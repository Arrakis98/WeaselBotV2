from __future__ import annotations

from sqlite3 import Row

from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Rating, RatingCounts


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

    def get_rating(self, guild_id: int, user_id: int, track_id: int) -> Rating | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT guild_id, user_id, track_id, rating
                FROM ratings
                WHERE guild_id = ? AND user_id = ? AND track_id = ?
                """,
                (guild_id, user_id, track_id),
            ).fetchone()

        return _rating_from_row(row) if row else None

    def counts_for_track(self, guild_id: int, track_id: int) -> RatingCounts:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT rating, COUNT(*) AS rating_count
                FROM ratings
                WHERE guild_id = ? AND track_id = ?
                GROUP BY rating
                """,
                (guild_id, track_id),
            ).fetchall()

        counts = {str(row["rating"]): int(row["rating_count"]) for row in rows}
        return RatingCounts(
            like=counts.get("like", 0),
            superlike=counts.get("superlike", 0),
            dislike=counts.get("dislike", 0),
            superdislike=counts.get("superdislike", 0),
        )


def _rating_from_row(row: Row) -> Rating:
    return Rating(
        guild_id=int(row["guild_id"]),
        user_id=int(row["user_id"]),
        track_id=int(row["track_id"]),
        rating=str(row["rating"]),
    )
