from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from weasel_bot_v2.config import DatabaseConfig, LibraryModerationConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Track, UserRecord
from weasel_bot_v2.repositories import (
    QuarantineRepository,
    TrackRepository,
    UserRepository,
)
from weasel_bot_v2.services.arcadia_quarantine import ArcadiaQuarantineService
from weasel_bot_v2.services.player_state import PlayerStateStore


def test_manifest_apply_is_reversible_and_idempotent(tmp_path: Path) -> None:
    bot, database, admin_root, quarantine_root = _bot(tmp_path)
    reference = _track(database, admin_root, "Artist/reference.mp3", b"reference")
    duplicate = _track(database, admin_root, "Artist/copy.mp3", b"duplicate")
    non_music = _track(database, admin_root, "Artist/interview.mp3", b"interview")
    assert reference.relative_path is not None
    assert duplicate.relative_path is not None
    assert non_music.relative_path is not None
    manifest_path, validation_path = _reports(
        tmp_path,
        admin_root,
        reference,
        duplicate,
        non_music,
    )
    service = ArcadiaQuarantineService(
        bot,
        manifest_path=manifest_path,
        validation_path=validation_path,
    )

    preview = service.preview()
    result = service.apply(guild_id=123, requested_by_user_id=42)

    assert preview.ok is True
    assert preview.eligible == 2
    assert result.ok is True
    assert result.moved == 2
    assert (admin_root / reference.relative_path).is_file()
    assert not (admin_root / duplicate.relative_path).exists()
    assert not (admin_root / non_music.relative_path).exists()
    assert (quarantine_root / duplicate.relative_path).is_file()
    assert (quarantine_root / non_music.relative_path).is_file()
    record = QuarantineRepository(database).active_for_track(duplicate.id or 0)
    assert record is not None
    assert record.reason.startswith("arcadia_manifest:duplicate_high_confidence:")

    second = service.apply(guild_id=123, requested_by_user_id=42)
    assert second.ok is True
    assert second.moved == 0
    assert second.already_quarantined == 2


def _bot(tmp_path: Path) -> tuple[Any, SQLiteDatabase, Path, Path]:
    database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel.db"))
    database.initialize()
    admin_root = tmp_path / "admin_music"
    quarantine_root = tmp_path / "quarantine"
    settings = SimpleNamespace(
        library_moderation=LibraryModerationConfig(
            admin_music_path=admin_root,
            quarantine_path=quarantine_root,
            auto_quarantine_superdislike=False,
        ),
        bot=SimpleNamespace(music_library=admin_root),
    )
    bot = SimpleNamespace(
        database=database,
        settings=settings,
        player_states=PlayerStateStore(),
    )
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Admin"))
    return bot, database, admin_root, quarantine_root


def _track(
    database: SQLiteDatabase,
    root: Path,
    relative_path: str,
    content: bytes,
) -> Track:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return TrackRepository(database).upsert_local(
        Track(
            source="local",
            source_id=relative_path,
            relative_path=relative_path,
            file_name=path.name,
            display_title=path.stem,
            artist_guess="Artist",
            extension=".mp3",
        )
    )


def _reports(
    tmp_path: Path,
    admin_root: Path,
    reference: Track,
    duplicate: Track,
    non_music: Track,
) -> tuple[Path, Path]:
    assert reference.relative_path is not None
    assert duplicate.relative_path is not None
    assert non_music.relative_path is not None
    operations = [
        {
            "relative_path": duplicate.relative_path,
            "source_sha256": _sha256(admin_root / duplicate.relative_path),
            "reasons": ["duplicate_high_confidence"],
            "confidence": 0.98,
            "reference_file": reference.relative_path,
        },
        {
            "relative_path": non_music.relative_path,
            "source_sha256": _sha256(admin_root / non_music.relative_path),
            "reasons": ["non_music"],
            "confidence": 1.0,
            "reference_file": "",
        },
    ]
    manifest = {
        "schema_version": 2,
        "kind": "arcadia_quarantine_manifest",
        "manifest_version": 2,
        "generated_at": "2026-06-17T02:44:11.391265+00:00",
        "dry_run": True,
        "duplicate_threshold": 0.9,
        "reference_policy": "canonical_originality_first",
        "operation_count": 2,
        "reason_counts": {
            "duplicate_high_confidence": 1,
            "non_music": 1,
        },
        "operations": operations,
    }
    validation = {
        "schema_version": 1,
        "validation_version": 1,
        "generated_at": "2026-06-17T02:44:11.392144+00:00",
        "overall_status": "pass",
        "summary": {
            "quarantine_operations": 2,
            "quarantine_reason_counts": {
                "duplicate_high_confidence": 1,
                "non_music": 1,
            },
            "safe_duplicate_copies": 1,
            "non_music_candidates": 1,
            "checks_failed": 0,
            "checks_warning": 0,
        },
        "checks": [{"id": "all", "status": "pass"}],
        "quarantine_verification": {
            "operation_count": 2,
            "safe_duplicate_copies": 1,
            "blocked_duplicates": 0,
            "non_music_candidates": 1,
            "results": [
                {
                    "relative_path": duplicate.relative_path,
                    "reasons": ["duplicate_high_confidence"],
                    "reference_file": reference.relative_path,
                    "reference_active": True,
                    "safe_to_remove_quarantine_copy": True,
                    "verdict": "safe_duplicate_copy",
                },
                {
                    "relative_path": non_music.relative_path,
                    "reasons": ["non_music"],
                    "reference_file": None,
                    "reference_active": False,
                    "safe_to_remove_quarantine_copy": False,
                    "verdict": "non_music_candidate",
                },
            ],
        },
    }
    manifest_path = tmp_path / "manifest.json"
    validation_path = tmp_path / "validation.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    validation_path.write_text(json.dumps(validation), encoding="utf-8")
    return manifest_path, validation_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
