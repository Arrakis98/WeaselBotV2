from __future__ import annotations

from sqlite3 import Row

from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Playlist, PlaylistItem


class PlaylistRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def create(self, playlist: Playlist) -> Playlist:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO playlists (guild_id, owner_user_id, name, description)
                VALUES (?, ?, ?, ?)
                """,
                (
                    playlist.guild_id,
                    playlist.owner_user_id,
                    playlist.name,
                    playlist.description,
                ),
            )
            playlist_id = cursor.lastrowid
            connection.commit()

        if playlist_id is None:
            raise RuntimeError("Failed to create playlist.")
        stored = self.get(int(playlist_id))
        if stored is None:
            raise RuntimeError("Failed to create playlist.")
        return stored

    def get(self, playlist_id: int) -> Playlist | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, guild_id, owner_user_id, name, description
                FROM playlists
                WHERE id = ?
                """,
                (playlist_id,),
            ).fetchone()

        return _playlist_from_row(row) if row else None

    def list_for_owner(self, owner_user_id: int) -> list[Playlist]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, guild_id, owner_user_id, name, description
                FROM playlists
                WHERE owner_user_id = ?
                ORDER BY id
                """,
                (owner_user_id,),
            ).fetchall()

        return [_playlist_from_row(row) for row in rows]

    def add_item(self, item: PlaylistItem) -> PlaylistItem:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO playlist_items (
                    playlist_id,
                    position,
                    track_id,
                    added_by_user_id
                )
                VALUES (?, ?, ?, ?)
                """,
                (item.playlist_id, item.position, item.track_id, item.added_by_user_id),
            )
            connection.commit()
        return item

    def list_items(self, playlist_id: int) -> list[PlaylistItem]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT playlist_id, position, track_id, added_by_user_id
                FROM playlist_items
                WHERE playlist_id = ?
                ORDER BY position
                """,
                (playlist_id,),
            ).fetchall()

        return [_playlist_item_from_row(row) for row in rows]


def _playlist_from_row(row: Row) -> Playlist:
    return Playlist(
        id=int(row["id"]),
        guild_id=row["guild_id"],
        owner_user_id=int(row["owner_user_id"]),
        name=row["name"],
        description=row["description"],
    )


def _playlist_item_from_row(row: Row) -> PlaylistItem:
    return PlaylistItem(
        playlist_id=int(row["playlist_id"]),
        position=int(row["position"]),
        track_id=int(row["track_id"]),
        added_by_user_id=row["added_by_user_id"],
    )
