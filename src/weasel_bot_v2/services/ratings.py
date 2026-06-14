from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from weasel_bot_v2.models import Rating, RatingCounts, UserRecord
from weasel_bot_v2.repositories import RatingRepository, UserRepository
from weasel_bot_v2.services.player_state import GuildPlayerState

RatingValue = Literal["like", "superlike", "dislike", "superdislike"]

VALID_RATINGS: frozenset[str] = frozenset(
    {"like", "superlike", "dislike", "superdislike"}
)
RATINGS_THAT_SKIP: frozenset[str] = frozenset({"dislike", "superdislike"})
RATING_LABELS: dict[str, str] = {
    "like": "Like",
    "superlike": "SuperLike",
    "dislike": "Dislike",
    "superdislike": "SuperDislike",
}


@dataclass(frozen=True)
class RatingResult:
    ok: bool
    message: str
    rating: Rating | None = None


class RatingService:
    def __init__(self, ratings: RatingRepository, users: UserRepository) -> None:
        self.ratings = ratings
        self.users = users

    def rate_current_track(
        self,
        *,
        state: GuildPlayerState | None,
        user_id: int,
        display_name: str | None,
        rating_value: str,
    ) -> RatingResult:
        if rating_value not in VALID_RATINGS:
            return RatingResult(ok=False, message="Unsupported rating value.")
        if state is None or state.current_track is None:
            return RatingResult(ok=False, message="Nothing is playing.")
        if state.current_track.id is None:
            return RatingResult(
                ok=False,
                message="The current track is not linked to an indexed local track.",
            )

        self.users.upsert(UserRecord(user_id=user_id, display_name=display_name))
        rating = self.ratings.set_rating(
            Rating(
                guild_id=state.guild_id,
                user_id=user_id,
                track_id=state.current_track.id,
                rating=rating_value,
            )
        )
        label = RATING_LABELS[rating_value]
        title = (
            state.current_track.display_title
            or state.current_track.file_name
            or state.current_track.relative_path
            or "current track"
        )
        return RatingResult(
            ok=True,
            message=f"Saved {label} for {title}.",
            rating=rating,
        )

    def get_current_rating(
        self,
        *,
        state: GuildPlayerState | None,
        user_id: int,
    ) -> RatingResult:
        if state is None or state.current_track is None:
            return RatingResult(ok=False, message="Nothing is playing.")
        if state.current_track.id is None:
            return RatingResult(
                ok=False,
                message="The current track is not linked to an indexed local track.",
            )

        rating = self.ratings.get_rating(state.guild_id, user_id, state.current_track.id)
        if rating is None:
            return RatingResult(ok=True, message="You have not rated the current track.")

        label = RATING_LABELS.get(rating.rating, rating.rating)
        return RatingResult(ok=True, message=f"Your rating for the current track: {label}.")

    def counts_for_current_track(self, state: GuildPlayerState | None) -> RatingCounts:
        if state is None or state.current_track is None or state.current_track.id is None:
            return RatingCounts()
        return self.ratings.counts_for_track(state.guild_id, state.current_track.id)
