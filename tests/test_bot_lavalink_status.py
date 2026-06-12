from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from weasel_bot_v2.bot import WeaselBot
from weasel_bot_v2.config import BotConfig, DatabaseConfig, FeatureFlags, LavalinkConfig, Settings


def _settings(lavalink: LavalinkConfig) -> Settings:
    return Settings(
        discord_token="test-token",
        discord_test_guild_id=None,
        bot=BotConfig(
            data_dir=Path("/tmp/weasel-data"),
            logs_dir=Path("/tmp/weasel-logs"),
            music_library=Path("/tmp/weasel-music"),
        ),
        lavalink=lavalink,
        database=DatabaseConfig(path=Path("/tmp/weasel-data/weasel-test.db")),
        features=FeatureFlags(),
    )


@pytest.mark.asyncio
async def test_lavalink_not_configured_status() -> None:
    bot = WeaselBot(_settings(LavalinkConfig(password=None)))

    await bot._setup_lavalink()

    assert bot.lavalink_available is False
    assert bot.lavalink_status == "not configured"
    assert bot.lavalink_last_error is None

    await bot.close()


@pytest.mark.asyncio
async def test_lavalink_connection_failure_status(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNodePool:
        def __init__(self, bot: WeaselBot) -> None:
            self.bot = bot

        async def create_node(self, **kwargs: object) -> None:
            raise RuntimeError("simulated connection failure")

    monkeypatch.setitem(sys.modules, "mafic", SimpleNamespace(NodePool=FakeNodePool))
    bot = WeaselBot(_settings(LavalinkConfig(password="test-password")))

    await bot._setup_lavalink()

    assert bot.lavalink_available is False
    assert bot.lavalink_status == "failed/unavailable"
    assert bot.lavalink_last_error == "RuntimeError"

    await bot.close()


@pytest.mark.asyncio
async def test_lavalink_connection_starts_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = WeaselBot(_settings(LavalinkConfig(password="test-password")))
    call_count = 0

    async def fake_setup_lavalink() -> None:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0)

    monkeypatch.setattr(bot, "_setup_lavalink", fake_setup_lavalink)

    bot._start_lavalink_connection()
    first_task = bot._lavalink_connection_task
    bot._start_lavalink_connection()

    assert first_task is bot._lavalink_connection_task
    assert first_task is not None

    await first_task

    assert call_count == 1

    await bot.close()
