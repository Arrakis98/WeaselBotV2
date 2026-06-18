from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from weasel_bot_v2.config import DatabaseConfig, LibraryModerationConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Rating, Track, UserRecord
from weasel_bot_v2.repositories import (
    QuarantineRepository,
    RatingRepository,
    TrackRepository,
    UserRepository,
)
from weasel_bot_v2.services.local_library import LocalLibraryService
from weasel_bot_v2.services.player_state import PlayerStateStore
from weasel_bot_v2.services.quarantine import QuarantineService


def test_quarantine_preview_does_not_move_files(tmp_path: Path) -> None:
    bot, database, admin_root, quarantine_root = _bot(tmp_path)
    track = _track(database, admin_root, "Artist/song.mp3")
    _superdislike(database, track)

    preview = QuarantineService(bot).preview_superdisliked(123)

    assert len(preview.eligible) == 1
    assert (admin_root / "Artist/song.mp3").exists()
    assert not (quarantine_root / "superdislike/Artist/song.mp3").exists()


def test_quarantine_preview_blocks_current_track(tmp_path: Path) -> None:
    bot, database, admin_root, _ = _bot(tmp_path)
    track = _track(database, admin_root, "Artist/song.mp3")
    _superdislike(database, track)
    assert track.id is not None

    preview = QuarantineService(bot).preview_superdisliked(
        123,
        current_track_id=track.id,
    )

    assert preview.eligible == ()
    assert "currently playing" in preview.cannot_move[0]


def test_quarantine_execute_moves_indexed_file_and_removes_future_queue(tmp_path: Path) -> None:
    bot, database, admin_root, quarantine_root = _bot(tmp_path)
    track = _track(database, admin_root, "Artist/song.mp3")
    _superdislike(database, track)
    bot.player_states.get_or_create(123).upcoming = [track, track]

    result = QuarantineService(bot).purge_superdisliked(
        guild_id=123,
        requested_by_user_id=42,
    )

    stored = TrackRepository(database).get(track.id or 0)
    assert result.moved == 1
    assert result.removed_from_queue == 2
    assert stored is not None and stored.is_available is False
    assert not (admin_root / "Artist/song.mp3").exists()
    assert (quarantine_root / "superdislike/Artist/song.mp3").exists()
    assert RatingRepository(database).get_rating(123, 42, track.id or 0) is not None
    assert QuarantineRepository(database).active_for_track(track.id or 0) is not None
    indexed_tracks = LocalLibraryService(
        admin_root,
        TrackRepository(database),
    ).list_indexed_mp3_tracks()
    assert indexed_tracks == []


def test_quarantine_does_not_move_same_track_twice_and_handles_collision(tmp_path: Path) -> None:
    bot, database, admin_root, quarantine_root = _bot(tmp_path)
    existing = quarantine_root / "superdislike/Artist/song.mp3"
    existing.parent.mkdir(parents=True)
    existing.write_text("occupied", encoding="utf-8")
    track = _track(database, admin_root, "Artist/song.mp3")
    _superdislike(database, track)

    first = QuarantineService(bot).purge_superdisliked(
        guild_id=123,
        requested_by_user_id=42,
    )
    second = QuarantineService(bot).purge_superdisliked(
        guild_id=123,
        requested_by_user_id=42,
    )

    assert first.moved == 1
    assert (quarantine_root / "superdislike/Artist/song-1.mp3").exists()
    assert second.already_quarantined == 1
    assert second.moved == 0


def test_restore_returns_file_and_makes_track_playable(tmp_path: Path) -> None:
    bot, database, admin_root, quarantine_root = _bot(tmp_path)
    track = _track(database, admin_root, "Artist/song.mp3")
    _superdislike(database, track)
    moved = QuarantineService(bot).purge_superdisliked(
        guild_id=123,
        requested_by_user_id=42,
    )
    record = moved.records[0]

    restored = QuarantineService(bot).restore(record.id or 0)

    stored = TrackRepository(database).get(track.id or 0)
    assert restored.ok is True
    assert stored is not None and stored.is_available is True
    assert (admin_root / "Artist/song.mp3").exists()
    assert not (quarantine_root / "superdislike/Artist/song.mp3").exists()
    assert QuarantineRepository(database).get(record.id or 0).state == "restored"  # type: ignore[union-attr]


def test_quarantine_rejects_path_traversal_and_missing_unindexed_file(tmp_path: Path) -> None:
    bot, database, admin_root, _ = _bot(tmp_path)
    traversal = TrackRepository(database).upsert(
        Track(source="local", source_id="../bad.mp3", relative_path="../bad.mp3")
    )
    unindexed = Track(source="local", source_id="missing.mp3", relative_path="missing.mp3")

    bad = QuarantineService(bot).quarantine_track(
        traversal,
        guild_id=123,
        requested_by_user_id=42,
        reason="test",
    )
    missing = QuarantineService(bot).quarantine_track(
        unindexed,
        guild_id=123,
        requested_by_user_id=42,
        reason="test",
    )

    assert bad.failed == 1
    assert missing.skipped == 1
    assert list(admin_root.rglob("*")) == []


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
    return bot, database, admin_root, quarantine_root


def _track(database: SQLiteDatabase, root: Path, relative_path: str) -> Track:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("audio", encoding="utf-8")
    return TrackRepository(database).upsert_local(
        Track(
            source="local",
            source_id=relative_path,
            relative_path=relative_path,
            file_name=Path(relative_path).name,
            display_title=Path(relative_path).stem,
            artist_guess="Artist",
            extension=".mp3",
        )
    )


def _superdislike(database: SQLiteDatabase, track: Track) -> None:
    assert track.id is not None
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Admin"))
    RatingRepository(database).set_rating(
        Rating(guild_id=123, user_id=42, track_id=track.id, rating="superdislike")
    )
