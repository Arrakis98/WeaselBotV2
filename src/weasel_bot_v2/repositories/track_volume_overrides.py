from __future__ import annotations

from sqlite3 import Row

from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import TrackVolumeOverride


class TrackVolumeOverrideRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get(self, guild_id: int, track_id: int) -> TrackVolumeOverride | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT guild_id, track_id, volume, created_at, updated_at
                FROM track_volume_overrides
                WHERE guild_id = ? AND track_id = ?
                """,
                (guild_id, track_id),
            ).fetchone()

        return _override_from_row(row) if row else None

    def save(self, guild_id: int, track_id: int, volume: int) -> TrackVolumeOverride:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO track_volume_overrides (guild_id, track_id, volume)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, track_id) DO UPDATE SET
                    volume = excluded.volume,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (guild_id, track_id, volume),
            )
            connection.commit()

        saved = self.get(guild_id, track_id)
        if saved is None:
            raise RuntimeError("Failed to save track volume override.")
        return saved

    def delete(self, guild_id: int, track_id: int) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM track_volume_overrides
                WHERE guild_id = ? AND track_id = ?
                """,
                (guild_id, track_id),
            )
            connection.commit()

        return cursor.rowcount > 0


def _override_from_row(row: Row) -> TrackVolumeOverride:
    return TrackVolumeOverride(
        guild_id=int(row["guild_id"]),
        track_id=int(row["track_id"]),
        volume=int(row["volume"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
