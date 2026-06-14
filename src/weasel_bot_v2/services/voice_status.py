from __future__ import annotations

import logging
from typing import Any, cast

import discord

from weasel_bot_v2.models import Track

LOGGER = logging.getLogger(__name__)
MAX_VOICE_STATUS_LENGTH = 120


class VoiceChannelStatusService:
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        if not hasattr(bot, "voice_channel_statuses"):
            bot.voice_channel_statuses = {}
        self._statuses: dict[int, str | None] = bot.voice_channel_statuses

    async def set_for_track(self, guild: discord.Guild, track: Track) -> None:
        status = format_voice_status(track)
        await self._apply(guild, status)

    async def clear(self, guild: discord.Guild) -> None:
        await self._apply(guild, None)

    async def _apply(self, guild: discord.Guild, status: str | None) -> None:
        if self._statuses.get(guild.id) == status:
            return

        channel = self._voice_channel(guild)
        if channel is None or not hasattr(channel, "edit"):
            self._statuses[guild.id] = status
            return

        try:
            await cast(Any, channel).edit(status=status)
            self._statuses[guild.id] = status
        except Exception as exc:  # noqa: BLE001 - status updates must never break playback.
            LOGGER.warning(
                "Voice channel status update failed guild_id=%s channel_id=%s error=%s",
                guild.id,
                getattr(channel, "id", "unknown"),
                exc.__class__.__name__,
            )

    def _voice_channel(self, guild: discord.Guild) -> object | None:
        player = getattr(guild, "voice_client", None)
        return getattr(player, "channel", None)


def format_voice_status(track: Track) -> str:
    title = _track_title(track)
    metadata = _track_artist(track)
    raw = f"🎵 {title}"
    if metadata:
        raw = f"{raw} — {metadata}"
    return _truncate_status(_sanitize_status(raw))


def _track_title(track: Track) -> str:
    return (
        _clean(track.display_title)
        or _clean(track.title)
        or _clean(track.file_name)
        or "Unknown local track"
    )


def _track_artist(track: Track) -> str | None:
    return _clean(track.artist) or _clean(track.artist_guess)


def _clean(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sanitize_status(value: str) -> str:
    return " ".join(value.replace("\n", " ").replace("\r", " ").split())


def _truncate_status(value: str) -> str:
    if len(value) <= MAX_VOICE_STATUS_LENGTH:
        return value
    return value[: MAX_VOICE_STATUS_LENGTH - 1].rstrip() + "…"
