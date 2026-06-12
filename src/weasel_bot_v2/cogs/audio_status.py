from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from weasel_bot_v2.bot import WeaselBot


class AudioStatusCog(commands.Cog):
    def __init__(self, bot: WeaselBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="audio_status",
        description="Show whether the Lavalink audio backend appears available.",
    )
    async def audio_status(self, interaction: discord.Interaction) -> None:
        message = f"Lavalink/Mafic: {self.bot.lavalink_status}"
        if self.bot.lavalink_last_error:
            message = f"{message} (last error: {self.bot.lavalink_last_error})"

        await interaction.response.send_message(
            message,
            ephemeral=True,
        )


async def setup(bot: WeaselBot) -> None:
    await bot.add_cog(AudioStatusCog(bot))
