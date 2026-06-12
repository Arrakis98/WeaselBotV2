from __future__ import annotations

from weasel_bot_v2.models import GuildSettings
from weasel_bot_v2.repositories import GuildSettingsRepository
from weasel_bot_v2.services.player_state import DEFAULT_VOLUME, clamp_volume


class GuildSettingsService:
    def __init__(self, repository: GuildSettingsRepository) -> None:
        self.repository = repository

    def get_or_create(self, guild_id: int) -> GuildSettings:
        return self.repository.ensure(guild_id)

    def get_volume(self, guild_id: int) -> int:
        settings = self.repository.ensure(guild_id)
        volume = settings.default_volume
        return clamp_volume(DEFAULT_VOLUME if volume is None else volume)

    def set_volume(self, guild_id: int, volume: int) -> int:
        settings = self.repository.ensure(guild_id)
        clamped = clamp_volume(volume)
        self.repository.save(
            GuildSettings(
                guild_id=settings.guild_id,
                command_prefix=settings.command_prefix,
                locale=settings.locale,
                dj_role_id=settings.dj_role_id,
                default_volume=clamped,
            )
        )
        return clamped
