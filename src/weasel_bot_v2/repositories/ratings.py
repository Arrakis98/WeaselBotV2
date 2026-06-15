from __future__ import annotations

from sqlite3 import Row

from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Rating, RatingCounts, UserTrackRating
from weasel_bot_v2.repositories.tracks import _track_from_row


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

    def track_ids_for_rating(self, guild_id: int, rating: str) -> list[int]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT track_id
                FROM ratings
                WHERE guild_id = ? AND rating = ?
                ORDER BY track_id
                """,
                (guild_id, rating),
            ).fetchall()
        return [int(row["track_id"]) for row in rows]

    def counts_for_user(self, guild_id: int, user_id: int) -> RatingCounts:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT rating, COUNT(*) AS rating_count
                FROM ratings
                WHERE guild_id = ? AND user_id = ?
                GROUP BY rating
                """,
                (guild_id, user_id),
            ).fetchall()
        counts = {str(row["rating"]): int(row["rating_count"]) for row in rows}
        return RatingCounts(
            like=counts.get("like", 0),
            superlike=counts.get("superlike", 0),
            dislike=counts.get("dislike", 0),
            superdislike=counts.get("superdislike", 0),
        )

    def list_user_ratings(
        self,
        *,
        guild_id: int,
        user_id: int,
        rating: str | None,
        limit: int,
        offset: int,
    ) -> list[UserTrackRating]:
        where = "r.guild_id = ? AND r.user_id = ?"
        parameters: list[object] = [guild_id, user_id]
        if rating is not None:
            where += " AND r.rating = ?"
            parameters.append(rating)
        parameters.extend([limit, offset])
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    r.guild_id AS rating_guild_id,
                    r.user_id AS rating_user_id,
                    r.track_id AS rating_track_id,
                    r.rating AS rating_value,
                    r.updated_at AS rating_updated_at,
                    t.id,
                    t.source,
                    t.source_id,
                    t.relative_path,
                    t.file_name,
                    t.display_title,
                    t.category_guess,
                    t.artist_guess,
                    t.extension,
                    t.size_bytes,
                    t.modified_at,
                    t.indexed_at,
                    t.title,
                    t.artist,
                    t.duration_ms,
                    t.is_available
                FROM ratings r
                JOIN tracks t ON t.id = r.track_id
                WHERE {where}
                ORDER BY
                    r.updated_at DESC,
                    COALESCE(t.display_title, t.title, t.file_name, '') COLLATE NOCASE,
                    COALESCE(t.artist, t.artist_guess, '') COLLATE NOCASE,
                    r.track_id
                LIMIT ? OFFSET ?
                """,
                tuple(parameters),
            ).fetchall()
        return [_user_track_rating_from_row(row) for row in rows]


def _rating_from_row(row: Row) -> Rating:
    return Rating(
        guild_id=int(row["guild_id"]),
        user_id=int(row["user_id"]),
        track_id=int(row["track_id"]),
        rating=str(row["rating"]),
    )


def _user_track_rating_from_row(row: Row) -> UserTrackRating:
    return UserTrackRating(
        guild_id=int(row["rating_guild_id"]),
        user_id=int(row["rating_user_id"]),
        track_id=int(row["rating_track_id"]),
        rating=str(row["rating_value"]),
        updated_at=str(row["rating_updated_at"]),
        track=_track_from_row(row),
    )
