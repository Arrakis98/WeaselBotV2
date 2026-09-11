from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from weasel_bot_v2.models import Track
from weasel_bot_v2.repositories import RatingRepository


FAVORITE_GROUPS = frozenset({"superlike", "like"})
NEGATIVE_RATINGS = frozenset({"dislike", "superdislike"})


class ShuffleRandom(Protocol):
    def shuffle(self, x: list[Any]) -> None: ...

    def random(self) -> float: ...


def favorites_first_shuffle(
    occurrences: Sequence[Track],
    ratings_by_track_id: Mapping[int, str],
    *,
    rng: ShuffleRandom = random,
) -> list[Track]:
    """Return a rating-weighted permutation without mutating the input sequence."""
    buckets: dict[str, list[Track]] = {
        "superlike": [],
        "like": [],
        "neutral": [],
        "dislike": [],
    }
    for occurrence in occurrences:
        rating = ratings_by_track_id.get(occurrence.id) if occurrence.id is not None else None
        if rating == "superlike":
            buckets["superlike"].append(occurrence)
        elif rating == "like":
            buckets["like"].append(occurrence)
        elif rating in NEGATIVE_RATINGS:
            buckets["dislike"].append(occurrence)
        else:
            buckets["neutral"].append(occurrence)

    for values in buckets.values():
        _shuffle(rng, values)

    shuffled: list[Track] = []
    total = len(occurrences)
    previous_group: str | None = None

    for position in range(total):
        if previous_group in FAVORITE_GROUPS and buckets["neutral"]:
            group = "neutral"
        else:
            progress = 0.0 if total <= 1 else position / (total - 1)
            group = _choose_group(buckets, _weights_for_progress(progress), rng)

        shuffled.append(buckets[group].pop())
        previous_group = group

    return shuffled


class FavoritesFirstShuffleService:
    def __init__(self, ratings: RatingRepository) -> None:
        self.ratings = ratings

    def shuffle(
        self,
        occurrences: Sequence[Track],
        *,
        guild_id: int,
        user_id: int,
        rng: ShuffleRandom = random,
    ) -> list[Track]:
        track_ids = [track.id for track in occurrences if track.id is not None]
        ratings = self.ratings.ratings_for_tracks(guild_id, user_id, track_ids)
        return favorites_first_shuffle(occurrences, ratings, rng=rng)


def _weights_for_progress(progress: float) -> dict[str, float]:
    if progress < 0.25:
        return {
            "superlike": 0.25,
            "like": 0.20,
            "neutral": 0.55,
            "dislike": 0.0,
        }
    if progress < 0.70:
        return {
            "superlike": 0.15,
            "like": 0.15,
            "neutral": 0.65,
            "dislike": 0.05,
        }
    return {
        "superlike": 0.05,
        "like": 0.05,
        "neutral": 0.40,
        "dislike": 0.50,
    }


def _choose_group(
    buckets: Mapping[str, list[Track]],
    weights: Mapping[str, float],
    rng: ShuffleRandom,
) -> str:
    available = [group for group, values in buckets.items() if values]
    if not available:
        raise ValueError("cannot choose a shuffle group from empty buckets")

    total_weight = sum(weights.get(group, 0.0) for group in available)
    if total_weight <= 0:
        index = min(int(rng.random() * len(available)), len(available) - 1)
        return available[index]

    threshold = rng.random() * total_weight
    cumulative = 0.0
    for group in available:
        cumulative += weights.get(group, 0.0)
        if threshold < cumulative:
            return group

    return available[-1]


def _shuffle(rng: ShuffleRandom, values: list[Track]) -> None:
    rng.shuffle(values)
