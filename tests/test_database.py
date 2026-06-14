from __future__ import annotations

import sqlite3
from pathlib import Path

from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase


def test_database_schema_bootstrap_creates_initial_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "weasel.db"
    database = SQLiteDatabase(DatabaseConfig(path=database_path))

    database.initialize()

    assert database.bootstrapped is True
    assert database_path.exists()

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()

    table_names = {row[0] for row in rows}
    assert {
        "guild_settings",
        "users",
        "tracks",
        "play_history",
        "ratings",
        "track_volume_overrides",
        "playlists",
        "playlist_items",
    }.issubset(table_names)


def test_database_schema_bootstrap_is_idempotent_for_track_volume_overrides(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "weasel.db"
    database = SQLiteDatabase(DatabaseConfig(path=database_path))

    database.initialize()
    database.initialize()

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'track_volume_overrides'
            """
        ).fetchall()

    assert rows == [("track_volume_overrides",)]
