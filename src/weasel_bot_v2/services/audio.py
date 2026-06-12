from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

import aiohttp
import discord

from weasel_bot_v2.models import GuildSettings, Track
from weasel_bot_v2.repositories import GuildSettingsRepository
from weasel_bot_v2.services.local_library import safe_relative_path
from weasel_bot_v2.services.player_state import (
    DEFAULT_VOLUME,
    GuildPlayerState,
    clamp_volume,
)

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

        state = self.bot.player_states.get_or_create(guild.id)
        if state.has_track:
            position = state.enqueue(track)
            title = track.display_title or track.file_name or track.relative_path
            return PlaybackResult(
                ok=True,
                message=f"Added to queue at position {position}: {title}",
            )

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

        player = await self._connect_player(guild, channel)
        result = await self.play_track_on_player(guild=guild, player=player, track=track)
        if result.ok:
            title = track.display_title or track.file_name or track.relative_path
            return PlaybackResult(ok=True, message=f"Now playing: {title}")
        return result

    async def play_track_on_player(
        self,
        *,
        guild: discord.Guild,
        player: object,
        track: Track,
    ) -> PlaybackResult:
        if not self.bot.lavalink_available:
            return PlaybackResult(ok=False, message="Lavalink is not connected.")

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
            state = self.bot.player_states.get_or_create(guild.id)
            state.set_volume(self._load_saved_volume(guild.id))
            await cast(Any, player).play(lavalink_track)
            await self._apply_volume(player, state.volume)
            state.set_current_track(track)
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

    async def _connect_player(self, guild: discord.Guild, channel: object) -> object:
        import mafic

        voice_client = guild.voice_client
        if voice_client is None:
            LOGGER.info("Connecting to voice for local playback.")
            player = await cast(Any, channel).connect(cls=mafic.Player)
            LOGGER.info("Voice connect succeeded for local playback.")
            return player

        LOGGER.info("Reusing existing voice client for local playback.")
        return voice_client

    async def pause(self, guild: discord.Guild) -> PlaybackResult:
        state = self._active_state(guild)
        if state is None:
            return PlaybackResult(ok=False, message="Nothing is playing.")

        player = self._active_player(guild)
        if player is None or not hasattr(player, "pause"):
            return PlaybackResult(ok=False, message="The bot is not connected to a player.")

        try:
            await cast(Any, player).pause(True)
        except Exception as exc:  # noqa: BLE001 - controls should report clean failures.
            return PlaybackResult(
                ok=False,
                message=f"Could not pause playback: {exc.__class__.__name__}.",
            )

        state.paused = True
        return PlaybackResult(ok=True, message="Paused.")

    async def resume(self, guild: discord.Guild) -> PlaybackResult:
        state = self._active_state(guild)
        if state is None:
            return PlaybackResult(ok=False, message="Nothing is playing.")

        player = self._active_player(guild)
        if player is None or not hasattr(player, "resume"):
            return PlaybackResult(ok=False, message="The bot is not connected to a player.")

        try:
            await cast(Any, player).resume()
        except Exception as exc:  # noqa: BLE001 - controls should report clean failures.
            return PlaybackResult(
                ok=False,
                message=f"Could not resume playback: {exc.__class__.__name__}.",
            )

        state.paused = False
        return PlaybackResult(ok=True, message="Resumed.")

    async def stop(self, guild: discord.Guild) -> PlaybackResult:
        state = self._active_state(guild)
        if state is None:
            return PlaybackResult(ok=False, message="Nothing is playing.")

        player = self._active_player(guild)
        if player is None or not hasattr(player, "stop"):
            return PlaybackResult(ok=False, message="The bot is not connected to a player.")

        try:
            await cast(Any, player).stop()
        except Exception as exc:  # noqa: BLE001 - controls should report clean failures.
            return PlaybackResult(
                ok=False,
                message=f"Could not stop playback: {exc.__class__.__name__}.",
            )

        state.clear_current_track()
        return PlaybackResult(ok=True, message="Stopped.")

    async def leave(self, guild: discord.Guild) -> PlaybackResult:
        player = self._active_player(guild)
        if player is None or not hasattr(player, "disconnect"):
            self.bot.player_states.clear(guild.id)
            return PlaybackResult(ok=False, message="The bot is not connected to voice.")

        try:
            if hasattr(player, "stop"):
                await cast(Any, player).stop()
            await cast(Any, player).disconnect()
        except Exception as exc:  # noqa: BLE001 - controls should report clean failures.
            return PlaybackResult(
                ok=False,
                message=f"Could not leave voice: {exc.__class__.__name__}.",
            )

        self.bot.player_states.clear(guild.id)
        return PlaybackResult(ok=True, message="Left voice.")

    async def skip(self, guild: discord.Guild) -> PlaybackResult:
        state = self._active_state(guild)
        if state is None:
            return PlaybackResult(ok=False, message="Nothing is playing.")

        player = self._active_player(guild)
        if player is None:
            return PlaybackResult(ok=False, message="The bot is not connected to a player.")

        next_track = state.pop_next()
        if next_track is None:
            try:
                if hasattr(player, "stop"):
                    await cast(Any, player).stop()
            except Exception as exc:  # noqa: BLE001 - controls should report clean failures.
                return PlaybackResult(
                    ok=False,
                    message=f"Could not skip playback: {exc.__class__.__name__}.",
                )
            state.clear_current_track()
            return PlaybackResult(ok=True, message="Skipped. The queue is empty.")

        return await self.play_track_on_player(guild=guild, player=player, track=next_track)

    async def back(self, guild: discord.Guild) -> PlaybackResult:
        state = self._active_state(guild)
        if state is None:
            return PlaybackResult(ok=False, message="Nothing is playing.")

        player = self._active_player(guild)
        if player is None:
            return PlaybackResult(ok=False, message="The bot is not connected to a player.")

        previous = state.back_to_previous()
        if previous is None:
            return PlaybackResult(ok=False, message="No previous track is available.")

        state.current_track = None
        return await self.play_track_on_player(guild=guild, player=player, track=previous)

    def clear_queue(self, guild_id: int) -> PlaybackResult:
        state = self.bot.player_states.get_or_create(guild_id)
        cleared = state.clear_queue()
        return PlaybackResult(ok=True, message=f"Cleared {cleared} queued track(s).")

    def remove_from_queue(self, guild_id: int, position: int) -> PlaybackResult:
        state = self.bot.player_states.get_or_create(guild_id)
        removed = state.remove_queue_item(position)
        if removed is None:
            return PlaybackResult(ok=False, message="No queued track exists at that position.")
        title = removed.display_title or removed.file_name or removed.relative_path
        return PlaybackResult(ok=True, message=f"Removed from queue: {title}")

    async def handle_track_end(self, event: object) -> None:
        reason_obj = getattr(event, "reason", "")
        reason = getattr(reason_obj, "value", str(reason_obj))
        if reason != "finished":
            return

        player = getattr(event, "player", None)
        guild = getattr(player, "guild", None)
        if guild is None:
            return

        state = self.bot.player_states.get(guild.id)
        if state is None or state.current_track is None:
            return

        if state.loop_current:
            track = state.current_track
            state.current_track = None
        else:
            track = state.pop_next()

        if track is None:
            state.clear_current_track()
            return

        await self.play_track_on_player(guild=guild, player=player, track=track)

    async def change_volume(self, guild: discord.Guild, delta: int) -> PlaybackResult:
        state = self.bot.player_states.get_or_create(guild.id)
        if not state.has_track:
            state.set_volume(self._load_saved_volume(guild.id))

        volume = state.change_volume(delta)
        self._save_guild_volume(guild.id, volume)
        player = self._active_player(guild)
        if player is None or not hasattr(player, "set_volume"):
            return PlaybackResult(ok=True, message=f"Volume saved: {volume}%")

        try:
            await self._apply_volume(player, volume)
        except Exception as exc:  # noqa: BLE001 - controls should report clean failures.
            return PlaybackResult(
                ok=False,
                message=f"Could not change volume: {exc.__class__.__name__}.",
            )

        return PlaybackResult(ok=True, message=f"Volume saved: {volume}%")

    async def set_volume(self, guild: discord.Guild, volume: int) -> PlaybackResult:
        state = self.bot.player_states.get_or_create(guild.id)
        saved_volume = self._save_guild_volume(guild.id, volume)
        state.set_volume(saved_volume)

        player = self._active_player(guild)
        if player is not None and hasattr(player, "set_volume"):
            try:
                await self._apply_volume(player, saved_volume)
            except Exception as exc:  # noqa: BLE001 - controls should report clean failures.
                return PlaybackResult(
                    ok=False,
                    message=f"Volume saved but could not apply now: {exc.__class__.__name__}.",
                )

        return PlaybackResult(ok=True, message=f"Volume saved: {saved_volume}%")

    def toggle_loop(self, guild_id: int) -> PlaybackResult:
        state = self.bot.player_states.get(guild_id)
        if state is None or not state.has_track:
            return PlaybackResult(ok=False, message="Nothing is playing.")

        enabled = state.toggle_loop()
        message = "Loop current track: on." if enabled else "Loop current track: off."
        return PlaybackResult(ok=True, message=message)

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

    def current_state(self, guild_id: int) -> GuildPlayerState | None:
        state = self.bot.player_states.get(guild_id)
        if state is None or not state.has_track:
            return None
        return state

    def _active_state(self, guild: discord.Guild) -> GuildPlayerState | None:
        return self.current_state(guild.id)

    def _active_player(self, guild: discord.Guild) -> object | None:
        return guild.voice_client

    async def _apply_volume(self, player: object, volume: int) -> None:
        if hasattr(player, "set_volume"):
            await cast(Any, player).set_volume(volume)

    def _load_saved_volume(self, guild_id: int) -> int:
        settings = GuildSettingsRepository(self.bot.database).ensure(guild_id)
        volume = settings.default_volume
        return clamp_volume(DEFAULT_VOLUME if volume is None else volume)

    def _save_guild_volume(self, guild_id: int, volume: int) -> int:
        repository = GuildSettingsRepository(self.bot.database)
        settings = repository.ensure(guild_id)
        clamped = clamp_volume(volume)
        repository.save(
            GuildSettings(
                guild_id=settings.guild_id,
                command_prefix=settings.command_prefix,
                locale=settings.locale,
                dj_role_id=settings.dj_role_id,
                default_volume=clamped,
            )
        )
        return clamped


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
