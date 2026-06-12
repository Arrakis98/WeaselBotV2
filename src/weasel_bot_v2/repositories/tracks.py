from __future__ import annotations

from sqlite3 import Row

from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Track


class TrackRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get(self, track_id: int) -> Track | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, source, source_id, title, artist, duration_ms
                FROM tracks
                WHERE id = ?
                """,
                (track_id,),
            ).fetchone()

        return _track_from_row(row) if row else None

    def upsert(self, track: Track) -> Track:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tracks (source, source_id, title, artist, duration_ms)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source, source_id) DO UPDATE SET
                    title = excluded.title,
                    artist = excluded.artist,
                    duration_ms = excluded.duration_ms
                RETURNING id
                """,
                (track.source, track.source_id, track.title, track.artist, track.duration_ms),
            )
            row = cursor.fetchone()
            connection.commit()

        if row is None:
            raise RuntimeError("Failed to create track record.")
        stored = self.get(int(row["id"]))
        if stored is None:
            raise RuntimeError("Failed to fetch track record.")
        return stored


def _track_from_row(row: Row) -> Track:
    return Track(
        id=int(row["id"]),
        source=row["source"],
        source_id=row["source_id"],
        title=row["title"],
        artist=row["artist"],
        duration_ms=row["duration_ms"],
    )
