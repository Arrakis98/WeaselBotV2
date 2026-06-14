from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import GuildSettings, Playlist, PlaylistItem, Track, UserRecord
from weasel_bot_v2.repositories import (
    GuildSettingsRepository,
    PlaylistRepository,
    TrackRepository,
    TrackVolumeOverrideRepository,
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
from weasel_bot_v2.services.volume import VolumeService, VolumeSource


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
async def test_audio_set_volume_saves_track_override_and_syncs_state(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    service = AudioPlaybackService(bot, Path("/music"))
    track = TrackRepository(database).upsert(Track(source="local", source_id="one.mp3"))
    bot.player_states.get_or_create(123).current_track = track

    result = await service.set_volume(cast(Any, guild), 65)

    assert result.ok is True
    assert GuildSettingsService(GuildSettingsRepository(database)).get_volume(123) == 100
    override = TrackVolumeOverrideRepository(database).get(123, track.id or 0)
    assert override is not None
    assert override.volume == 65
    assert bot.player_states.get_or_create(123).volume == 65


def test_track_volume_override_takes_priority_over_guild_default(
    database: SQLiteDatabase,
) -> None:
    service = _volume_service(database)
    track = TrackRepository(database).upsert(Track(source="local", source_id="one.mp3"))

    service.set_guild_default(123, 90)
    service.set_track_override(123, track.id or 0, 140)

    resolved = service.resolve(123, track)
    assert resolved.volume == 140
    assert resolved.source is VolumeSource.TRACK
    assert resolved.guild_default == 100


def test_no_track_volume_override_resolves_to_exactly_100(
    database: SQLiteDatabase,
) -> None:
    service = _volume_service(database)
    track = TrackRepository(database).upsert(Track(source="local", source_id="one.mp3"))

    service.set_guild_default(123, 65)

    resolved = service.resolve(123, track)
    assert resolved.volume == 100
    assert resolved.source is VolumeSource.DEFAULT
    assert resolved.guild_default == 100


def test_different_tracks_in_same_guild_can_have_different_volumes(
    database: SQLiteDatabase,
) -> None:
    service = _volume_service(database)
    tracks = TrackRepository(database)
    first = tracks.upsert(Track(source="local", source_id="one.mp3"))
    second = tracks.upsert(Track(source="local", source_id="two.mp3"))

    service.set_track_override(123, first.id or 0, 140)
    service.set_track_override(123, second.id or 0, 85)

    assert service.resolve(123, first).volume == 140
    assert service.resolve(123, second).volume == 85


def test_same_track_can_have_different_volumes_in_different_guilds(
    database: SQLiteDatabase,
) -> None:
    service = _volume_service(database)
    track = TrackRepository(database).upsert(Track(source="local", source_id="one.mp3"))

    service.set_track_override(123, track.id or 0, 140)
    service.set_track_override(456, track.id or 0, 85)

    assert service.resolve(123, track).volume == 140
    assert service.resolve(456, track).volume == 85


def test_changing_guild_default_does_not_overwrite_track_override(
    database: SQLiteDatabase,
) -> None:
    service = _volume_service(database)
    track = TrackRepository(database).upsert(Track(source="local", source_id="one.mp3"))

    service.set_track_override(123, track.id or 0, 140)
    service.set_guild_default(123, 80)

    assert service.resolve(123, track).volume == 140
    assert service.resolve(123, track).guild_default == 100


def test_track_volume_override_clamps_values(database: SQLiteDatabase) -> None:
    service = _volume_service(database)
    track = TrackRepository(database).upsert(Track(source="local", source_id="one.mp3"))

    service.set_track_override(123, track.id or 0, -50)
    assert service.resolve(123, track).volume == MIN_VOLUME

    service.set_track_override(123, track.id or 0, 999)
    assert service.resolve(123, track).volume == MAX_VOLUME


@pytest.mark.asyncio
async def test_track_change_loads_new_effective_volume_without_carryover(
    database: SQLiteDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "mafic", SimpleNamespace())
    bot = _FakeBot(database)
    bot.lavalink_available = True
    guild = _FakeGuild(guild_id=123)
    player = _FakePlayer()
    guild.voice_client = player
    service = _FakeAudioPlaybackService(bot, Path("/music"))
    tracks = TrackRepository(database)
    first = tracks.upsert(
        Track(
            source="local",
            source_id="one.mp3",
            relative_path="one.mp3",
            file_name="one.mp3",
        )
    )
    second = tracks.upsert(
        Track(
            source="local",
            source_id="two.mp3",
            relative_path="two.mp3",
            file_name="two.mp3",
        )
    )
    volume = _volume_service(database)
    volume.set_guild_default(123, 90)
    volume.set_track_override(123, first.id or 0, 140)

    first_result = await service.play_track_on_player(
        guild=cast(Any, guild),
        player=player,
        track=first,
    )
    second_result = await service.play_track_on_player(
        guild=cast(Any, guild),
        player=player,
        track=second,
    )

    assert first_result.ok is True
    assert second_result.ok is True
    assert player.volumes == [140, 100]
    assert bot.player_states.get_or_create(123).volume == 100


@pytest.mark.asyncio
async def test_volume_button_style_change_saves_current_track_override(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    guild.voice_client = _FakePlayer()
    service = AudioPlaybackService(bot, Path("/music"))
    track = TrackRepository(database).upsert(Track(source="local", source_id="one.mp3"))
    state = bot.player_states.get_or_create(123)
    state.current_track = track
    state.volume = 100

    result = await service.change_volume(cast(Any, guild), 10)

    assert result.ok is True
    override = TrackVolumeOverrideRepository(database).get(123, track.id or 0)
    assert override is not None
    assert override.volume == 110
    assert state.volume == 110


@pytest.mark.asyncio
async def test_volume_button_change_begins_from_100_without_preset(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    guild.voice_client = _FakePlayer()
    service = AudioPlaybackService(bot, Path("/music"))
    track = TrackRepository(database).upsert(Track(source="local", source_id="one.mp3"))
    state = bot.player_states.get_or_create(123)
    state.current_track = track
    state.volume = 140

    result = await service.change_volume(cast(Any, guild), 10)

    assert result.ok is True
    override = TrackVolumeOverrideRepository(database).get(123, track.id or 0)
    assert override is not None
    assert override.volume == 110
    assert state.volume == 110


@pytest.mark.asyncio
async def test_reset_track_volume_removes_override_and_restores_default(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    guild.voice_client = _FakePlayer()
    service = AudioPlaybackService(bot, Path("/music"))
    track = TrackRepository(database).upsert(Track(source="local", source_id="one.mp3"))
    state = bot.player_states.get_or_create(123)
    state.current_track = track
    state.volume = 140
    volume = _volume_service(database)
    volume.set_guild_default(123, 90)
    volume.set_track_override(123, track.id or 0, 140)

    result = await service.reset_current_track_volume(cast(Any, guild))

    assert result.ok is True
    assert TrackVolumeOverrideRepository(database).get(123, track.id or 0) is None
    assert state.volume == 100


@pytest.mark.asyncio
async def test_default_volume_command_path_is_deprecated_without_saving(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    service = AudioPlaybackService(bot, Path("/music"))

    result = await service.set_default_volume(cast(Any, guild), 65)

    assert result.ok is False
    assert GuildSettingsService(GuildSettingsRepository(database)).get_volume(123) == 100


@pytest.mark.asyncio
async def test_hard_stop_clears_session_and_disconnects(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    player = _FakePlayer()
    guild.voice_client = player
    service = AudioPlaybackService(bot, Path("/music"))
    state = bot.player_states.get_or_create(123)
    state.current_track = Track(source="local", source_id="current.mp3")
    state.upcoming.append(Track(source="local", source_id="next.mp3"))
    state.recently_played.append(Track(source="local", source_id="previous.mp3"))
    state.paused = True
    state.loop_current = True

    result = await service.stop(cast(Any, guild))

    assert result.ok is True
    assert result.message == "Playback stopped. Queue cleared. Disconnected."
    assert player.stopped is True
    assert player.disconnected is True
    assert state.current_track is None
    assert state.upcoming == []
    assert state.recently_played == []
    assert state.paused is False
    assert state.loop_current is False
    assert state.suppress_next_track_end is True


@pytest.mark.asyncio
async def test_leave_delegates_to_hard_reset_path(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    player = _FakePlayer()
    guild.voice_client = player
    service = AudioPlaybackService(bot, Path("/music"))
    bot.player_states.get_or_create(123).current_track = Track(
        source="local",
        source_id="current.mp3",
    )

    result = await service.leave(cast(Any, guild))

    assert result.ok is True
    assert player.stopped is True
    assert player.disconnected is True
    assert bot.player_states.get_or_create(123).current_track is None


@pytest.mark.asyncio
async def test_manual_stop_suppresses_next_track_end(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    bot.lavalink_available = True
    guild = _FakeGuild(guild_id=123)
    player = _FakePlayer()
    player.guild = guild
    service = _FakeAudioPlaybackService(bot, Path("/music"))
    state = bot.player_states.get_or_create(123)
    state.current_track = Track(source="local", source_id="current.mp3")
    state.upcoming.append(Track(source="local", source_id="next.mp3", relative_path="next.mp3"))
    state.mark_manual_stop()

    await service.handle_track_end(SimpleNamespace(reason="finished", player=player))

    assert player.played == []
    assert state.queue_length == 1
    assert state.suppress_next_track_end is False


@pytest.mark.asyncio
async def test_natural_track_completion_still_auto_advances(
    database: SQLiteDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "mafic", SimpleNamespace())
    bot = _FakeBot(database)
    bot.lavalink_available = True
    guild = _FakeGuild(guild_id=123)
    player = _FakePlayer()
    player.guild = guild
    guild.voice_client = player
    service = _FakeAudioPlaybackService(bot, Path("/music"))
    state = bot.player_states.get_or_create(123)
    state.current_track = Track(source="local", source_id="current.mp3")
    state.upcoming.append(
        Track(source="local", source_id="next.mp3", relative_path="next.mp3", file_name="next.mp3")
    )

    await service.handle_track_end(SimpleNamespace(reason="finished", player=player))

    assert player.played == [{"identifier": "/music/next.mp3"}]
    assert state.current_track is not None
    assert state.current_track.source_id == "next.mp3"


def test_clear_queue_preserves_current_playback(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    service = AudioPlaybackService(bot, Path("/music"))
    state = bot.player_states.get_or_create(123)
    current = Track(source="local", source_id="current.mp3")
    state.current_track = current
    state.upcoming.extend([
        Track(source="local", source_id="next.mp3"),
        Track(source="local", source_id="third.mp3"),
    ])

    result = service.clear_queue(123)

    assert result.ok is True
    assert state.current_track is current
    assert state.upcoming == []


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
        self.lavalink_available = False


class _FakeGuild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id
        self.voice_client: Any = None


class _FakePlayer:
    def __init__(self) -> None:
        self.volumes: list[int] = []
        self.played: list[object] = []
        self.stopped = False
        self.disconnected = False
        self.guild: _FakeGuild | None = None

    async def play(self, track: object) -> None:
        self.played.append(track)

    async def set_volume(self, volume: int) -> None:
        self.volumes.append(volume)

    async def stop(self) -> None:
        self.stopped = True

    async def disconnect(self) -> None:
        self.disconnected = True


class _FakeAudioPlaybackService(AudioPlaybackService):
    async def _load_local_track(self, *, identifier: str, mafic_module: Any) -> Any:
        return {"identifier": identifier}


def _volume_service(database: SQLiteDatabase) -> VolumeService:
    return VolumeService(
        GuildSettingsRepository(database),
        TrackVolumeOverrideRepository(database),
    )
