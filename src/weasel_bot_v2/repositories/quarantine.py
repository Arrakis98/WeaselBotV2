from __future__ import annotations

from sqlite3 import Row

from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import QuarantineRecord


class QuarantineRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def create(self, record: QuarantineRecord) -> QuarantineRecord:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                INSERT INTO track_quarantine (
                    track_id,
                    guild_id,
                    requested_by_user_id,
                    reason,
                    original_relative_path,
                    quarantine_relative_path,
                    state
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    record.track_id,
                    record.guild_id,
                    record.requested_by_user_id,
                    record.reason,
                    record.original_relative_path,
                    record.quarantine_relative_path,
                    record.state,
                ),
            ).fetchone()
            connection.commit()

        if row is None:
            raise RuntimeError("Failed to create quarantine record.")
        stored = self.get(int(row["id"]))
        if stored is None:
            raise RuntimeError("Failed to fetch quarantine record.")
        return stored

    def get(self, record_id: int) -> QuarantineRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    track_id,
                    guild_id,
                    requested_by_user_id,
                    reason,
                    original_relative_path,
                    quarantine_relative_path,
                    quarantined_at,
                    restored_at,
                    state
                FROM track_quarantine
                WHERE id = ?
                """,
                (record_id,),
            ).fetchone()
        return _record_from_row(row) if row else None

    def active_for_track(self, track_id: int) -> QuarantineRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    track_id,
                    guild_id,
                    requested_by_user_id,
                    reason,
                    original_relative_path,
                    quarantine_relative_path,
                    quarantined_at,
                    restored_at,
                    state
                FROM track_quarantine
                WHERE track_id = ? AND state = 'quarantined'
                ORDER BY id DESC
                LIMIT 1
                """,
                (track_id,),
            ).fetchone()
        return _record_from_row(row) if row else None

    def list_records(self, *, limit: int = 10) -> list[QuarantineRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    track_id,
                    guild_id,
                    requested_by_user_id,
                    reason,
                    original_relative_path,
                    quarantine_relative_path,
                    quarantined_at,
                    restored_at,
                    state
                FROM track_quarantine
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def mark_restored(self, record_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE track_quarantine
                SET state = 'restored', restored_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (record_id,),
            )
            connection.commit()


def _record_from_row(row: Row) -> QuarantineRecord:
    return QuarantineRecord(
        id=int(row["id"]),
        track_id=int(row["track_id"]),
        guild_id=int(row["guild_id"]),
        requested_by_user_id=int(row["requested_by_user_id"]),
        reason=str(row["reason"]),
        original_relative_path=str(row["original_relative_path"]),
        quarantine_relative_path=str(row["quarantine_relative_path"]),
        quarantined_at=str(row["quarantined_at"]),
        restored_at=str(row["restored_at"]) if row["restored_at"] is not None else None,
        state=str(row["state"]),
    )
