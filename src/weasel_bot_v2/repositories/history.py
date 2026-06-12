from __future__ import annotations

from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import PlayHistoryEntry


class HistoryRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def record_play(self, entry: PlayHistoryEntry) -> PlayHistoryEntry:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO play_history (guild_id, user_id, track_id, context)
                VALUES (?, ?, ?, ?)
                """,
                (entry.guild_id, entry.user_id, entry.track_id, entry.context),
            )
            history_id = cursor.lastrowid
            connection.commit()

        if history_id is None:
            raise RuntimeError("Failed to create play history record.")
        return PlayHistoryEntry(
            id=int(history_id),
            guild_id=entry.guild_id,
            user_id=entry.user_id,
            track_id=entry.track_id,
            context=entry.context,
        )
