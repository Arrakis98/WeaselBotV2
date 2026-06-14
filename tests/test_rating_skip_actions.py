from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from weasel_bot_v2.cogs.music import MusicCog
from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Rating, Track, UserRecord
from weasel_bot_v2.repositories import RatingRepository, TrackRepository, UserRepository
from weasel_bot_v2.services.now_playing_panel import NowPlayingPanelRegistry, NowPlayingPanelService
from weasel_bot_v2.services.player_state import PlayerStateStore


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    sqlite_database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel-test.db"))
    sqlite_database.initialize()
    return sqlite_database


@pytest.mark.asyncio
async def test_slash_dislike_replaces_rating_then_skips_current_track(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    cog = MusicCog(cast(Any, bot))
    player = _FakePlayer()
    guild = _FakeGuild(guild_id=123, voice_client=player)
    interaction = _FakeInteraction(guild=guild)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Listener"))
    RatingRepository(database).set_rating(
        Rating(guild_id=123, user_id=42, track_id=current.id, rating="like")
    )

    await _run_slash(cog, "dislike", interaction)

    saved = RatingRepository(database).get_rating(123, 42, current.id)
    assert saved == Rating(guild_id=123, user_id=42, track_id=current.id, rating="dislike")
    counts = RatingRepository(database).counts_for_track(123, current.id)
    assert counts.like == 0
    assert counts.dislike == 1
    assert bot.player_states.get_or_create(123).current_track is None
    assert player.stop_count == 1
    assert interaction.response_messages == [
        "Saved Dislike for current. Skipped. The queue is empty."
    ]


@pytest.mark.asyncio
async def test_slash_superdislike_keeps_saved_rating_when_skip_cannot_complete(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    cog = MusicCog(cast(Any, bot))
    guild = _FakeGuild(guild_id=123, voice_client=None)
    interaction = _FakeInteraction(guild=guild)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current

    await _run_slash(cog, "superdislike", interaction)

    assert RatingRepository(database).get_rating(123, 42, current.id) == Rating(
        guild_id=123,
        user_id=42,
        track_id=current.id,
        rating="superdislike",
    )
    assert bot.player_states.get_or_create(123).current_track == current
    assert interaction.response_messages == [
        "Saved SuperDislike for current. The bot is not connected to a player."
    ]


@pytest.mark.asyncio
async def test_slash_superdislike_saves_rating_then_invokes_one_skip(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    cog = MusicCog(cast(Any, bot))
    player = _FakePlayer()
    guild = _FakeGuild(guild_id=123, voice_client=player)
    interaction = _FakeInteraction(guild=guild)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current

    await _run_slash(cog, "superdislike", interaction)

    assert RatingRepository(database).get_rating(123, 42, current.id) == Rating(
        guild_id=123,
        user_id=42,
        track_id=current.id,
        rating="superdislike",
    )
    assert bot.player_states.get_or_create(123).current_track is None
    assert player.stop_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("rating_value", ["dislike", "superdislike"])
async def test_panel_negative_rating_buttons_save_rating_then_invoke_one_skip(
    database: SQLiteDatabase,
    rating_value: str,
) -> None:
    bot = _FakeBot(database)
    player = _FakePlayer()
    guild = _FakeGuild(guild_id=123, voice_client=player)
    interaction = _FakeInteraction(guild=guild)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current

    await NowPlayingPanelService(bot).run_rating_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        rating_value,
    )

    assert RatingRepository(database).get_rating(123, 42, current.id) == Rating(
        guild_id=123,
        user_id=42,
        track_id=current.id,
        rating=rating_value,
    )
    assert bot.player_states.get_or_create(123).current_track is None
    assert player.stop_count == 1
    assert len(interaction.followup_messages) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("surface", "rating_value"),
    [
        ("slash", "like"),
        ("slash", "superlike"),
        ("button", "like"),
        ("button", "superlike"),
    ],
)
async def test_like_and_superlike_do_not_skip_on_commands_or_buttons(
    database: SQLiteDatabase,
    surface: str,
    rating_value: str,
) -> None:
    bot = _FakeBot(database)
    player = _FakePlayer()
    guild = _FakeGuild(guild_id=123, voice_client=player)
    interaction = _FakeInteraction(guild=guild)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current

    if surface == "slash":
        await _run_slash(cast(Any, MusicCog(cast(Any, bot))), rating_value, interaction)
    else:
        await NowPlayingPanelService(bot).run_rating_action(  # type: ignore[arg-type]
            interaction,  # type: ignore[arg-type]
            rating_value,
        )

    assert RatingRepository(database).get_rating(123, 42, current.id) == Rating(
        guild_id=123,
        user_id=42,
        track_id=current.id,
        rating=rating_value,
    )
    assert bot.player_states.get_or_create(123).current_track == current
    assert player.stop_count == 0


async def _run_slash(cog: MusicCog, command_name: str, interaction: _FakeInteraction) -> None:
    command = next(
        command for command in MusicCog.__cog_app_commands__ if command.name == command_name
    )
    await cast(Any, command).callback(cog, interaction)


def _indexed_track(database: SQLiteDatabase, relative_path: str) -> Track:
    return TrackRepository(database).upsert(
        Track(
            source="local",
            source_id=relative_path,
            relative_path=relative_path,
            file_name=relative_path.rsplit("/", maxsplit=1)[-1],
            display_title=relative_path.rsplit("/", maxsplit=1)[-1].removesuffix(".mp3"),
            title=relative_path.rsplit("/", maxsplit=1)[-1].removesuffix(".mp3"),
            artist_guess="Artist",
            extension=".mp3",
        )
    )


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
    def __init__(self, *, guild_id: int, voice_client: object | None) -> None:
        self.id = guild_id
        self.voice_client = voice_client


class _FakePlayer:
    def __init__(self) -> None:
        self.stop_count = 0

    async def stop(self) -> None:
        self.stop_count += 1


class _FakeInteraction:
    def __init__(self, *, guild: _FakeGuild) -> None:
        self.guild = guild
        self.user = SimpleNamespace(id=42, display_name="Listener")
        self.channel = _FakeChannel(channel_id=10)
        self.response = _FakeResponse(self)
        self.followup = _FakeFollowup(self)
        self.response_messages: list[str] = []
        self.followup_messages: list[str] = []


class _FakeResponse:
    def __init__(self, interaction: _FakeInteraction) -> None:
        self.interaction = interaction
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def defer(self, *, ephemeral: bool = False) -> None:
        self._done = True

    async def send_message(self, message: str, *, ephemeral: bool = False) -> None:
        self._done = True
        self.interaction.response_messages.append(message)


class _FakeFollowup:
    def __init__(self, interaction: _FakeInteraction) -> None:
        self.interaction = interaction

    async def send(self, message: str, *, ephemeral: bool = False) -> None:
        self.interaction.followup_messages.append(message)


class _FakeChannel:
    def __init__(self, *, channel_id: int) -> None:
        self.id = channel_id
        self.sent_messages: list[_FakeMessage] = []
        self.next_message_id = 100

    async def send(self, **kwargs: Any) -> _FakeMessage:
        message = _FakeMessage(message_id=self.next_message_id)
        self.next_message_id += 1
        self.sent_messages.append(message)
        return message


class _FakeMessage:
    def __init__(self, *, message_id: int) -> None:
        self.id = message_id
