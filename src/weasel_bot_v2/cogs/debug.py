from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from weasel_bot_v2.bot import WeaselBot


class DebugCog(commands.Cog):
    def __init__(self, bot: WeaselBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="bot_status",
        description="Show safe bot, database, Lavalink, and feature flag status.",
    )
    async def bot_status(self, interaction: discord.Interaction) -> None:
        database_status = "ready" if self.bot.database.bootstrapped else "configured"
        message = "\n".join(
            (
                "Bot: online",
                f"Database: {database_status}",
                f"Lavalink/Mafic: {self.bot.lavalink_status}",
                f"Enabled features: {self.bot.settings.features.safe_summary()}",
            )
        )
        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: WeaselBot) -> None:
    await bot.add_cog(DebugCog(bot))
