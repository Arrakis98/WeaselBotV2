from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from weasel_bot_v2.models import QuarantineRecord, Track
from weasel_bot_v2.repositories import QuarantineRepository, RatingRepository, TrackRepository
from weasel_bot_v2.services.local_library import safe_relative_path

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuarantineMoveResult:
    moved: int = 0
    skipped: int = 0
    already_quarantined: int = 0
    failed: int = 0
    removed_from_queue: int = 0
    records: tuple[QuarantineRecord, ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.failed == 0


@dataclass(frozen=True)
class PurgePreview:
    eligible: tuple[Track, ...]
    already_quarantined: int
    cannot_move: tuple[str, ...]
    destination: str


@dataclass(frozen=True)
class RestoreResult:
    ok: bool
    message: str
    record: QuarantineRecord | None = None


class QuarantineService:
    def __init__(
        self,
        bot: Any,
        *,
        admin_music_path: Path | None = None,
        quarantine_path: Path | None = None,
    ) -> None:
        self.bot = bot
        moderation = bot.settings.library_moderation
        self.admin_music_path = admin_music_path or moderation.admin_music_path
        self.quarantine_path = quarantine_path or moderation.quarantine_path
        self.tracks = TrackRepository(bot.database)
        self.quarantine = QuarantineRepository(bot.database)
        self.ratings = RatingRepository(bot.database)

    def preview_superdisliked(self, guild_id: int) -> PurgePreview:
        eligible: list[Track] = []
        cannot_move: list[str] = []
        already = 0
        for track in self._superdisliked_tracks(guild_id, available_only=False):
            if track.id is None:
                continue
            if self.quarantine.active_for_track(track.id) is not None:
                already += 1
                continue
            if not track.is_available:
                continue
            reason = self._cannot_move_reason(track)
            if reason:
                cannot_move.append(f"{_track_title(track)}: {reason}")
                continue
            eligible.append(track)
        return PurgePreview(
            eligible=tuple(eligible),
            already_quarantined=already,
            cannot_move=tuple(cannot_move),
            destination=self.quarantine_path.as_posix(),
        )

    def quarantine_track(
        self,
        track: Track,
        *,
        guild_id: int,
        requested_by_user_id: int,
        reason: str,
    ) -> QuarantineMoveResult:
        builder = _QuarantineResultBuilder()
        record = self._quarantine_one(
            track,
            guild_id=guild_id,
            requested_by_user_id=requested_by_user_id,
            reason=reason,
            builder=builder,
        )
        if record is not None:
            builder.records.append(record)
        return builder.build()

    def purge_superdisliked(
        self,
        *,
        guild_id: int,
        requested_by_user_id: int,
        exclude_track_ids: set[int] | None = None,
    ) -> QuarantineMoveResult:
        builder = _QuarantineResultBuilder()
        excluded = exclude_track_ids or set()
        for track in self._superdisliked_tracks(guild_id, available_only=False):
            if track.id in excluded:
                builder.skipped += 1
                continue
            if track.id is not None and self.quarantine.active_for_track(track.id) is not None:
                builder.already_quarantined += 1
                continue
            if not track.is_available:
                builder.skipped += 1
                continue
            record = self._quarantine_one(
                track,
                guild_id=guild_id,
                requested_by_user_id=requested_by_user_id,
                reason="purge_superdisliked",
                builder=builder,
            )
            if record is not None:
                builder.records.append(record)
        return builder.build()

    def restore(self, record_id: int) -> RestoreResult:
        record = self.quarantine.get(record_id)
        if record is None:
            return RestoreResult(ok=False, message="No quarantine record exists with that ID.")
        if record.state != "quarantined":
            return RestoreResult(ok=False, message="That quarantine record is already restored.")

        try:
            original_relative = safe_relative_path(record.original_relative_path)
            quarantine_relative = safe_relative_path(record.quarantine_relative_path)
            source = _resolved_child(self.quarantine_path, quarantine_relative.as_posix())
            destination = _resolved_child(self.admin_music_path, original_relative.as_posix())
        except ValueError as exc:
            return RestoreResult(ok=False, message=f"Restore path validation failed: {exc}.")

        if not source.exists() or not source.is_file():
            return RestoreResult(ok=False, message="The quarantined file is missing.")
        if destination.exists():
            return RestoreResult(
                ok=False,
                message="The original library path is occupied; restore skipped safely.",
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source.as_posix(), destination.as_posix())
        self.tracks.set_available(record.track_id, True)
        self.quarantine.mark_restored(record.id or record_id)
        restored = self.quarantine.get(record.id or record_id)
        return RestoreResult(
            ok=True,
            message="Track restored to the playable library.",
            record=restored,
        )

    def _quarantine_one(
        self,
        track: Track,
        *,
        guild_id: int,
        requested_by_user_id: int,
        reason: str,
        builder: _QuarantineResultBuilder,
    ) -> QuarantineRecord | None:
        if track.id is None or not track.relative_path:
            builder.skipped += 1
            return None
        if self.quarantine.active_for_track(track.id) is not None:
            builder.already_quarantined += 1
            return None

        try:
            relative = safe_relative_path(track.relative_path)
            source = _resolved_child(self.admin_music_path, relative.as_posix())
            destination = _collision_safe_path(
                _resolved_child(self.quarantine_path, relative.as_posix())
            )
        except ValueError as exc:
            builder.failed += 1
            builder.failures.append(f"{_track_title(track)}: {exc}")
            return None

        if not source.exists() or not source.is_file():
            builder.failed += 1
            builder.failures.append(f"{_track_title(track)}: source file is missing")
            return None

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(source.as_posix(), destination.as_posix())
            self.tracks.set_available(track.id, False)
            builder.removed_from_queue += self._remove_from_future_queues(track.id)
            builder.moved += 1
            return self.quarantine.create(
                QuarantineRecord(
                    track_id=track.id,
                    guild_id=guild_id,
                    requested_by_user_id=requested_by_user_id,
                    reason=reason,
                    original_relative_path=relative.as_posix(),
                    quarantine_relative_path=destination.relative_to(
                        self.quarantine_path.resolve()
                    ).as_posix(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - moderation should report per-track failures.
            LOGGER.warning(
                "Quarantine failed track_id=%s guild_id=%s error=%s",
                track.id,
                guild_id,
                exc.__class__.__name__,
            )
            builder.failed += 1
            builder.failures.append(f"{_track_title(track)}: {exc.__class__.__name__}")
            return None

    def _cannot_move_reason(self, track: Track) -> str | None:
        if track.id is None or not track.relative_path:
            return "track is not indexed with a local path"
        try:
            relative = safe_relative_path(track.relative_path)
            source = _resolved_child(self.admin_music_path, relative.as_posix())
        except ValueError as exc:
            return str(exc)
        if not source.exists():
            return "source file is missing"
        if not source.is_file():
            return "source path is not a file"
        return None

    def _superdisliked_tracks(self, guild_id: int, *, available_only: bool = True) -> list[Track]:
        track_ids = self.ratings.track_ids_for_rating(guild_id, "superdislike")
        tracks = [self.tracks.get(track_id) for track_id in track_ids]
        return [
            track
            for track in tracks
            if track is not None and (track.is_available or not available_only)
        ]

    def _remove_from_future_queues(self, track_id: int) -> int:
        removed = 0
        states = getattr(self.bot.player_states, "_states", {})
        for state in list(states.values()):
            removed += state.remove_upcoming_track(track_id)
        return removed


@dataclass
class _QuarantineResultBuilder:
    moved: int = 0
    skipped: int = 0
    already_quarantined: int = 0
    failed: int = 0
    removed_from_queue: int = 0
    records: list[QuarantineRecord] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def build(self) -> QuarantineMoveResult:
        return QuarantineMoveResult(
            moved=self.moved,
            skipped=self.skipped,
            already_quarantined=self.already_quarantined,
            failed=self.failed,
            removed_from_queue=self.removed_from_queue,
            records=tuple(self.records),
            failures=tuple(self.failures),
        )


def _resolved_child(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    child = (resolved_root / Path(*safe_relative_path(relative_path).parts)).resolve()
    try:
        child.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("resolved path escapes configured root") from exc
    return child


def _collision_safe_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _track_title(track: Track) -> str:
    return (
        _clean(track.display_title)
        or _clean(track.title)
        or _clean(track.file_name)
        or "Unknown local track"
    )


def _clean(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
