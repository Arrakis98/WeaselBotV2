from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from weasel_bot_v2.models import Track
from weasel_bot_v2.repositories import RatingRepository


class ShuffleRandom(Protocol):
    def shuffle(self, x: list[Any]) -> None: ...

    def randint(self, a: int, b: int) -> int: ...

    def random(self) -> float: ...


def favorites_first_shuffle(
    occurrences: Sequence[Track],
    ratings_by_track_id: Mapping[int, str],
    *,
    rng: ShuffleRandom = random,
) -> list[Track]:
    """Return a personalized permutation without mutating the input sequence."""
    superlikes: list[Track] = []
    likes: list[Track] = []
    others: list[Track] = []
    for occurrence in occurrences:
        rating = ratings_by_track_id.get(occurrence.id) if occurrence.id is not None else None
        if rating == "superlike":
            superlikes.append(occurrence)
        elif rating == "like":
            likes.append(occurrence)
        else:
            others.append(occurrence)

    _shuffle(rng, superlikes)
    _shuffle(rng, likes)
    _shuffle(rng, others)
    if not superlikes and not likes:
        return others

    shuffled: list[Track] = []
    initial_other_count = rng.randint(0, min(2, len(others)))
    _take_others(shuffled, others, initial_other_count)

    while superlikes or likes:
        shuffled.append(_take_favorite(superlikes, likes, rng))
        if not superlikes and not likes:
            break
        other_count = rng.randint(1, min(3, len(others))) if others else 0
        _take_others(shuffled, others, other_count)

    shuffled.extend(others)
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


def _take_favorite(
    superlikes: list[Track],
    likes: list[Track],
    rng: ShuffleRandom,
) -> Track:
    if superlikes and likes:
        source = superlikes if rng.random() < (2 / 3) else likes
    else:
        source = superlikes or likes
    return source.pop()


def _take_others(destination: list[Track], others: list[Track], count: int) -> None:
    for _ in range(count):
        destination.append(others.pop())


def _shuffle(rng: ShuffleRandom, values: list[Track]) -> None:
    rng.shuffle(values)
