from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

import discord

from weasel_bot_v2.models import RatingCounts, Track
from weasel_bot_v2.repositories import RatingRepository, UserRepository
from weasel_bot_v2.services.audio import AudioPlaybackService, PlaybackResult
from weasel_bot_v2.services.player_state import VOLUME_STEP, GuildPlayerState
from weasel_bot_v2.services.ratings import RatingService

LOGGER = logging.getLogger(__name__)

@dataclass
class NowPlayingPanelRecord:
    guild_id: int
    channel_id: int
    message_id: int
    view: discord.ui.View | None = None


class NowPlayingPanelRegistry:
    def __init__(self) -> None:
        self._records: dict[int, NowPlayingPanelRecord] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def get(self, guild_id: int) -> NowPlayingPanelRecord | None:
        return self._records.get(guild_id)

    def set(self, record: NowPlayingPanelRecord) -> NowPlayingPanelRecord:
        self._records[record.guild_id] = record
        return record

    def clear(self, guild_id: int) -> None:
        self._records.pop(guild_id, None)

    def lock_for(self, guild_id: int) -> asyncio.Lock:
        lock = self._locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[guild_id] = lock
        return lock


@dataclass(frozen=True)
class NowPlayingSnapshot:
    guild_id: int
    has_track: bool
    title: str
    artist: str | None
    category: str | None
    status: str
    volume: int
    loop_enabled: bool
    queue_length: int
    next_title: str | None
    previous_available: bool
    rating_counts: RatingCounts
    relative_path: str | None
    lavalink_available: bool
    player_connected: bool


class NowPlayingPanelService:
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.registry: NowPlayingPanelRegistry = bot.now_playing_panels

    def lock_for(self, guild_id: int) -> asyncio.Lock:
        return self.registry.lock_for(guild_id)

    def snapshot_for(self, guild: discord.Guild) -> NowPlayingSnapshot:
        state = self.bot.player_states.get(guild.id)
        rating_counts = self._rating_counts(state)
        track = state.current_track if state is not None else None
        return NowPlayingSnapshot(
            guild_id=guild.id,
            has_track=track is not None,
            title=track_title(track) if track is not None else "Nothing playing",
            artist=track.artist_guess if track is not None else None,
            category=track.category_guess if track is not None else None,
            status=self._status_for(state),
            volume=state.volume if state is not None else 100,
            loop_enabled=state.loop_current if state is not None else False,
            queue_length=state.queue_length if state is not None else 0,
            next_title=track_title(state.next_track_preview())
            if state is not None and state.next_track_preview() is not None
            else None,
            previous_available=state.can_go_back if state is not None else False,
            rating_counts=rating_counts,
            relative_path=track.relative_path if track is not None else None,
            lavalink_available=bool(getattr(self.bot, "lavalink_available", False)),
            player_connected=getattr(guild, "voice_client", None) is not None,
        )

    async def refresh(
        self,
        *,
        guild: discord.Guild,
        channel: discord.abc.Messageable | None = None,
        reason: str,
    ) -> NowPlayingPanelRecord | None:
        async with self.lock_for(guild.id):
            return await self.refresh_locked(guild=guild, channel=channel, reason=reason)

    async def refresh_locked(
        self,
        *,
        guild: discord.Guild,
        channel: discord.abc.Messageable | None = None,
        reason: str,
    ) -> NowPlayingPanelRecord | None:
        snapshot = self.snapshot_for(guild)
        record = self.registry.get(guild.id)
        if channel is None and record is not None:
            channel = self._channel_for_record(record)

        if record is not None and channel is not None:
            edited = await self._try_edit_existing(
                record=record,
                channel=channel,
                snapshot=snapshot,
                reason=reason,
            )
            if edited is not None:
                return edited

        if channel is None or not hasattr(channel, "send") or not snapshot.has_track:
            return None

        return await self._create_panel(
            guild_id=guild.id,
            channel=channel,
            snapshot=snapshot,
            reason=reason,
        )

    async def disable_stale_interaction_panel(
        self,
        interaction: discord.Interaction,
    ) -> None:
        guild = interaction.guild
        message = getattr(interaction, "message", None)
        if guild is None or message is None:
            return

        record = self.registry.get(guild.id)
        if record is None or getattr(message, "id", None) == record.message_id:
            return

        try:
            await cast(Any, message).edit(view=DisabledNowPlayingView())
        except Exception as exc:  # noqa: BLE001 - stale panel cleanup is best effort.
            LOGGER.info(
                "Could not disable stale panel guild_id=%s channel_id=%s message_id=%s "
                "error=%s",
                guild.id,
                getattr(getattr(message, "channel", None), "id", "unknown"),
                getattr(message, "id", "unknown"),
                exc.__class__.__name__,
            )

    async def run_button_action(
        self,
        interaction: discord.Interaction,
        action: Callable[[discord.Guild], Awaitable[PlaybackResult] | PlaybackResult],
        *,
        reason: str,
        success_message: bool = False,
    ) -> None:
        await acknowledge_interaction(interaction)
        guild = interaction.guild
        if guild is None:
            await send_ephemeral_once(interaction, "This control can only be used in a server.")
            return

        async with self.lock_for(guild.id):
            await self.disable_stale_interaction_panel(interaction)
            result_or_awaitable = action(guild)
            result = (
                await result_or_awaitable
                if inspect.isawaitable(result_or_awaitable)
                else result_or_awaitable
            )
            await self.refresh_locked(
                guild=guild,
                channel=cast(discord.abc.Messageable | None, interaction.channel),
                reason=reason,
            )

        if (not result.ok) or success_message:
            await send_ephemeral_once(interaction, result.message)

    async def run_rating_action(self, interaction: discord.Interaction, rating_value: str) -> None:
        await acknowledge_interaction(interaction)
        guild = interaction.guild
        if guild is None:
            await send_ephemeral_once(interaction, "This control can only be used in a server.")
            return

        async with self.lock_for(guild.id):
            await self.disable_stale_interaction_panel(interaction)
            state = self.bot.player_states.get(guild.id)
            result = self._rating_service().rate_current_track(
                state=state,
                user_id=interaction.user.id,
                display_name=interaction.user.display_name,
                rating_value=rating_value,
            )
            await self.refresh_locked(
                guild=guild,
                channel=cast(discord.abc.Messageable | None, interaction.channel),
                reason=f"rating:{rating_value}",
            )

        await send_ephemeral_once(interaction, result.message)

    async def _try_edit_existing(
        self,
        *,
        record: NowPlayingPanelRecord,
        channel: discord.abc.Messageable,
        snapshot: NowPlayingSnapshot,
        reason: str,
    ) -> NowPlayingPanelRecord | None:
        try:
            message = await self._fetch_message(channel, record.message_id)
            view = NowPlayingView(self.bot, snapshot)
            await message.edit(embed=build_now_playing_embed(snapshot), view=view)
        except discord.NotFound:
            LOGGER.info(
                "Now Playing panel missing; recreating guild_id=%s channel_id=%s "
                "message_id=%s reason=%s",
                record.guild_id,
                record.channel_id,
                record.message_id,
                reason,
            )
            self.registry.clear(record.guild_id)
            return None
        except discord.Forbidden as exc:
            LOGGER.warning(
                "Now Playing panel edit forbidden guild_id=%s channel_id=%s message_id=%s "
                "reason=%s error=%s",
                record.guild_id,
                record.channel_id,
                record.message_id,
                reason,
                exc.__class__.__name__,
            )
            return record
        except Exception as exc:  # noqa: BLE001 - refresh must not crash playback.
            LOGGER.warning(
                "Now Playing panel edit failed guild_id=%s channel_id=%s message_id=%s "
                "reason=%s error=%s",
                record.guild_id,
                record.channel_id,
                record.message_id,
                reason,
                exc.__class__.__name__,
            )
            return record

        updated = NowPlayingPanelRecord(
            guild_id=record.guild_id,
            channel_id=record.channel_id,
            message_id=record.message_id,
            view=view,
        )
        return self.registry.set(updated)

    async def _create_panel(
        self,
        *,
        guild_id: int,
        channel: discord.abc.Messageable,
        snapshot: NowPlayingSnapshot,
        reason: str,
    ) -> NowPlayingPanelRecord | None:
        try:
            view = NowPlayingView(self.bot, snapshot)
            message = await cast(Any, channel).send(
                embed=build_now_playing_embed(snapshot),
                view=view,
            )
        except discord.Forbidden as exc:
            LOGGER.warning(
                "Now Playing panel create forbidden guild_id=%s channel_id=%s reason=%s "
                "error=%s",
                guild_id,
                getattr(channel, "id", "unknown"),
                reason,
                exc.__class__.__name__,
            )
            return None
        except Exception as exc:  # noqa: BLE001 - refresh must not crash playback.
            LOGGER.warning(
                "Now Playing panel create failed guild_id=%s channel_id=%s reason=%s error=%s",
                guild_id,
                getattr(channel, "id", "unknown"),
                reason,
                exc.__class__.__name__,
            )
            return None

        record = NowPlayingPanelRecord(
            guild_id=guild_id,
            channel_id=int(getattr(channel, "id", 0)),
            message_id=int(message.id),
            view=view,
        )
        return self.registry.set(record)

    async def _fetch_message(self, channel: discord.abc.Messageable, message_id: int) -> Any:
        if hasattr(channel, "fetch_message"):
            return await cast(Any, channel).fetch_message(message_id)
        raise discord.NotFound(response=cast(Any, None), message="Channel cannot fetch messages.")

    def _channel_for_record(
        self,
        record: NowPlayingPanelRecord,
    ) -> discord.abc.Messageable | None:
        channel = self.bot.get_channel(record.channel_id)
        return cast(discord.abc.Messageable | None, channel)

    def _rating_service(self) -> RatingService:
        return RatingService(
            ratings=RatingRepository(self.bot.database),
            users=UserRepository(self.bot.database),
        )

    def _rating_counts(self, state: GuildPlayerState | None) -> RatingCounts:
        try:
            return self._rating_service().counts_for_current_track(state)
        except Exception as exc:  # noqa: BLE001 - panel should survive database issues.
            LOGGER.warning(
                "Could not read Now Playing rating counts guild_id=%s error=%s",
                state.guild_id if state is not None else "unknown",
                exc.__class__.__name__,
            )
            return RatingCounts()

    def _status_for(self, state: GuildPlayerState | None) -> str:
        if state is None or state.current_track is None:
            return "Stopped"
        return "Paused" if state.paused else "Playing"


class NowPlayingView(discord.ui.View):
    def __init__(self, bot: Any, snapshot: NowPlayingSnapshot) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = snapshot.guild_id
        self._update_button_state(snapshot)

    @discord.ui.button(
        label="Back",
        emoji="⏮️",
        style=discord.ButtonStyle.secondary,
        row=0,
        custom_id="weasel:now_playing:back",
    )
    async def back_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        service = NowPlayingPanelService(self.bot)
        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        await service.run_button_action(
            interaction,
            playback.back,
            reason="button:back",
            success_message=False,
        )

    @discord.ui.button(
        label="Pause / Resume",
        emoji="⏯️",
        style=discord.ButtonStyle.primary,
        row=0,
        custom_id="weasel:now_playing:pause_resume",
    )
    async def pause_resume(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        service = NowPlayingPanelService(self.bot)
        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)

        def action(guild: discord.Guild) -> Awaitable[PlaybackResult]:
            state = self.bot.player_states.get(guild.id)
            if state is not None and state.paused:
                return playback.resume(guild)
            return playback.pause(guild)

        await service.run_button_action(
            interaction,
            action,
            reason="button:pause_resume",
            success_message=False,
        )

    @discord.ui.button(
        label="Skip",
        emoji="⏭️",
        style=discord.ButtonStyle.secondary,
        row=0,
        custom_id="weasel:now_playing:skip",
    )
    async def skip_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        service = NowPlayingPanelService(self.bot)
        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        await service.run_button_action(
            interaction,
            playback.skip,
            reason="button:skip",
            success_message=False,
        )

    @discord.ui.button(
        label="Stop",
        emoji="⏹️",
        style=discord.ButtonStyle.danger,
        row=0,
        custom_id="weasel:now_playing:stop",
    )
    async def stop_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        service = NowPlayingPanelService(self.bot)
        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        await service.run_button_action(
            interaction,
            playback.stop,
            reason="button:stop",
            success_message=False,
        )

    @discord.ui.button(
        label="Loop",
        emoji="🔁",
        style=discord.ButtonStyle.secondary,
        row=0,
        custom_id="weasel:now_playing:loop",
    )
    async def loop_current(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        service = NowPlayingPanelService(self.bot)
        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        await service.run_button_action(
            interaction,
            lambda guild: playback.toggle_loop(guild.id),
            reason="button:loop",
            success_message=True,
        )

    @discord.ui.button(
        label="Volume Down",
        emoji="🔉",
        style=discord.ButtonStyle.secondary,
        row=1,
        custom_id="weasel:now_playing:volume_down",
    )
    async def volume_down(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        await self._volume(interaction, -VOLUME_STEP)

    @discord.ui.button(
        label="Volume Up",
        emoji="🔊",
        style=discord.ButtonStyle.secondary,
        row=1,
        custom_id="weasel:now_playing:volume_up",
    )
    async def volume_up(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        await self._volume(interaction, VOLUME_STEP)

    @discord.ui.button(
        label="Like",
        emoji="❤️",
        style=discord.ButtonStyle.success,
        row=1,
        custom_id="weasel:now_playing:like",
    )
    async def like_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        await NowPlayingPanelService(self.bot).run_rating_action(interaction, "like")

    @discord.ui.button(
        label="SuperLike",
        emoji="💎",
        style=discord.ButtonStyle.success,
        row=1,
        custom_id="weasel:now_playing:superlike",
    )
    async def superlike_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        await NowPlayingPanelService(self.bot).run_rating_action(interaction, "superlike")

    @discord.ui.button(
        label="Dislike",
        emoji="👎",
        style=discord.ButtonStyle.secondary,
        row=2,
        custom_id="weasel:now_playing:dislike",
    )
    async def dislike_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        await NowPlayingPanelService(self.bot).run_rating_action(interaction, "dislike")

    @discord.ui.button(
        label="SuperDislike",
        emoji="💀",
        style=discord.ButtonStyle.danger,
        row=2,
        custom_id="weasel:now_playing:superdislike",
    )
    async def superdislike_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        await NowPlayingPanelService(self.bot).run_rating_action(interaction, "superdislike")

    async def _volume(self, interaction: discord.Interaction, delta: int) -> None:
        service = NowPlayingPanelService(self.bot)
        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        await service.run_button_action(
            interaction,
            lambda guild: playback.change_volume(guild, delta),
            reason="button:volume",
            success_message=True,
        )

    def _update_button_state(self, snapshot: NowPlayingSnapshot) -> None:
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            item.disabled = not snapshot.has_track
            if item.custom_id == "weasel:now_playing:back":
                item.disabled = not snapshot.previous_available or not snapshot.has_track
            if item.custom_id == "weasel:now_playing:skip":
                item.disabled = not snapshot.has_track
            if item.custom_id == "weasel:now_playing:pause_resume":
                item.label = "Resume" if snapshot.status == "Paused" else "Pause"
            if item.custom_id == "weasel:now_playing:loop":
                item.style = (
                    discord.ButtonStyle.success
                    if snapshot.loop_enabled
                    else discord.ButtonStyle.secondary
                )


class DisabledNowPlayingView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        button = discord.ui.Button(
            label="Stale Panel",
            emoji="🔒",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            custom_id="weasel:now_playing:stale",
        )
        self.add_item(button)


def build_now_playing_embed(snapshot: NowPlayingSnapshot) -> discord.Embed:
    color = discord.Color.green() if snapshot.has_track else discord.Color.dark_grey()
    embed = discord.Embed(
        title="Now Playing",
        description=f"**{snapshot.title}**",
        color=color,
    )
    if snapshot.artist:
        embed.add_field(name="Artist", value=snapshot.artist, inline=True)
    if snapshot.category:
        embed.add_field(name="Category", value=snapshot.category, inline=True)
    embed.add_field(name="Status", value=snapshot.status, inline=True)
    embed.add_field(name="Volume", value=f"{snapshot.volume}%", inline=True)
    loop_value = "On (experimental)" if snapshot.loop_enabled else "Off"
    embed.add_field(name="Loop", value=loop_value, inline=True)
    embed.add_field(name="Queue", value=f"{snapshot.queue_length} upcoming", inline=True)
    embed.add_field(name="Next", value=snapshot.next_title or "Nothing queued", inline=False)
    embed.add_field(
        name="Previous",
        value="Available" if snapshot.previous_available else "None",
        inline=True,
    )
    embed.add_field(
        name="Ratings",
        value=(
            f"❤️ {snapshot.rating_counts.like}  "
            f"💎 {snapshot.rating_counts.superlike}  "
            f"👎 {snapshot.rating_counts.dislike}  "
            f"💀 {snapshot.rating_counts.superdislike}"
        ),
        inline=False,
    )
    connection = "Connected" if snapshot.player_connected else "Not connected"
    lavalink = "Lavalink ready" if snapshot.lavalink_available else "Lavalink unavailable"
    embed.add_field(name="Player", value=f"{connection} / {lavalink}", inline=False)
    if snapshot.relative_path:
        embed.set_footer(text=snapshot.relative_path)
    else:
        embed.set_footer(text="Panel persistence across bot restarts is not guaranteed.")
    return embed


def format_queue(state: GuildPlayerState | None, *, limit: int = 10) -> str:
    if state is None or (not state.has_track and state.queue_length == 0):
        return "Nothing is playing and the queue is empty."

    lines = [f"Now playing: {track_title(state.current_track)}"]
    if not state.upcoming:
        lines.append("Queue is empty.")
        return "\n".join(lines)

    lines.append("Upcoming:")
    for index, track in enumerate(state.upcoming[:limit], start=1):
        lines.append(f"{index}. {track_title(track)}")
    remaining = len(state.upcoming) - limit
    if remaining > 0:
        lines.append(f"...and {remaining} more.")
    return "\n".join(lines)


def track_title(track: Track | object | None) -> str:
    if track is None:
        return "None"
    local_track = cast(Any, track)
    return (
        local_track.display_title
        or local_track.file_name
        or local_track.relative_path
        or "Unknown local track"
    )


async def acknowledge_interaction(interaction: discord.Interaction) -> None:
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    except discord.InteractionResponded:
        return


async def send_ephemeral_once(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
        return

    try:
        await interaction.response.send_message(message, ephemeral=True)
    except discord.InteractionResponded:
        await interaction.followup.send(message, ephemeral=True)
