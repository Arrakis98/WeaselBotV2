from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

import pytest

from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Rating, Track, UserRecord
from weasel_bot_v2.repositories import RatingRepository, TrackRepository, UserRepository
from weasel_bot_v2.services.favorites_shuffle import (
    FavoritesFirstShuffleService,
    favorites_first_shuffle,
)


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    sqlite_database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel-test.db"))
    sqlite_database.initialize()
    return sqlite_database


def test_first_favorite_is_in_first_three_and_gaps_vary_within_bounds() -> None:
    favorites = [_track(index, "like") for index in range(1, 11)]
    others = [_track(index) for index in range(100, 140)]
    ratings = {track.id: "like" for track in favorites if track.id is not None}

    shuffled = favorites_first_shuffle(favorites + others, ratings, rng=random.Random(19))
    favorite_positions = [index for index, track in enumerate(shuffled) if track.id in ratings]
    gaps = [
        right - left - 1
        for left, right in zip(favorite_positions, favorite_positions[1:], strict=False)
    ]

    assert favorite_positions[0] <= 2
    assert all(1 <= gap <= 3 for gap in gaps)
    assert len(set(gaps)) > 1


def test_superlikes_receive_two_thirds_of_early_favorite_slots_statistically() -> None:
    superlikes = [_track(index) for index in range(1, 21)]
    likes = [_track(index) for index in range(101, 121)]
    ratings = {
        **{track.id: "superlike" for track in superlikes if track.id is not None},
        **{track.id: "like" for track in likes if track.id is not None},
    }
    first_superlike_count = 0
    trials = 900
    for seed in range(trials):
        shuffled = favorites_first_shuffle(
            superlikes + likes,
            ratings,
            rng=random.Random(seed),
        )
        if ratings[shuffled[0].id or 0] == "superlike":
            first_superlike_count += 1

    observed = first_superlike_count / trials
    assert 0.62 <= observed <= 0.71


def test_shuffle_preserves_occurrences_and_does_not_mutate_input() -> None:
    duplicate = _track(1)
    occurrences = [duplicate, _track(2), duplicate, _track(None)]
    before = list(occurrences)

    shuffled = favorites_first_shuffle(
        occurrences,
        {1: "superlike", 2: "dislike"},
        rng=random.Random(4),
    )

    assert occurrences == before
    assert Counter(map(id, shuffled)) == Counter(map(id, occurrences))
    assert len(shuffled) == len(occurrences)


@pytest.mark.parametrize(
    ("ratings", "expected_favorite_count"),
    [
        ({}, 0),
        ({1: "like", 2: "like"}, 2),
        ({1: "superlike", 2: "superlike"}, 2),
        ({1: "like", 2: "superlike"}, 2),
    ],
)
def test_empty_and_single_group_collections(
    ratings: dict[int, str],
    expected_favorite_count: int,
) -> None:
    occurrences = [_track(1), _track(2)]

    shuffled = favorites_first_shuffle(occurrences, ratings, rng=random.Random(8))

    assert len(shuffled) == 2
    assert sum(ratings.get(track.id or 0) in {"like", "superlike"} for track in shuffled) == (
        expected_favorite_count
    )
    assert favorites_first_shuffle([], ratings, rng=random.Random(8)) == []


def test_same_seed_is_stable_and_different_seeds_vary() -> None:
    occurrences = [_track(index) for index in range(20)]
    ratings = {1: "like", 2: "superlike", 3: "like"}

    first = favorites_first_shuffle(occurrences, ratings, rng=random.Random(77))
    repeated = favorites_first_shuffle(occurrences, ratings, rng=random.Random(77))
    variants = {
        tuple(
            track.id
            for track in favorites_first_shuffle(
                occurrences,
                ratings,
                rng=random.Random(seed),
            )
        )
        for seed in range(5)
    }

    assert first == repeated
    assert len(variants) > 1


def test_more_other_tracks_do_not_dilute_first_favorite_position() -> None:
    favorite = _track(1)
    ratings = {1: "like"}
    small = [favorite, *(_track(index) for index in range(10, 20))]
    large = [favorite, *(_track(index) for index in range(10, 1010))]

    for seed in range(100):
        small_result = favorites_first_shuffle(small, ratings, rng=random.Random(seed))
        large_result = favorites_first_shuffle(large, ratings, rng=random.Random(seed))
        assert small_result.index(favorite) <= 2
        assert large_result.index(favorite) <= 2


def test_service_loads_ratings_in_one_batch_and_isolates_user_and_guild(
    database: SQLiteDatabase,
) -> None:
    favorite = _stored_track(database, 1)
    other = _stored_track(database, 2)
    users = UserRepository(database)
    users.upsert(UserRecord(user_id=42, display_name="Listener"))
    users.upsert(UserRecord(user_id=99, display_name="Other"))
    repository = RatingRepository(database)
    assert favorite.id is not None
    repository.set_rating(Rating(guild_id=123, user_id=42, track_id=favorite.id, rating="like"))
    repository.set_rating(
        Rating(guild_id=999, user_id=42, track_id=other.id or 0, rating="superlike")
    )
    repository.set_rating(
        Rating(guild_id=123, user_id=99, track_id=other.id or 0, rating="superlike")
    )

    ratings = repository.ratings_for_tracks(123, 42, [favorite.id, other.id or 0, favorite.id])
    shuffled = FavoritesFirstShuffleService(repository).shuffle(
        [other, favorite],
        guild_id=123,
        user_id=42,
        rng=random.Random(3),
    )

    assert ratings == {favorite.id: "like"}
    assert shuffled.index(favorite) <= 1


def _track(track_id: int | None, label: str = "other") -> Track:
    return Track(
        id=track_id,
        source="local",
        source_id=f"{label}-{track_id}.mp3",
        relative_path=f"{label}-{track_id}.mp3",
        file_name=f"{label}-{track_id}.mp3",
        display_title=f"{label}-{track_id}",
        extension=".mp3",
    )


def _stored_track(database: SQLiteDatabase, track_id: int) -> Track:
    return TrackRepository(database).upsert(
        Track(
            source="local",
            source_id=f"track-{track_id}.mp3",
            relative_path=f"track-{track_id}.mp3",
            file_name=f"track-{track_id}.mp3",
            display_title=f"track-{track_id}",
            extension=".mp3",
        )
    )
