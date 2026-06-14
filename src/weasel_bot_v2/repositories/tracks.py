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
                WHERE id = ?
                """,
                (track_id,),
            ).fetchone()

        return _track_from_row(row) if row else None

    def upsert(self, track: Track) -> Track:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tracks (
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
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, source_id) DO UPDATE SET
                    relative_path = excluded.relative_path,
                    file_name = excluded.file_name,
                    display_title = excluded.display_title,
                    category_guess = excluded.category_guess,
                    artist_guess = excluded.artist_guess,
                    extension = excluded.extension,
                    size_bytes = excluded.size_bytes,
                    modified_at = excluded.modified_at,
                    indexed_at = excluded.indexed_at,
                    title = excluded.title,
                    artist = excluded.artist,
                    duration_ms = excluded.duration_ms,
                    is_available = excluded.is_available
                RETURNING id
                """,
                (
                    track.source,
                    track.source_id,
                    track.relative_path,
                    track.file_name,
                    track.display_title,
                    track.category_guess,
                    track.artist_guess,
                    track.extension,
                    track.size_bytes,
                    track.modified_at,
                    track.indexed_at,
                    track.title,
                    track.artist,
                    track.duration_ms,
                    int(track.is_available),
                ),
            )
            row = cursor.fetchone()
            connection.commit()

        if row is None:
            raise RuntimeError("Failed to create track record.")
        stored = self.get(int(row["id"]))
        if stored is None:
            raise RuntimeError("Failed to fetch track record.")
        return stored

    def get_local_by_relative_path(self, relative_path: str) -> Track | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
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
                WHERE source = 'local' AND relative_path = ?
                """,
                (relative_path,),
            ).fetchone()

        return _track_from_row(row) if row else None

    def upsert_local(self, track: Track) -> Track:
        if track.source != "local" or not track.relative_path:
            raise ValueError("Local tracks require source='local' and a relative path.")
        return self.upsert(track)

    def set_available(self, track_id: int, available: bool) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE tracks SET is_available = ? WHERE id = ?",
                (int(available), track_id),
            )
            connection.commit()

    def list_local(self, *, available_only: bool = False) -> list[Track]:
        where = "WHERE source = 'local'"
        if available_only:
            where += " AND is_available = 1"
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
                {where}
                ORDER BY relative_path COLLATE NOCASE, id
                """
            ).fetchall()

        return [_track_from_row(row) for row in rows]

    def count_local(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS track_count FROM tracks WHERE source = 'local' "
                "AND is_available = 1"
            ).fetchone()

        return int(row["track_count"]) if row else 0


def _track_from_row(row: Row) -> Track:
    return Track(
        id=int(row["id"]),
        source=row["source"],
        source_id=row["source_id"],
        relative_path=row["relative_path"],
        file_name=row["file_name"],
        display_title=row["display_title"],
        category_guess=row["category_guess"],
        artist_guess=row["artist_guess"],
        extension=row["extension"],
        size_bytes=row["size_bytes"],
        modified_at=row["modified_at"],
        indexed_at=row["indexed_at"],
        title=row["title"],
        artist=row["artist"],
        duration_ms=row["duration_ms"],
        is_available=bool(row["is_available"]),
    )
