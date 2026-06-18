from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

from weasel_bot_v2.models import QuarantineRecord
from weasel_bot_v2.repositories import QuarantineRepository
from weasel_bot_v2.services.local_library import safe_relative_path
from weasel_bot_v2.services.quarantine import quarantine_bucket_for_reason

_CURRENT_BUCKETS = {"superdislike", "mediatool"}
_LEGACY_BUCKET = "super_disliked"


@dataclass(frozen=True)
class QuarantineLayoutMove:
    record: QuarantineRecord
    source_relative_path: str
    target_relative_path: str


@dataclass(frozen=True)
class QuarantineLayoutPreview:
    eligible: tuple[QuarantineLayoutMove, ...]
    already_current: int
    blocked: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.blocked


@dataclass(frozen=True)
class QuarantineLayoutResult:
    migrated: int = 0
    already_current: int = 0
    failed: int = 0
    failures: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.failed == 0


class QuarantineLayoutService:
    """Move legacy quarantine records into source-specific subdirectories."""

    def __init__(self, bot: Any, *, quarantine_path: Path | None = None) -> None:
        self.quarantine_path = quarantine_path or bot.settings.library_moderation.quarantine_path
        self.records = QuarantineRepository(bot.database)

    def preview(self) -> QuarantineLayoutPreview:
        eligible: list[QuarantineLayoutMove] = []
        blocked: list[str] = []
        already_current = 0

        for record in self.records.list_active_records():
            try:
                stored_relative = safe_relative_path(record.quarantine_relative_path)
            except ValueError as exc:
                blocked.append(f"record {record.id}: invalid stored path ({exc})")
                continue

            if stored_relative.parts and stored_relative.parts[0] in _CURRENT_BUCKETS:
                already_current += 1
                continue

            bucket = quarantine_bucket_for_reason(record.reason)
            target_relative = Path(bucket, *stored_relative.parts)
            source_relative = self._legacy_source_relative(stored_relative)
            if source_relative is None:
                blocked.append(f"record {record.id}: quarantined file is missing")
                continue

            source = _resolved_child(self.quarantine_path, source_relative.as_posix())
            target = _resolved_child(self.quarantine_path, target_relative.as_posix())
            if target.exists() and target != source:
                blocked.append(f"record {record.id}: target path is already occupied")
                continue

            eligible.append(
                QuarantineLayoutMove(
                    record=record,
                    source_relative_path=source_relative.as_posix(),
                    target_relative_path=target_relative.as_posix(),
                )
            )

        return QuarantineLayoutPreview(
            eligible=tuple(eligible),
            already_current=already_current,
            blocked=tuple(blocked),
        )

    def apply(self) -> QuarantineLayoutResult:
        preview = self.preview()
        if preview.blocked:
            return QuarantineLayoutResult(
                already_current=preview.already_current,
                failed=len(preview.blocked),
                failures=preview.blocked,
            )

        migrated = 0
        failures: list[str] = []
        for move in preview.eligible:
            record_id = move.record.id
            if record_id is None:
                failures.append("quarantine record has no ID")
                continue
            source = _resolved_child(self.quarantine_path, move.source_relative_path)
            target = _resolved_child(self.quarantine_path, move.target_relative_path)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(source.as_posix(), target.as_posix())
                try:
                    self.records.update_relative_path(record_id, move.target_relative_path)
                except Exception:
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(target.as_posix(), source.as_posix())
                    raise
            except Exception as exc:  # noqa: BLE001 - report per-record migration failures.
                failures.append(f"record {record_id}: {exc.__class__.__name__}")
                continue
            migrated += 1

        return QuarantineLayoutResult(
            migrated=migrated,
            already_current=preview.already_current,
            failed=len(failures),
            failures=tuple(failures),
        )

    def _legacy_source_relative(
        self,
        stored_relative: PurePath,
    ) -> PurePath | None:
        direct = _resolved_child(self.quarantine_path, stored_relative.as_posix())
        if direct.is_file():
            return stored_relative
        legacy = Path(_LEGACY_BUCKET, *stored_relative.parts)
        if _resolved_child(self.quarantine_path, legacy.as_posix()).is_file():
            return legacy
        return None


def _resolved_child(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    child = (resolved_root / Path(*safe_relative_path(relative_path).parts)).resolve()
    try:
        child.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("resolved path escapes configured quarantine root") from exc
    return child
