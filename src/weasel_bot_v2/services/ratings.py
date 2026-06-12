from __future__ import annotations

from weasel_bot_v2.models import Rating
from weasel_bot_v2.repositories import RatingRepository


class RatingService:
    def __init__(self, repository: RatingRepository) -> None:
        self.repository = repository

    def set_rating(self, rating: Rating) -> Rating:
        return self.repository.set_rating(rating)
