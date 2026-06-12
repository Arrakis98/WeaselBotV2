from __future__ import annotations

from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Rating


class RatingRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def set_rating(self, rating: Rating) -> Rating:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO ratings (guild_id, user_id, track_id, rating)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id, track_id) DO UPDATE SET
                    rating = excluded.rating,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (rating.guild_id, rating.user_id, rating.track_id, rating.rating),
            )
            connection.commit()
        return rating
