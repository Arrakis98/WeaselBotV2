from __future__ import annotations

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id INTEGER PRIMARY KEY,
        command_prefix TEXT,
        locale TEXT,
        dj_role_id INTEGER,
        default_volume INTEGER NOT NULL DEFAULT 100,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        display_name TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        relative_path TEXT,
        file_name TEXT,
        display_title TEXT,
        category_guess TEXT,
        artist_guess TEXT,
        extension TEXT,
        size_bytes INTEGER,
        modified_at REAL,
        indexed_at TEXT,
        title TEXT,
        artist TEXT,
        duration_ms INTEGER,
        is_available INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (source, source_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS play_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        user_id INTEGER,
        track_id INTEGER,
        context TEXT,
        played_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (track_id) REFERENCES tracks (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ratings (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        track_id INTEGER NOT NULL,
        rating TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (guild_id, user_id, track_id),
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (track_id) REFERENCES tracks (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS track_volume_overrides (
        guild_id INTEGER NOT NULL,
        track_id INTEGER NOT NULL,
        volume INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (guild_id, track_id),
        FOREIGN KEY (track_id) REFERENCES tracks (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS track_quarantine (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        track_id INTEGER NOT NULL,
        guild_id INTEGER NOT NULL,
        requested_by_user_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        original_relative_path TEXT NOT NULL,
        quarantine_relative_path TEXT NOT NULL,
        quarantined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        restored_at TEXT,
        state TEXT NOT NULL DEFAULT 'quarantined',
        FOREIGN KEY (track_id) REFERENCES tracks (id),
        FOREIGN KEY (requested_by_user_id) REFERENCES users (user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS playlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER,
        owner_user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (owner_user_id) REFERENCES users (user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS playlist_items (
        playlist_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        track_id INTEGER NOT NULL,
        added_by_user_id INTEGER,
        added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (playlist_id, position),
        FOREIGN KEY (playlist_id) REFERENCES playlists (id) ON DELETE CASCADE,
        FOREIGN KEY (track_id) REFERENCES tracks (id),
        FOREIGN KEY (added_by_user_id) REFERENCES users (user_id)
    )
    """,
)

SCHEMA_MIGRATIONS = (
    "ALTER TABLE tracks ADD COLUMN relative_path TEXT",
    "ALTER TABLE tracks ADD COLUMN file_name TEXT",
    "ALTER TABLE tracks ADD COLUMN display_title TEXT",
    "ALTER TABLE tracks ADD COLUMN category_guess TEXT",
    "ALTER TABLE tracks ADD COLUMN artist_guess TEXT",
    "ALTER TABLE tracks ADD COLUMN extension TEXT",
    "ALTER TABLE tracks ADD COLUMN size_bytes INTEGER",
    "ALTER TABLE tracks ADD COLUMN modified_at REAL",
    "ALTER TABLE tracks ADD COLUMN indexed_at TEXT",
    "ALTER TABLE tracks ADD COLUMN is_available INTEGER NOT NULL DEFAULT 1",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_local_relative_path "
    "ON tracks(relative_path) WHERE source = 'local'",
    "CREATE INDEX IF NOT EXISTS idx_tracks_local_search ON tracks("
    "source, display_title, artist_guess, category_guess, file_name, relative_path"
    ")",
    "ALTER TABLE guild_settings ADD COLUMN default_volume INTEGER NOT NULL DEFAULT 100",
    """
    CREATE TABLE IF NOT EXISTS track_quarantine (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        track_id INTEGER NOT NULL,
        guild_id INTEGER NOT NULL,
        requested_by_user_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        original_relative_path TEXT NOT NULL,
        quarantine_relative_path TEXT NOT NULL,
        quarantined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        restored_at TEXT,
        state TEXT NOT NULL DEFAULT 'quarantined',
        FOREIGN KEY (track_id) REFERENCES tracks (id),
        FOREIGN KEY (requested_by_user_id) REFERENCES users (user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_track_quarantine_state ON track_quarantine(state, track_id)",
    """
    CREATE TABLE IF NOT EXISTS track_volume_overrides (
        guild_id INTEGER NOT NULL,
        track_id INTEGER NOT NULL,
        volume INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (guild_id, track_id),
        FOREIGN KEY (track_id) REFERENCES tracks (id) ON DELETE CASCADE
    )
    """,
)
