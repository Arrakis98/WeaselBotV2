from __future__ import annotations

from pathlib import Path
from typing import Any, cast

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
from weasel_bot_v2.services.audio import AudioPlaybackService
from weasel_bot_v2.services.guild_settings import GuildSettingsService
from weasel_bot_v2.services.player_state import (
    DEFAULT_VOLUME,
    MAX_VOLUME,
    MIN_VOLUME,
    PlayerStateStore,
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
        GuildSettings(
            guild_id=123,
            command_prefix="!",
            locale="en-US",
            dj_role_id=456,
            default_volume=75,
        )
    )

    assert saved == GuildSettings(
        guild_id=123,
        command_prefix="!",
        locale="en-US",
        dj_role_id=456,
        default_volume=75,
    )


def test_guild_settings_volume_defaults_to_100_when_unset(
    database: SQLiteDatabase,
) -> None:
    service = GuildSettingsService(GuildSettingsRepository(database))

    assert service.get_volume(123) == DEFAULT_VOLUME


def test_guild_settings_volume_is_saved_and_retrieved(database: SQLiteDatabase) -> None:
    service = GuildSettingsService(GuildSettingsRepository(database))

    assert service.set_volume(123, 80) == 80
    assert service.get_volume(123) == 80


def test_guild_settings_volume_clamps_low(database: SQLiteDatabase) -> None:
    service = GuildSettingsService(GuildSettingsRepository(database))

    assert service.set_volume(123, -50) == MIN_VOLUME
    assert service.get_volume(123) == MIN_VOLUME


def test_guild_settings_volume_clamps_high(database: SQLiteDatabase) -> None:
    service = GuildSettingsService(GuildSettingsRepository(database))

    assert service.set_volume(123, 999) == MAX_VOLUME
    assert service.get_volume(123) == MAX_VOLUME


@pytest.mark.asyncio
async def test_audio_set_volume_saves_and_syncs_state(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    service = AudioPlaybackService(bot, Path("/music"))

    result = await service.set_volume(cast(Any, guild), 65)

    assert result.ok is True
    assert GuildSettingsService(GuildSettingsRepository(database)).get_volume(123) == 65
    assert bot.player_states.get_or_create(123).volume == 65


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


class _FakeBot:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        self.player_states = PlayerStateStore()


class _FakeGuild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id
        self.voice_client: Any = None
