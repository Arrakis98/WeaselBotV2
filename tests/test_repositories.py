from __future__ import annotations

from pathlib import Path

import pytest

from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import GuildSettings, Playlist, PlaylistItem, Track, UserRecord
from weasel_bot_v2.repositories import (
    GuildSettingsRepository,
    PlaylistRepository,
    TrackRepository,
    UserRepository,
)


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    sqlite_database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel-test.db"))
    sqlite_database.initialize()
    return sqlite_database


def test_guild_settings_create_and_fetch(database: SQLiteDatabase) -> None:
    repository = GuildSettingsRepository(database)

    created = repository.ensure(123)
    fetched = repository.get(123)

    assert created == GuildSettings(guild_id=123)
    assert fetched == created


def test_guild_settings_save_updates_values(database: SQLiteDatabase) -> None:
    repository = GuildSettingsRepository(database)

    saved = repository.save(
        GuildSettings(guild_id=123, command_prefix="!", locale="en-US", dj_role_id=456)
    )

    assert saved == GuildSettings(
        guild_id=123,
        command_prefix="!",
        locale="en-US",
        dj_role_id=456,
    )


def test_user_create_and_fetch(database: SQLiteDatabase) -> None:
    repository = UserRepository(database)

    created = repository.upsert(UserRecord(user_id=42, display_name="Test User"))
    fetched = repository.get(42)

    assert created == UserRecord(user_id=42, display_name="Test User")
    assert fetched == created


def test_basic_playlist_repository_behavior(database: SQLiteDatabase) -> None:
    users = UserRepository(database)
    tracks = TrackRepository(database)
    playlists = PlaylistRepository(database)
    users.upsert(UserRecord(user_id=42, display_name="Owner"))
    track = tracks.upsert(Track(source="test", source_id="track-1", title="Track One"))
    assert track.id is not None

    playlist = playlists.create(
        Playlist(guild_id=123, owner_user_id=42, name="Test Playlist", description="Phase 2")
    )
    playlists.add_item(
        PlaylistItem(
            playlist_id=playlist.id or 0,
            position=0,
            track_id=track.id,
            added_by_user_id=42,
        )
    )

    assert playlist.id is not None
    assert playlists.get(playlist.id) == playlist
    assert playlists.list_for_owner(42) == [playlist]
    assert playlists.list_items(playlist.id) == [
        PlaylistItem(
            playlist_id=playlist.id,
            position=0,
            track_id=track.id,
            added_by_user_id=42,
        )
    ]
