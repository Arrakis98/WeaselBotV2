from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from weasel_bot_v2.config import DatabaseConfig, LibraryModerationConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import QuarantineRecord, Track, UserRecord
from weasel_bot_v2.repositories import QuarantineRepository, TrackRepository, UserRepository
from weasel_bot_v2.services.player_state import PlayerStateStore
from weasel_bot_v2.services.quarantine import QuarantineService, quarantine_bucket_for_reason
from weasel_bot_v2.services.quarantine_layout import QuarantineLayoutService


def test_layout_migrates_legacy_mediatool_record_and_restore_works(tmp_path: Path) -> None:
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
    track = TrackRepository(database).upsert_local(
        Track(
            source="local",
            source_id="Artist/interview.mp3",
            relative_path="Artist/interview.mp3",
            file_name="interview.mp3",
            extension=".mp3",
            is_available=False,
        )
    )
    assert track.id is not None
    legacy = quarantine / "super_disliked/Artist/interview.mp3"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"audio")
    record = QuarantineRepository(database).create(
        QuarantineRecord(
            track_id=track.id,
            guild_id=123,
            requested_by_user_id=42,
            reason="arcadia_manifest:non_music:abc123",
            original_relative_path="Artist/interview.mp3",
            quarantine_relative_path="Artist/interview.mp3",
        )
    )

    preview = QuarantineLayoutService(bot).preview()
    result = QuarantineLayoutService(bot).apply()

    assert preview.ok is True
    assert len(preview.eligible) == 1
    assert result.migrated == 1
    assert not legacy.exists()
    assert (quarantine / "mediatool/Artist/interview.mp3").is_file()
    stored = QuarantineRepository(database).get(record.id or 0)
    assert stored is not None
    assert stored.quarantine_relative_path == "mediatool/Artist/interview.mp3"
    restored = QuarantineService(bot).restore(record.id or 0)
    assert restored.ok is True
    assert (music / "Artist/interview.mp3").is_file()


def test_reason_routes_to_expected_bucket() -> None:
    assert quarantine_bucket_for_reason("purge_superdisliked") == "superdislike"
    assert quarantine_bucket_for_reason("arcadia_manifest:non_music:abc") == "mediatool"
