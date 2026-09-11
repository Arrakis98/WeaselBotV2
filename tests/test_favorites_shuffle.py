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
    _weights_for_progress,
    favorites_first_shuffle,
)


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    sqlite_database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel-test.db"))
    sqlite_database.initialize()
    return sqlite_database


@pytest.mark.parametrize(
    ("progress", "expected"),
    [
        (
            0.0,
            {"superlike": 0.25, "like": 0.20, "neutral": 0.55, "dislike": 0.0},
        ),
        (
            0.249999,
            {"superlike": 0.25, "like": 0.20, "neutral": 0.55, "dislike": 0.0},
        ),
        (
            0.25,
            {"superlike": 0.15, "like": 0.15, "neutral": 0.65, "dislike": 0.05},
        ),
        (
            0.699999,
            {"superlike": 0.15, "like": 0.15, "neutral": 0.65, "dislike": 0.05},
        ),
        (
            0.70,
            {"superlike": 0.05, "like": 0.05, "neutral": 0.40, "dislike": 0.50},
        ),
        (
            1.0,
            {"superlike": 0.05, "like": 0.05, "neutral": 0.40, "dislike": 0.50},
        ),
    ],
)
def test_weight_table_matches_requested_playlist_zones(
    progress: float,
    expected: dict[str, float],
) -> None:
    assert _weights_for_progress(progress) == expected


def test_start_slot_matches_requested_weights_statistically() -> None:
    superlikes = [_track(index, "superlike") for index in range(1, 81)]
    likes = [_track(index, "like") for index in range(101, 181)]
    neutral = [_track(index, "neutral") for index in range(201, 281)]
    dislikes = [_track(index, "dislike") for index in range(301, 381)]
    ratings = {
        **{track.id: "superlike" for track in superlikes if track.id is not None},
        **{track.id: "like" for track in likes if track.id is not None},
        **{track.id: "dislike" for track in dislikes if track.id is not None},
    }
    occurrences = superlikes + likes + neutral + dislikes

    counts: Counter[str] = Counter()
    trials = 4000
    for seed in range(trials):
        shuffled = favorites_first_shuffle(occurrences, ratings, rng=random.Random(seed))
        counts[_group_for(shuffled[0], ratings)] += 1

    observed = {group: count / trials for group, count in counts.items()}
    assert observed.get("dislike", 0.0) == 0.0
    assert 0.22 <= observed["superlike"] <= 0.28
    assert 0.17 <= observed["like"] <= 0.23
    assert 0.52 <= observed["neutral"] <= 0.58


def test_dislikes_are_held_out_of_first_quarter_and_concentrate_late() -> None:
    superlikes = [_track(index, "superlike") for index in range(1, 31)]
    likes = [_track(index, "like") for index in range(101, 131)]
    neutral = [_track(index, "neutral") for index in range(201, 501)]
    dislikes = [_track(index, "dislike") for index in range(601, 661)]
    ratings = {
        **{track.id: "superlike" for track in superlikes if track.id is not None},
        **{track.id: "like" for track in likes if track.id is not None},
        **{track.id: "dislike" for track in dislikes if track.id is not None},
    }

    shuffled = favorites_first_shuffle(
        superlikes + likes + neutral + dislikes,
        ratings,
        rng=random.Random(2),
    )
    total = len(shuffled)
    start_dislikes = 0
    middle_dislikes = 0
    end_dislikes = 0

    for position, track in enumerate(shuffled):
        progress = 0.0 if total <= 1 else position / (total - 1)
        if _group_for(track, ratings) != "dislike":
            continue
        if progress < 0.25:
            start_dislikes += 1
        elif progress < 0.70:
            middle_dislikes += 1
        else:
            end_dislikes += 1

    assert start_dislikes == 0
    assert end_dislikes > middle_dislikes


def test_favorites_do_not_stack_while_neutral_tracks_remain() -> None:
    favorites = [_track(index, "favorite") for index in range(1, 41)]
    neutral = [_track(index, "neutral") for index in range(101, 201)]
    ratings = {
        track.id: ("superlike" if index % 2 == 0 else "like")
        for index, track in enumerate(favorites)
        if track.id is not None
    }
    shuffled = favorites_first_shuffle(
        favorites + neutral,
        ratings,
        rng=random.Random(31),
    )

    neutral_remaining = len(neutral)
    previous_was_favorite = False
    for track in shuffled:
        group = _group_for(track, ratings)
        is_favorite = group in {"like", "superlike"}
        if previous_was_favorite and is_favorite:
            assert neutral_remaining == 0
        if group == "neutral":
            neutral_remaining -= 1
        previous_was_favorite = is_favorite


def test_superdislike_uses_the_same_late_bucket_as_dislike() -> None:
    neutral = [_track(index, "neutral") for index in range(1, 101)]
    disliked = _track(201, "dislike")
    superdisliked = _track(202, "superdislike")
    ratings = {201: "dislike", 202: "superdislike"}

    shuffled = favorites_first_shuffle(
        neutral + [disliked, superdisliked],
        ratings,
        rng=random.Random(7),
    )
    first_quarter = [
        track
        for index, track in enumerate(shuffled)
        if index / (len(shuffled) - 1) < 0.25
    ]

    assert disliked not in first_quarter
    assert superdisliked not in first_quarter


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
    "ratings",
    [
        {},
        {1: "like", 2: "like"},
        {1: "superlike", 2: "superlike"},
        {1: "like", 2: "superlike"},
        {1: "dislike", 2: "dislike"},
        {1: "superdislike", 2: "superdislike"},
    ],
)
def test_empty_and_single_group_collections(ratings: dict[int, str]) -> None:
    occurrences = [_track(1), _track(2)]

    shuffled = favorites_first_shuffle(occurrences, ratings, rng=random.Random(8))

    assert Counter(map(id, shuffled)) == Counter(map(id, occurrences))
    assert favorites_first_shuffle([], ratings, rng=random.Random(8)) == []


def test_same_seed_is_stable_and_different_seeds_vary() -> None:
    occurrences = [_track(index) for index in range(20)]
    ratings = {1: "like", 2: "superlike", 3: "like", 4: "dislike"}

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
    expected = favorites_first_shuffle(
        [other, favorite],
        ratings,
        rng=random.Random(3),
    )
    shuffled = FavoritesFirstShuffleService(repository).shuffle(
        [other, favorite],
        guild_id=123,
        user_id=42,
        rng=random.Random(3),
    )

    assert ratings == {favorite.id: "like"}
    assert shuffled == expected


def _group_for(track: Track, ratings: dict[int, str]) -> str:
    rating = ratings.get(track.id or 0)
    if rating == "superlike":
        return "superlike"
    if rating == "like":
        return "like"
    if rating in {"dislike", "superdislike"}:
        return "dislike"
    return "neutral"


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
