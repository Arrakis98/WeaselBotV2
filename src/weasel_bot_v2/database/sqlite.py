from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database.schema import SCHEMA_STATEMENTS


class SQLiteDatabase:
    """Small SQLite connection factory and schema bootstrapper."""

    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self.bootstrapped = False

    @property
    def path(self) -> Path:
        return self.config.path

    @property
    def configured(self) -> bool:
        return self.config.configured

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
            connection.commit()
        self.bootstrapped = True

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()
