from __future__ import annotations

from sqlite3 import Row

from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import (
    PlayAllArtistExclusion,
    PlayAllPolicy,
    PlayAllTrackException,
    Track,
)
from weasel_bot_v2.repositories.tracks import _track_from_row


class PlayAllPolicyRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def add_artist_exclusion(
        self,
        *,
        guild_id: int,
        normalized_artist: str,
        display_artist: str,
        created_by_user_id: int,
    ) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO play_all_artist_exclusions (
                    guild_id,
                    normalized_artist,
                    display_artist,
                    created_by_user_id
                )
                VALUES (?, ?, ?, ?)
                """,
                (guild_id, normalized_artist, display_artist, created_by_user_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    def remove_artist_exclusion(self, *, guild_id: int, normalized_artist: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM play_all_artist_exclusions
                WHERE guild_id = ? AND normalized_artist = ?
                """,
                (guild_id, normalized_artist),
            )
            connection.commit()
            return cursor.rowcount > 0

    def list_artist_exclusions(self, guild_id: int) -> list[PlayAllArtistExclusion]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    guild_id,
                    normalized_artist,
                    display_artist,
                    created_by_user_id,
                    created_at
                FROM play_all_artist_exclusions
                WHERE guild_id = ?
                ORDER BY display_artist COLLATE NOCASE, normalized_artist
                """,
                (guild_id,),
            ).fetchall()
        return [_artist_exclusion_from_row(row) for row in rows]

    def add_track_exception(
        self,
        *,
        guild_id: int,
        track_id: int,
        created_by_user_id: int,
    ) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO play_all_track_exceptions (
                    guild_id,
                    track_id,
                    created_by_user_id
                )
                VALUES (?, ?, ?)
                """,
                (guild_id, track_id, created_by_user_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    def remove_track_exception(self, *, guild_id: int, track_id: int) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM play_all_track_exceptions
                WHERE guild_id = ? AND track_id = ?
                """,
                (guild_id, track_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    def has_track_exception(self, *, guild_id: int, track_id: int) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM play_all_track_exceptions
                WHERE guild_id = ? AND track_id = ?
                """,
                (guild_id, track_id),
            ).fetchone()
        return row is not None

    def list_track_exceptions(self, guild_id: int) -> list[PlayAllTrackException]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    guild_id,
                    track_id,
                    created_by_user_id,
                    created_at
                FROM play_all_track_exceptions
                WHERE guild_id = ?
                ORDER BY created_at DESC, track_id
                """,
                (guild_id,),
            ).fetchall()
        return [_track_exception_from_row(row) for row in rows]

    def get_policy(self, guild_id: int) -> PlayAllPolicy:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    guild_id,
                    strict_exclusions,
                    updated_by_user_id,
                    updated_at
                FROM play_all_policy
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchone()
        if row is None:
            return PlayAllPolicy(guild_id=guild_id)
        return _policy_from_row(row)

    def set_strict(
        self,
        *,
        guild_id: int,
        enabled: bool,
        updated_by_user_id: int,
    ) -> PlayAllPolicy:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO play_all_policy (
                    guild_id,
                    strict_exclusions,
                    updated_by_user_id,
                    updated_at
                )
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(guild_id) DO UPDATE SET
                    strict_exclusions = excluded.strict_exclusions,
                    updated_by_user_id = excluded.updated_by_user_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (guild_id, int(enabled), updated_by_user_id),
            )
            connection.commit()
        return self.get_policy(guild_id)

    def list_exception_tracks(
        self,
        guild_id: int,
    ) -> list[tuple[PlayAllTrackException, Track | None]]:
        exceptions = self.list_track_exceptions(guild_id)
        if not exceptions:
            return []
        placeholders = ", ".join("?" for _ in exceptions)
        track_ids = [exception.track_id for exception in exceptions]
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    id,
                    source,
                    source_id,
                    relative_path,
                    file_name,
                    display_title,
                    category_guess,
                    artist_guess,
                    extension,
                    size_bytes,
                    modified_at,
                    indexed_at,
                    title,
                    artist,
                    duration_ms,
                    is_available
                FROM tracks
                WHERE id IN ({placeholders})
                """,
                track_ids,
            ).fetchall()
        tracks = {int(row["id"]): _track_from_row(row) for row in rows}
        return [(exception, tracks.get(exception.track_id)) for exception in exceptions]


def _artist_exclusion_from_row(row: Row) -> PlayAllArtistExclusion:
    return PlayAllArtistExclusion(
        guild_id=int(row["guild_id"]),
        normalized_artist=row["normalized_artist"],
        display_artist=row["display_artist"],
        created_by_user_id=int(row["created_by_user_id"]),
        created_at=row["created_at"],
    )


def _track_exception_from_row(row: Row) -> PlayAllTrackException:
    return PlayAllTrackException(
        guild_id=int(row["guild_id"]),
        track_id=int(row["track_id"]),
        created_by_user_id=int(row["created_by_user_id"]),
        created_at=row["created_at"],
    )


def _policy_from_row(row: Row) -> PlayAllPolicy:
    return PlayAllPolicy(
        guild_id=int(row["guild_id"]),
        strict_exclusions=bool(row["strict_exclusions"]),
        updated_by_user_id=row["updated_by_user_id"],
        updated_at=row["updated_at"],
    )
