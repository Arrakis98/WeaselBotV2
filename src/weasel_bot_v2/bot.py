from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from discord.ext import commands

from weasel_bot_v2.config import Settings
from weasel_bot_v2.logging_config import configure_logging

LOGGER = logging.getLogger(__name__)

COGS = (
    "weasel_bot_v2.cogs.admin",
    "weasel_bot_v2.cogs.audio_status",
)


class WeaselBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.voice_states = True

        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        self.lavalink_pool: Any | None = None
        self.lavalink_available = False
        self.lavalink_status = "not configured"
        self.lavalink_last_error: str | None = None
        self._lavalink_connection_started = False
        self._lavalink_connection_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        for cog in COGS:
            await self.load_extension(cog)

        await self._sync_commands()

    async def on_ready(self) -> None:
        LOGGER.info(
            "Logged in as %s (ID: %s).",
            self.user,
            self.user.id if self.user else "unknown",
        )
        self._start_lavalink_connection()

    def _start_lavalink_connection(self) -> None:
        if self._lavalink_connection_started:
            return

        self._lavalink_connection_started = True
        self._lavalink_connection_task = asyncio.create_task(
            self._setup_lavalink(),
            name="weasel-lavalink-connect",
        )

    async def _setup_lavalink(self) -> None:
        lavalink = self.settings.lavalink
        if not lavalink.configured:
            self.lavalink_available = False
            self.lavalink_status = "not configured"
            self.lavalink_last_error = None
            LOGGER.info("Lavalink is not fully configured; /audio_status will report unavailable.")
            return

        password = lavalink.password
        if password is None:
            self.lavalink_available = False
            self.lavalink_status = "not configured"
            self.lavalink_last_error = None
            LOGGER.info(
                "Lavalink password is not configured; /audio_status will report unavailable."
            )
            return

        self.lavalink_available = False
        self.lavalink_status = "connecting"
        self.lavalink_last_error = None
        LOGGER.info("Connecting to Lavalink/Mafic at %s:%s.", lavalink.host, lavalink.port)

        try:
            import mafic

            pool = mafic.NodePool(self)
            await asyncio.wait_for(
                pool.create_node(
                    host=lavalink.host,
                    port=lavalink.port,
                    label="main",
                    password=password,
                    secure=lavalink.secure,
                ),
                timeout=30,
            )
            self.lavalink_pool = pool
        except Exception as exc:  # noqa: BLE001 - startup should continue so /audio_status can explain.
            self.lavalink_available = False
            self.lavalink_status = "failed/unavailable"
            self.lavalink_last_error = exc.__class__.__name__
            LOGGER.warning("Lavalink/Mafic connection failed: %s", exc.__class__.__name__)
            return

        self.lavalink_available = True
        self.lavalink_status = "connected"
        self.lavalink_last_error = None
        LOGGER.info("Lavalink/Mafic connection is available at %s:%s", lavalink.host, lavalink.port)

    async def _sync_commands(self) -> None:
        if self.settings.discord_test_guild_id is not None:
            guild = discord.Object(id=self.settings.discord_test_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            LOGGER.info("Synced %s command(s) to test guild.", len(synced))
            return

        synced = await self.tree.sync()
        LOGGER.info("Synced %s global command(s).", len(synced))


async def run_bot() -> None:
    configure_logging()
    settings = Settings.load(require_token=True)
    if settings.discord_token is None:
        raise RuntimeError("DISCORD_TOKEN is required.")

    async with WeaselBot(settings) as bot:
        await bot.start(settings.discord_token)
