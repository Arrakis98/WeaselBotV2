from __future__ import annotations

from sqlite3 import Row

from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import GuildSettings


class GuildSettingsRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get(self, guild_id: int) -> GuildSettings | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT guild_id, command_prefix, locale, dj_role_id, default_volume
                FROM guild_settings
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchone()

        return _guild_settings_from_row(row) if row else None

    def ensure(self, guild_id: int) -> GuildSettings:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO guild_settings (guild_id)
                VALUES (?)
                ON CONFLICT(guild_id) DO NOTHING
                """,
                (guild_id,),
            )
            connection.commit()

        settings = self.get(guild_id)
        if settings is None:
            raise RuntimeError("Failed to create guild settings.")
        return settings

    def save(self, settings: GuildSettings) -> GuildSettings:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO guild_settings (
                    guild_id,
                    command_prefix,
                    locale,
                    dj_role_id,
                    default_volume
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    command_prefix = excluded.command_prefix,
                    locale = excluded.locale,
                    dj_role_id = excluded.dj_role_id,
                    default_volume = excluded.default_volume,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    settings.guild_id,
                    settings.command_prefix,
                    settings.locale,
                    settings.dj_role_id,
                    settings.default_volume,
                ),
            )
            connection.commit()

        return self.ensure(settings.guild_id)


def _guild_settings_from_row(row: Row) -> GuildSettings:
    return GuildSettings(
        guild_id=int(row["guild_id"]),
        command_prefix=row["command_prefix"],
        locale=row["locale"],
        dj_role_id=row["dj_role_id"],
        default_volume=int(row["default_volume"]),
    )
