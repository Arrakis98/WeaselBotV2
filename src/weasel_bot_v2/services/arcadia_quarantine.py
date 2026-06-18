from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from weasel_bot_v2.models import QuarantineRecord, Track
from weasel_bot_v2.repositories import QuarantineRepository, TrackRepository
from weasel_bot_v2.services.arcadia_manifest import (
    ArcadiaManifestOperation,
    load_arcadia_manifest,
)
from weasel_bot_v2.services.local_library import safe_relative_path
from weasel_bot_v2.services.quarantine import QuarantineService


@dataclass(frozen=True)
class PreparedArcadiaOperation:
    operation: ArcadiaManifestOperation
    track: Track


@dataclass(frozen=True)
class ArcadiaQuarantinePreview:
    digest: str
    generated_at: str
    operation_count: int
    prepared: tuple[PreparedArcadiaOperation, ...]
    already_quarantined: int
    blocked: tuple[str, ...]
    reason_counts: Mapping[str, int]

    @property
    def eligible(self) -> int:
        return len(self.prepared)

    @property
    def ok(self) -> bool:
        return not self.blocked


@dataclass(frozen=True)
class ArcadiaQuarantineResult:
    digest: str
    moved: int = 0
    already_quarantined: int = 0
    failed: int = 0
    removed_from_queue: int = 0
    records: tuple[QuarantineRecord, ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.failed == 0


class ArcadiaQuarantineService:
    def __init__(
        self,
        bot: Any,
        *,
        manifest_path: Path,
        validation_path: Path,
        admin_music_path: Path | None = None,
    ) -> None:
        self.bot = bot
        self.manifest_path = manifest_path
        self.validation_path = validation_path
        moderation = bot.settings.library_moderation
        self.admin_music_path = admin_music_path or moderation.admin_music_path
        self.tracks = TrackRepository(bot.database)
        self.quarantine = QuarantineRepository(bot.database)

    def preview(self, *, current_track_id: int | None = None) -> ArcadiaQuarantinePreview:
        manifest = load_arcadia_manifest(self.manifest_path, self.validation_path)
        selected_paths = {operation.relative_path for operation in manifest.operations}
        prepared: list[PreparedArcadiaOperation] = []
        blocked: list[str] = []
        already_quarantined = 0

        for operation in manifest.operations:
            track = self.tracks.get_local_by_relative_path(operation.relative_path)
            if track is None or track.id is None:
                blocked.append(f"{operation.relative_path}: track is not indexed")
                continue
            if self.quarantine.active_for_track(track.id) is not None:
                already_quarantined += 1
                continue
            if not track.is_available:
                blocked.append(f"{operation.relative_path}: indexed track is unavailable")
                continue
            if current_track_id is not None and track.id == current_track_id:
                blocked.append(f"{operation.relative_path}: track is currently playing")
                continue

            source = _resolved_child(self.admin_music_path, operation.relative_path)
            if not source.is_file():
                blocked.append(f"{operation.relative_path}: source file is missing")
                continue
            if _sha256_file(source) != operation.source_sha256:
                blocked.append(f"{operation.relative_path}: source SHA-256 changed")
                continue

            reference_error = self._reference_error(operation, selected_paths)
            if reference_error is not None:
                blocked.append(f"{operation.relative_path}: {reference_error}")
                continue
            prepared.append(PreparedArcadiaOperation(operation=operation, track=track))

        return ArcadiaQuarantinePreview(
            digest=manifest.digest,
            generated_at=manifest.generated_at,
            operation_count=len(manifest.operations),
            prepared=tuple(prepared),
            already_quarantined=already_quarantined,
            blocked=tuple(blocked),
            reason_counts=dict(Counter(operation.reason for operation in manifest.operations)),
        )

    def apply(
        self,
        *,
        guild_id: int,
        requested_by_user_id: int,
        current_track_id: int | None = None,
    ) -> ArcadiaQuarantineResult:
        preview = self.preview(current_track_id=current_track_id)
        if preview.blocked:
            return ArcadiaQuarantineResult(
                digest=preview.digest,
                already_quarantined=preview.already_quarantined,
                failed=len(preview.blocked),
                failures=preview.blocked,
            )

        moved = 0
        failed = 0
        already_quarantined = preview.already_quarantined
        removed_from_queue = 0
        records: list[QuarantineRecord] = []
        failures: list[str] = []
        quarantine_service = QuarantineService(self.bot)
        digest_prefix = preview.digest[:12]

        for prepared in preview.prepared:
            operation = prepared.operation
            result = quarantine_service.quarantine_track(
                prepared.track,
                guild_id=guild_id,
                requested_by_user_id=requested_by_user_id,
                reason=f"arcadia_manifest:{operation.reason}:{digest_prefix}",
                expected_sha256=operation.source_sha256,
                bucket="mediatool",
            )
            moved += result.moved
            failed += result.failed
            already_quarantined += result.already_quarantined
            removed_from_queue += result.removed_from_queue
            records.extend(result.records)
            failures.extend(result.failures)

        return ArcadiaQuarantineResult(
            digest=preview.digest,
            moved=moved,
            already_quarantined=already_quarantined,
            failed=failed,
            removed_from_queue=removed_from_queue,
            records=tuple(records),
            failures=tuple(failures),
        )

    def _reference_error(
        self,
        operation: ArcadiaManifestOperation,
        selected_paths: set[str],
    ) -> str | None:
        if operation.reason != "duplicate_high_confidence":
            return None
        reference_file = operation.reference_file
        if reference_file is None:
            return "duplicate reference is missing"
        if reference_file in selected_paths:
            return "duplicate reference is also selected for quarantine"
        reference = self.tracks.get_local_by_relative_path(reference_file)
        if reference is None or reference.id is None:
            return "duplicate reference is not indexed"
        if not reference.is_available:
            return "duplicate reference is unavailable"
        if self.quarantine.active_for_track(reference.id) is not None:
            return "duplicate reference is already quarantined"
        if not _resolved_child(self.admin_music_path, reference_file).is_file():
            return "duplicate reference file is missing"
        return None


def _resolved_child(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    child = (resolved_root / Path(*safe_relative_path(relative_path).parts)).resolve()
    try:
        child.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("resolved path escapes configured root") from exc
    return child


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
