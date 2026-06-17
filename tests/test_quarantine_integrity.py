from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from weasel_bot_v2.config import DatabaseConfig, LibraryModerationConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Track, UserRecord
from weasel_bot_v2.repositories import TrackRepository, UserRepository
from weasel_bot_v2.services.player_state import PlayerStateStore
from weasel_bot_v2.services.quarantine import QuarantineService


def test_quarantine_rejects_changed_sha256(tmp_path: Path) -> None:
    bot, database, admin_root, quarantine_root = _bot(tmp_path)
    track = _track(database, admin_root, "Artist/song.mp3")
    assert track.id is not None
    assert track.relative_path is not None

    result = QuarantineService(bot).quarantine_track(
        track,
        guild_id=123,
        requested_by_user_id=42,
        reason="test",
        expected_sha256="0" * 64,
    )

    stored = TrackRepository(database).get(track.id)
    assert result.failed == 1
    assert result.moved == 0
    assert stored is not None and stored.is_available is True
    assert (admin_root / track.relative_path).is_file()
    assert not (quarantine_root / track.relative_path).exists()


def test_quarantine_rolls_back_when_record_creation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot, database, admin_root, quarantine_root = _bot(tmp_path)
    track = _track(database, admin_root, "Artist/song.mp3")
    assert track.id is not None
    assert track.relative_path is not None
    service = QuarantineService(bot)

    def fail_create(record: object) -> None:
        del record
        raise RuntimeError("database write failed")

    monkeypatch.setattr(service.quarantine, "create", fail_create)
    expected_sha256 = hashlib.sha256((admin_root / track.relative_path).read_bytes()).hexdigest()
    result = service.quarantine_track(
        track,
        guild_id=123,
        requested_by_user_id=42,
        reason="test",
        expected_sha256=expected_sha256,
    )

    stored = TrackRepository(database).get(track.id)
    assert result.failed == 1
    assert result.moved == 0
    assert stored is not None and stored.is_available is True
    assert (admin_root / track.relative_path).is_file()
    assert not (quarantine_root / track.relative_path).exists()


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


def _track(database: SQLiteDatabase, root: Path, relative_path: str) -> Track:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"audio")
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
