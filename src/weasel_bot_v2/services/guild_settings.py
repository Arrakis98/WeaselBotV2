from __future__ import annotations

from weasel_bot_v2.models import GuildSettings
from weasel_bot_v2.repositories import GuildSettingsRepository


class GuildSettingsService:
    def __init__(self, repository: GuildSettingsRepository) -> None:
        self.repository = repository

    def get_or_create(self, guild_id: int) -> GuildSettings:
        return self.repository.ensure(guild_id)
