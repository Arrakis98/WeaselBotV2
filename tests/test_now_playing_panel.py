from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import discord
import pytest

from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Rating, Track, UserRecord
from weasel_bot_v2.repositories import RatingRepository, TrackRepository, UserRepository
from weasel_bot_v2.services.now_playing_panel import (
    NowPlayingPanelRecord,
    NowPlayingPanelRegistry,
    NowPlayingPanelService,
)
from weasel_bot_v2.services.player_state import PlayerStateStore


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    sqlite_database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel-test.db"))
    sqlite_database.initialize()
    return sqlite_database


def test_registry_keeps_one_panel_record_per_guild() -> None:
    registry = NowPlayingPanelRegistry()
    first = NowPlayingPanelRecord(guild_id=123, channel_id=10, message_id=100)
    second = NowPlayingPanelRecord(guild_id=123, channel_id=11, message_id=101)

    registry.set(first)
    registry.set(second)

    assert registry.get(123) == second


def test_registry_reuses_per_guild_lock() -> None:
    registry = NowPlayingPanelRegistry()

    assert registry.lock_for(123) is registry.lock_for(123)
    assert registry.lock_for(123) is not registry.lock_for(456)


def test_snapshot_reflects_queue_volume_loop_and_ratings(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    current = _indexed_track(database, "Rock/Artist/current.mp3")
    next_track = _indexed_track(database, "Rock/Artist/next.mp3")
    previous = _indexed_track(database, "Rock/Artist/previous.mp3")
    state = bot.player_states.get_or_create(123)
    state.current_track = current
    state.upcoming.append(next_track)
    state.recently_played.append(previous)
    state.paused = True
    state.volume = 75
    state.loop_current = True
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Tester"))
    assert current.id is not None
    RatingRepository(database).set_rating(
        Rating(guild_id=123, user_id=42, track_id=current.id, rating="superlike")
    )

    snapshot = NowPlayingPanelService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    assert snapshot.title == "current"
    assert snapshot.artist == "Artist"
    assert snapshot.category == "Rock"
    assert snapshot.status == "Paused"
    assert snapshot.volume == 75
    assert snapshot.loop_enabled is True
    assert snapshot.queue_length == 1
    assert snapshot.next_title == "next"
    assert snapshot.previous_available is True
    assert snapshot.rating_counts.superlike == 1


@pytest.mark.asyncio
async def test_refresh_creates_then_edits_authoritative_panel(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    bot.channels[10] = channel
    bot.player_states.get_or_create(123).current_track = _indexed_track(database, "one.mp3")
    service = NowPlayingPanelService(bot)

    first = await service.refresh(guild=guild, channel=channel, reason="test")  # type: ignore[arg-type]
    second = await service.refresh(guild=guild, channel=channel, reason="test")  # type: ignore[arg-type]

    assert first is not None
    assert second is not None
    assert first.message_id == second.message_id
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0].edit_count == 1


@pytest.mark.asyncio
async def test_deleted_panel_message_recreates_reference(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    channel.deleted_message_ids.add(100)
    bot.channels[10] = channel
    bot.player_states.get_or_create(123).current_track = _indexed_track(database, "one.mp3")
    bot.now_playing_panels.set(NowPlayingPanelRecord(123, 10, 100))

    record = await NowPlayingPanelService(bot).refresh(
        guild=guild,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
        reason="deleted",
    )

    assert record is not None
    assert record.message_id != 100
    assert bot.now_playing_panels.get(123) == record
    assert len(channel.sent_messages) == 1


@pytest.mark.asyncio
async def test_refresh_does_not_create_duplicate_panels(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    bot.player_states.get_or_create(123).current_track = _indexed_track(database, "one.mp3")
    service = NowPlayingPanelService(bot)

    await service.refresh(guild=guild, channel=channel, reason="first")  # type: ignore[arg-type]
    await service.refresh(guild=guild, channel=channel, reason="second")  # type: ignore[arg-type]
    await service.refresh(guild=guild, channel=channel, reason="third")  # type: ignore[arg-type]

    assert len(channel.sent_messages) == 1
    assert bot.now_playing_panels.get(123) is not None


@pytest.mark.asyncio
async def test_refresh_uses_newest_state(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    state = bot.player_states.get_or_create(123)
    state.current_track = _indexed_track(database, "first.mp3")
    service = NowPlayingPanelService(bot)
    await service.refresh(guild=guild, channel=channel, reason="first")  # type: ignore[arg-type]

    state.current_track = _indexed_track(database, "second.mp3")
    state.volume = 55
    await service.refresh(guild=guild, channel=channel, reason="second")  # type: ignore[arg-type]

    embed = channel.sent_messages[0].last_embed
    assert embed is not None
    assert "second" in (embed.description or "")
    assert _field_value(embed, "Volume") == "55%"


def _indexed_track(database: SQLiteDatabase, relative_path: str) -> Track:
    return TrackRepository(database).upsert(
        Track(
            source="local",
            source_id=relative_path,
            relative_path=relative_path,
            file_name=relative_path.rsplit("/", maxsplit=1)[-1],
            display_title=relative_path.rsplit("/", maxsplit=1)[-1].removesuffix(".mp3"),
            title=relative_path.rsplit("/", maxsplit=1)[-1].removesuffix(".mp3"),
            artist_guess="Artist" if "/" in relative_path else None,
            category_guess="Rock" if relative_path.count("/") >= 2 else None,
        )
    )


def _field_value(embed: discord.Embed, name: str) -> str | None:
    for field in embed.fields:
        if field.name == name:
            return str(field.value)
    return None


class _FakeBot:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        self.player_states = PlayerStateStore()
        self.now_playing_panels = NowPlayingPanelRegistry()
        self.lavalink_available = True
        self.settings = SimpleNamespace(bot=SimpleNamespace(music_library=Path("/music")))
        self.channels: dict[int, _FakeChannel] = {}

    def get_channel(self, channel_id: int) -> _FakeChannel | None:
        return self.channels.get(channel_id)


class _FakeGuild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id
        self.voice_client: Any = object()


class _FakeChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.sent_messages: list[_FakeMessage] = []
        self.deleted_message_ids: set[int] = set()
        self.next_message_id = 100

    async def send(self, *, embed: discord.Embed, view: discord.ui.View) -> _FakeMessage:
        while self.next_message_id in self.deleted_message_ids:
            self.next_message_id += 1
        message = _FakeMessage(
            message_id=self.next_message_id,
            channel=self,
            embed=embed,
            view=view,
        )
        self.next_message_id += 1
        self.sent_messages.append(message)
        return message

    async def fetch_message(self, message_id: int) -> _FakeMessage:
        if message_id in self.deleted_message_ids:
            raise discord.NotFound(response=_not_found_response(), message="deleted")
        for message in self.sent_messages:
            if message.id == message_id:
                return message
        raise discord.NotFound(response=_not_found_response(), message="missing")


class _FakeMessage:
    def __init__(
        self,
        *,
        message_id: int,
        channel: _FakeChannel,
        embed: discord.Embed,
        view: discord.ui.View,
    ) -> None:
        self.id = message_id
        self.channel = channel
        self.last_embed = embed
        self.last_view = view
        self.edit_count = 0

    async def edit(self, *, embed: discord.Embed | None = None, view: discord.ui.View) -> None:
        self.edit_count += 1
        self.last_embed = embed
        self.last_view = view


def _not_found_response() -> Any:
    return SimpleNamespace(status=404, reason="Not Found")
