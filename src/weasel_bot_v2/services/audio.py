from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

import aiohttp
import discord

from weasel_bot_v2.models import Track
from weasel_bot_v2.services.local_library import safe_relative_path

LOGGER = logging.getLogger(__name__)

# Lavalink's local source is backed by Lavaplayer, which resolves plain file
# paths as local tracks. Do not use file:, file:///, or host-only paths here.
LAVALINK_LOCAL_IDENTIFIER_FORMAT = "absolute container file path"


@dataclass(frozen=True)
class PlaybackResult:
    ok: bool
    message: str


class AudioPlaybackService:
    """Minimal one-track local playback through Mafic/Lavalink."""

    def __init__(self, bot: Any, music_root: Path) -> None:
        self.bot = bot
        self.music_root = music_root

    async def play_local_track(
        self,
        *,
        interaction: discord.Interaction,
        track: Track,
    ) -> PlaybackResult:
        if not self.bot.lavalink_available:
            return PlaybackResult(ok=False, message="Lavalink is not connected.")

        guild = interaction.guild
        if guild is None:
            return PlaybackResult(ok=False, message="This command can only be used in a server.")

        member = interaction.user
        if not isinstance(member, discord.Member) or member.voice is None:
            return PlaybackResult(
                ok=False,
                message="Join a voice channel before using /play_local.",
            )

        channel = member.voice.channel
        if channel is None:
            return PlaybackResult(
                ok=False,
                message="Join a voice channel before using /play_local.",
            )

        if not track.relative_path:
            return PlaybackResult(ok=False, message="The selected track is missing a local path.")

        try:
            relative = safe_relative_path(track.relative_path)
        except ValueError:
            return PlaybackResult(ok=False, message="The selected track path is invalid.")

        identifier = build_lavalink_local_identifier(
            music_root=self.music_root,
            relative_path=relative.as_posix(),
        )
        LOGGER.info(
            "Built Lavalink local identifier for relative_path=%s identifier=%s",
            relative.as_posix(),
            identifier,
        )

        try:
            import mafic

            voice_client = guild.voice_client
            if voice_client is None:
                LOGGER.info("Connecting to voice for local playback.")
                player = await channel.connect(cls=mafic.Player)
                LOGGER.info("Voice connect succeeded for local playback.")
            else:
                player = voice_client
                LOGGER.info("Reusing existing voice client for local playback.")

            player = cast(Any, player)
            if not hasattr(player, "play"):
                return PlaybackResult(
                    ok=False,
                    message="The current voice client cannot play through Lavalink.",
                )

            LOGGER.info(
                "Loading local track from Lavalink for relative_path=%s.",
                relative.as_posix(),
            )
            lavalink_track = await self._load_local_track(identifier=identifier, mafic_module=mafic)
            LOGGER.info(
                "Local track load succeeded for relative_path=%s.",
                relative.as_posix(),
            )
            LOGGER.info("Starting player.play for local relative_path=%s.", relative.as_posix())
            await player.play(lavalink_track)
            LOGGER.info("player.play succeeded for local relative_path=%s.", relative.as_posix())
        except Exception as exc:  # noqa: BLE001 - Discord command should report a clean runtime error.
            LOGGER.warning(
                "Local Lavalink playback failed for relative_path=%s "
                "identifier_format=%s error=%s",
                relative.as_posix(),
                LAVALINK_LOCAL_IDENTIFIER_FORMAT,
                exc.__class__.__name__,
            )
            return PlaybackResult(
                ok=False,
                message=(
                    "Lavalink could not start the local track. "
                    f"Check the shared /music mount and Lavalink local-file support. "
                    f"Last error: {exc.__class__.__name__}."
                ),
            )

        title = track.display_title or track.file_name or track.relative_path
        return PlaybackResult(ok=True, message=f"Playing local track: {title}")

    async def _load_local_track(self, *, identifier: str, mafic_module: Any) -> Any:
        lavalink = self.bot.settings.lavalink
        if lavalink.password is None:
            raise LocalTrackLoadError("Lavalink password is not configured.")

        scheme = "https" if lavalink.secure else "http"
        url = f"{scheme}://{lavalink.host}:{lavalink.port}/v4/loadtracks"
        timeout = aiohttp.ClientTimeout(total=lavalink.timeout_seconds)
        headers = {"Authorization": lavalink.password}

        LOGGER.info(
            "Requesting Lavalink local track load using identifier_format=%s.",
            LAVALINK_LOCAL_IDENTIFIER_FORMAT,
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                url,
                params={"identifier": identifier},
                headers=headers,
            ) as response:
                response.raise_for_status()
                payload = await response.json()

        return normalize_lavalink_track_load(payload, mafic_module=mafic_module)


def build_lavalink_local_identifier(*, music_root: Path, relative_path: str) -> str:
    """Build Lavalink's local-source identifier from a container root and relative path."""
    root = PurePosixPath(music_root.as_posix())
    if not root.is_absolute():
        raise ValueError("Lavalink local music root must be an absolute container path.")

    safe_relative = safe_relative_path(relative_path)
    return (root / safe_relative).as_posix()


class LocalTrackLoadError(RuntimeError):
    """Raised when Lavalink does not return exactly one playable local track."""


def normalize_lavalink_track_load(load_result: object, *, mafic_module: Any) -> Any:
    if not isinstance(load_result, dict):
        raise LocalTrackLoadError("Lavalink loadtracks response was not a JSON object.")

    load_type = load_result.get("loadType")
    if load_type == "track":
        data = load_result.get("data")
        if not isinstance(data, dict):
            raise LocalTrackLoadError("Lavalink track response did not include track data.")
        return mafic_module.Track.from_data_with_info(data)

    if load_type in {"empty", "NO_MATCHES"}:
        raise LocalTrackLoadError("Lavalink did not find a local track for the identifier.")

    if load_type == "error":
        raise LocalTrackLoadError("Lavalink failed to load the local track.")

    raise LocalTrackLoadError(f"Unsupported Lavalink local loadType: {load_type!r}.")
