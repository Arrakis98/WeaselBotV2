from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from weasel_bot_v2.config import DatabaseConfig, LibraryModerationConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Track, UserRecord
from weasel_bot_v2.repositories import QuarantineRepository, TrackRepository, UserRepository
from weasel_bot_v2.services.arcadia_quarantine import ArcadiaQuarantineService
from weasel_bot_v2.services.player_state import PlayerStateStore


def test_manifest_apply_uses_mediatool_bucket_and_is_idempotent(tmp_path: Path) -> None:
    database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel.db"))
    database.initialize()
    music = tmp_path / "music"
    quarantine = tmp_path / "quarantine"
    bot = SimpleNamespace(
        database=database,
        settings=SimpleNamespace(
            library_moderation=LibraryModerationConfig(
                admin_music_path=music,
                quarantine_path=quarantine,
            ),
            bot=SimpleNamespace(music_library=music),
        ),
        player_states=PlayerStateStore(),
    )
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Admin"))

    relative_path = "Artist/interview.opus"
    source = music / relative_path
    source.parent.mkdir(parents=True)
    source.write_bytes(b"interview")
    track = TrackRepository(database).upsert_local(
        Track(
            source="local",
            source_id=relative_path,
            relative_path=relative_path,
            file_name="interview.opus",
            display_title="interview",
            extension=".opus",
        )
    )
    manifest_path, validation_path = _write_reports(
        tmp_path,
        relative_path,
        hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    service = ArcadiaQuarantineService(
        bot,
        manifest_path=manifest_path,
        validation_path=validation_path,
    )

    result = service.apply(guild_id=123, requested_by_user_id=42)

    assert result.moved == 1
    assert not source.exists()
    assert (quarantine / "mediatool" / relative_path).is_file()
    record = QuarantineRepository(database).active_for_track(track.id or 0)
    assert record is not None
    assert record.quarantine_relative_path == f"mediatool/{relative_path}"
    second = service.apply(guild_id=123, requested_by_user_id=42)
    assert second.moved == 0
    assert second.already_quarantined == 1


def _write_reports(tmp_path: Path, relative_path: str, sha256: str) -> tuple[Path, Path]:
    operation = {
        "relative_path": relative_path,
        "source_sha256": sha256,
        "reasons": ["non_music"],
        "confidence": 1.0,
        "reference_file": "",
    }
    result = {
        "relative_path": relative_path,
        "reasons": ["non_music"],
        "reference_file": None,
        "reference_active": False,
        "safe_to_remove_quarantine_copy": False,
        "verdict": "non_music_candidate",
    }
    manifest = {
        "schema_version": 2,
        "kind": "arcadia_quarantine_manifest",
        "manifest_version": 2,
        "generated_at": "2026-06-17T02:44:11+00:00",
        "dry_run": True,
        "duplicate_threshold": 0.9,
        "reference_policy": "canonical_originality_first",
        "operation_count": 1,
        "reason_counts": {"non_music": 1},
        "operations": [operation],
    }
    validation = {
        "schema_version": 1,
        "validation_version": 1,
        "generated_at": "2026-06-17T02:44:12+00:00",
        "overall_status": "pass",
        "summary": {
            "quarantine_operations": 1,
            "quarantine_reason_counts": {"non_music": 1},
            "safe_duplicate_copies": 0,
            "non_music_candidates": 1,
            "checks_failed": 0,
            "checks_warning": 0,
        },
        "checks": [{"id": "all", "status": "pass"}],
        "quarantine_verification": {
            "operation_count": 1,
            "safe_duplicate_copies": 0,
            "blocked_duplicates": 0,
            "non_music_candidates": 1,
            "results": [result],
        },
    }
    manifest_path = tmp_path / "manifest.json"
    validation_path = tmp_path / "validation.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    validation_path.write_text(json.dumps(validation), encoding="utf-8")
    return manifest_path, validation_path
