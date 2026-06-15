from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import discord
import pytest

from weasel_bot_v2.cogs.music import MusicCog
from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Rating, Track, UserRecord
from weasel_bot_v2.repositories import RatingRepository, TrackRepository, UserRepository
from weasel_bot_v2.services.application_emojis import ApplicationEmojiRegistry
from weasel_bot_v2.services.now_playing_panel import NowPlayingPanelRegistry
from weasel_bot_v2.services.player_state import PlayerStateStore


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    sqlite_database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel-test.db"))
    sqlite_database.initialize()
    return sqlite_database


@pytest.mark.asyncio
async def test_my_ratings_isolates_current_user_and_guild(database: SQLiteDatabase) -> None:
    current = _track(database, "Pop/Artist/current.mp3", artist="Artist")
    other_user = _track(database, "Pop/Artist/other-user.mp3", artist="Artist")
    other_guild = _track(database, "Pop/Artist/other-guild.mp3", artist="Artist")
    assert current.id is not None and other_user.id is not None and other_guild.id is not None
    ratings = RatingRepository(database)
    ratings.set_rating(Rating(guild_id=123, user_id=42, track_id=current.id, rating="like"))
    ratings.set_rating(Rating(guild_id=123, user_id=999, track_id=other_user.id, rating="like"))
    ratings.set_rating(Rating(guild_id=456, user_id=42, track_id=other_guild.id, rating="like"))
    interaction = _FakeInteraction(guild=_FakeGuild(guild_id=123), user_id=42)

    await _run_slash(MusicCog(cast(Any, _FakeBot(database))), "my_ratings", interaction)

    assert interaction.response_ephemeral == [True]
    assert "Total rated tracks: 1" in interaction.response_messages[0]
    assert "current" in interaction.response_messages[0]
    assert "other-user" not in interaction.response_messages[0]
    assert "other-guild" not in interaction.response_messages[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rating_filter", "expected_title", "expected_count"),
    [
        ("all", "liked", "Total rated tracks: 4"),
        ("like", "liked", "Like: 1"),
        ("superlike", "superliked", "SuperLike: 1"),
        ("dislike", "disliked", "Dislike: 1"),
        ("superdislike", "superdisliked", "SuperDislike: 1"),
    ],
)
async def test_my_ratings_filters_and_counts(
    database: SQLiteDatabase,
    rating_filter: str,
    expected_title: str,
    expected_count: str,
) -> None:
    _seed_four_ratings(database)
    interaction = _FakeInteraction(guild=_FakeGuild(guild_id=123), user_id=42)

    await _run_slash(
        MusicCog(cast(Any, _FakeBot(database))),
        "my_ratings",
        interaction,
        rating_filter,
    )

    message = interaction.response_messages[0]
    assert expected_count in message
    assert expected_title in message
    if rating_filter != "all":
        listed_rows = [line for line in message.splitlines() if line.startswith("- ")]
        assert len(listed_rows) == 1
        assert expected_title in listed_rows[0]


@pytest.mark.asyncio
async def test_my_ratings_uses_deterministic_ordering_and_pagination(
    database: SQLiteDatabase,
) -> None:
    ratings = RatingRepository(database)
    for index in range(12):
        track = _track(database, f"Pop/Artist/{index:02d}.mp3", artist="Artist")
        assert track.id is not None
        ratings.set_rating(Rating(guild_id=123, user_id=42, track_id=track.id, rating="like"))
    interaction = _FakeInteraction(guild=_FakeGuild(guild_id=123), user_id=42)

    await _run_slash(MusicCog(cast(Any, _FakeBot(database))), "my_ratings", interaction, "all", 2)

    message = interaction.response_messages[0]
    assert "Page 2/2" in message
    assert "10" in message
    assert "11" in message
    assert "00" not in message


@pytest.mark.asyncio
async def test_my_ratings_empty_filter_and_invalid_page(database: SQLiteDatabase) -> None:
    liked = _track(database, "Pop/Artist/liked.mp3", artist="Artist")
    assert liked.id is not None
    RatingRepository(database).set_rating(
        Rating(guild_id=123, user_id=42, track_id=liked.id, rating="like")
    )
    empty_filter = _FakeInteraction(guild=_FakeGuild(guild_id=123), user_id=42)
    out_of_range = _FakeInteraction(guild=_FakeGuild(guild_id=123), user_id=42)
    invalid_page = _FakeInteraction(guild=_FakeGuild(guild_id=123), user_id=42)

    cog = MusicCog(cast(Any, _FakeBot(database)))
    await _run_slash(cog, "my_ratings", empty_filter, "dislike")
    await _run_slash(cog, "my_ratings", out_of_range, "all", 99)
    await _run_slash(cog, "my_ratings", invalid_page, "all", 0)

    assert "No dislike ratings" in empty_filter.response_messages[0]
    assert "outside the available range" in out_of_range.response_messages[0]
    assert invalid_page.response_messages == ["Page must be a positive integer."]


@pytest.mark.asyncio
async def test_my_ratings_empty_user_and_safe_output(database: SQLiteDatabase) -> None:
    interaction = _FakeInteraction(guild=_FakeGuild(guild_id=123), user_id=42)

    await _run_slash(MusicCog(cast(Any, _FakeBot(database))), "my_ratings", interaction)

    message = interaction.response_messages[0]
    assert "You have not rated any tracks" in message
    assert "/music" not in message
    assert "Pop/Artist" not in message


@pytest.mark.asyncio
async def test_my_ratings_uses_application_emojis_and_unicode_fallbacks(
    database: SQLiteDatabase,
) -> None:
    liked = _track(database, "Pop/Artist/liked.mp3", artist="Artist")
    assert liked.id is not None
    RatingRepository(database).set_rating(
        Rating(guild_id=123, user_id=42, track_id=liked.id, rating="like")
    )
    bot = _FakeBot(database)
    bot.application_emoji_registry = ApplicationEmojiRegistry(
        {"wg_like": discord.PartialEmoji(name="wg_like", id=321)}
    )
    with_custom = _FakeInteraction(guild=_FakeGuild(guild_id=123), user_id=42)
    fallback = _FakeInteraction(guild=_FakeGuild(guild_id=123), user_id=42)

    await _run_slash(MusicCog(cast(Any, bot)), "my_ratings", with_custom)
    await _run_slash(MusicCog(cast(Any, _FakeBot(database))), "my_ratings", fallback)

    assert "<:wg_like:321> liked" in with_custom.response_messages[0]
    assert "❤️ liked" in fallback.response_messages[0]


async def _run_slash(
    cog: MusicCog,
    command_name: str,
    interaction: _FakeInteraction,
    *args: object,
) -> None:
    command = next(
        command for command in MusicCog.__cog_app_commands__ if command.name == command_name
    )
    await cast(Any, command).callback(cog, interaction, *args)


def _seed_four_ratings(database: SQLiteDatabase) -> None:
    ratings = RatingRepository(database)
    for rating in ("like", "superlike", "dislike", "superdislike"):
        title = f"{rating}d" if rating != "like" else "liked"
        track = _track(database, f"Pop/Artist/{title}.mp3", artist="Artist")
        assert track.id is not None
        ratings.set_rating(Rating(guild_id=123, user_id=42, track_id=track.id, rating=rating))


def _track(database: SQLiteDatabase, relative_path: str, *, artist: str) -> Track:
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Listener"))
    UserRepository(database).upsert(UserRecord(user_id=999, display_name="Other"))
    return TrackRepository(database).upsert_local(
        Track(
            source="local",
            source_id=relative_path,
            relative_path=relative_path,
            file_name=Path(relative_path).name,
            display_title=Path(relative_path).stem,
            title=Path(relative_path).stem,
            artist=artist,
            artist_guess=artist,
            category_guess="Pop",
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
        self.application_emoji_registry = ApplicationEmojiRegistry.empty()


class _FakeGuild:
    def __init__(self, *, guild_id: int) -> None:
        self.id = guild_id
        self.voice_client = None


class _FakeInteraction:
    def __init__(self, *, guild: _FakeGuild, user_id: int) -> None:
        self.guild = guild
        self.user = SimpleNamespace(id=user_id, display_name="Listener")
        self.channel = None
        self.response = _FakeResponse(self)
        self.response_messages: list[str] = []
        self.response_ephemeral: list[bool] = []


class _FakeResponse:
    def __init__(self, interaction: _FakeInteraction) -> None:
        self.interaction = interaction

    async def send_message(
        self,
        message: str,
        *,
        ephemeral: bool = False,
        view: object | None = None,
    ) -> None:
        self.interaction.response_messages.append(message)
        self.interaction.response_ephemeral.append(ephemeral)
