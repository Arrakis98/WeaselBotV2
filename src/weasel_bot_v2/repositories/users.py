from __future__ import annotations

from sqlite3 import Row

from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import UserRecord


class UserRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get(self, user_id: int) -> UserRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, display_name
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

        return _user_from_row(row) if row else None

    def upsert(self, user: UserRecord) -> UserRecord:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO users (user_id, display_name)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user.user_id, user.display_name),
            )
            connection.commit()

        stored = self.get(user.user_id)
        if stored is None:
            raise RuntimeError("Failed to create user record.")
        return stored


def _user_from_row(row: Row) -> UserRecord:
    return UserRecord(user_id=int(row["user_id"]), display_name=row["display_name"])
