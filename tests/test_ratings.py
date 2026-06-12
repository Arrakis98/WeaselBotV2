from __future__ import annotations

from pathlib import Path

import pytest

from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Rating, Track, UserRecord
from weasel_bot_v2.repositories import RatingRepository, TrackRepository, UserRepository
from weasel_bot_v2.services.player_state import GuildPlayerState
from weasel_bot_v2.services.ratings import RatingService


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    sqlite_database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel-test.db"))
    sqlite_database.initialize()
    return sqlite_database


def test_create_rating(database: SQLiteDatabase) -> None:
    ratings = RatingRepository(database)
    track = _create_track(database)
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Listener"))
    assert track.id is not None

    saved = ratings.set_rating(
        Rating(guild_id=123, user_id=42, track_id=track.id, rating="like")
    )

    assert saved.rating == "like"
    assert ratings.get_rating(123, 42, track.id) == saved


def test_replace_rating_keeps_one_rating_per_user_track(database: SQLiteDatabase) -> None:
    ratings = RatingRepository(database)
    track = _create_track(database)
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Listener"))
    assert track.id is not None

    ratings.set_rating(Rating(guild_id=123, user_id=42, track_id=track.id, rating="like"))
    ratings.set_rating(
        Rating(guild_id=123, user_id=42, track_id=track.id, rating="superlike")
    )

    assert ratings.get_rating(123, 42, track.id) == Rating(
        guild_id=123,
        user_id=42,
        track_id=track.id,
        rating="superlike",
    )
    counts = ratings.counts_for_track(123, track.id)
    assert counts.like == 0
    assert counts.superlike == 1


def test_multiple_users_can_rate_same_track(database: SQLiteDatabase) -> None:
    ratings = RatingRepository(database)
    users = UserRepository(database)
    track = _create_track(database)
    assert track.id is not None
    users.upsert(UserRecord(user_id=42, display_name="One"))
    users.upsert(UserRecord(user_id=43, display_name="Two"))
    users.upsert(UserRecord(user_id=44, display_name="Three"))

    ratings.set_rating(Rating(guild_id=123, user_id=42, track_id=track.id, rating="like"))
    ratings.set_rating(
        Rating(guild_id=123, user_id=43, track_id=track.id, rating="superlike")
    )
    ratings.set_rating(
        Rating(guild_id=123, user_id=44, track_id=track.id, rating="dislike")
    )

    counts = ratings.counts_for_track(123, track.id)
    assert counts.like == 1
    assert counts.superlike == 1
    assert counts.dislike == 1
    assert counts.superdislike == 0


def test_rating_service_rates_current_track(database: SQLiteDatabase) -> None:
    service = RatingService(RatingRepository(database), UserRepository(database))
    track = _create_track(database)
    state = GuildPlayerState(guild_id=123, current_track=track)
    assert track.id is not None

    result = service.rate_current_track(
        state=state,
        user_id=42,
        display_name="Listener",
        rating_value="superdislike",
    )

    assert result.ok is True
    assert result.rating == Rating(
        guild_id=123,
        user_id=42,
        track_id=track.id,
        rating="superdislike",
    )
    assert UserRepository(database).get(42) == UserRecord(
        user_id=42,
        display_name="Listener",
    )


def test_rating_service_reports_no_current_track(database: SQLiteDatabase) -> None:
    service = RatingService(RatingRepository(database), UserRepository(database))

    result = service.rate_current_track(
        state=None,
        user_id=42,
        display_name="Listener",
        rating_value="like",
    )

    assert result.ok is False
    assert result.message == "Nothing is playing."


def test_rating_service_rejects_unindexed_current_track(database: SQLiteDatabase) -> None:
    service = RatingService(RatingRepository(database), UserRepository(database))
    state = GuildPlayerState(
        guild_id=123,
        current_track=Track(
            source="local",
            source_id="song.mp3",
            relative_path="song.mp3",
        ),
    )

    result = service.rate_current_track(
        state=state,
        user_id=42,
        display_name="Listener",
        rating_value="like",
    )

    assert result.ok is False
    assert result.message == "The current track is not linked to an indexed local track."


def _create_track(database: SQLiteDatabase) -> Track:
    return TrackRepository(database).upsert_local(
        Track(
            source="local",
            source_id="Artist/song.mp3",
            relative_path="Artist/song.mp3",
            file_name="song.mp3",
            display_title="Song",
            artist_guess="Artist",
            extension=".mp3",
        )
    )
