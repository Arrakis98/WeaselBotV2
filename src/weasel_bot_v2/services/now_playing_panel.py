from __future__ import annotations

import asyncio
import inspect
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, cast

import discord

from weasel_bot_v2.models import RatingCounts, Track
from weasel_bot_v2.repositories import RatingRepository, UserRepository
from weasel_bot_v2.services.audio import AudioPlaybackService, PlaybackResult
from weasel_bot_v2.services.player_actions import PlayerActionService
from weasel_bot_v2.services.player_state import VOLUME_STEP, GuildPlayerState
from weasel_bot_v2.services.ratings import RatingService

LOGGER = logging.getLogger(__name__)

WEASEL_GALAXY_ACCENT = 0xC026D3
UNKNOWN_ARTIST = "Divers"
QUEUE_PREVIEW_LIMIT = 10


class PanelRenderMode(StrEnum):
    COMPONENTS_V2 = "components_v2"
    LEGACY_EMBED = "legacy_embed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ComponentsV2Support:
    supported: bool
    discord_version: str
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class PanelArtwork:
    """Optional future hook for mascot art or animated media.

    No asset is configured by default. The URL can later point at a free
    self-hosted file, a Discord attachment reference, or another safe source.
    """

    thumbnail_url: str | None = None
    description: str = "Weasel Galaxy artwork"


@dataclass
class NowPlayingPanelRecord:
    guild_id: int
    channel_id: int
    message_id: int
    view: Any | None = None
    render_mode: PanelRenderMode = PanelRenderMode.UNKNOWN


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
class TrackDisplay:
    title: str
    artist: str
    category: str | None = None
    extension: str | None = None

    @property
    def metadata_line(self) -> str:
        if self.category:
            return f"{self.artist} • {self.category}"
        return self.artist


@dataclass(frozen=True)
class QueuePreview:
    current: str
    upcoming: tuple[str, ...]
    total_remaining: int

    @property
    def hidden_count(self) -> int:
        return max(0, self.total_remaining - len(self.upcoming))


@dataclass(frozen=True)
class NowPlayingSnapshot:
    guild_id: int
    has_track: bool
    title: str
    artist: str | None
    category: str | None
    status: str
    volume: int
    volume_source_label: str
    loop_enabled: bool
    queue_length: int
    next_title: str | None
    previous_available: bool
    rating_counts: RatingCounts
    relative_path: str | None
    lavalink_available: bool
    player_connected: bool
    track_display: TrackDisplay
    queue_preview: QueuePreview
    artwork: PanelArtwork | None = None


@dataclass(frozen=True)
class PanelPayload:
    view: Any
    embed: discord.Embed | None
    mode: PanelRenderMode


class PanelRenderer(Protocol):
    mode: PanelRenderMode

    def render(self, bot: Any, snapshot: NowPlayingSnapshot) -> PanelPayload:
        ...


@dataclass(frozen=True)
class ControlSpec:
    key: str
    custom_id: str
    emoji: str | None
    label: str | None
    row: int
    style: discord.ButtonStyle


PLAYER_CONTROL_SPECS: tuple[ControlSpec, ...] = (
    ControlSpec(
        "previous",
        "weasel:now_playing:back",
        "⏮️",
        None,
        0,
        discord.ButtonStyle.secondary,
    ),
    ControlSpec(
        "pause_resume",
        "weasel:now_playing:pause_resume",
        "⏯️",
        None,
        0,
        discord.ButtonStyle.primary,
    ),
    ControlSpec("next", "weasel:now_playing:skip", "⏭️", None, 0, discord.ButtonStyle.secondary),
    ControlSpec("stop", "weasel:now_playing:stop", "⏹️", None, 0, discord.ButtonStyle.danger),
    ControlSpec("loop", "weasel:now_playing:loop", "🔁", None, 0, discord.ButtonStyle.secondary),
    ControlSpec(
        "volume_down",
        "weasel:now_playing:volume_down",
        "🔉",
        "−",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlSpec(
        "volume_up",
        "weasel:now_playing:volume_up",
        "🔊",
        "+",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlSpec("queue", "weasel:now_playing:queue", "📜", None, 1, discord.ButtonStyle.secondary),
    ControlSpec(
        "shuffle",
        "weasel:now_playing:shuffle",
        "🔀",
        None,
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlSpec("more", "weasel:now_playing:more", None, "⋯", 1, discord.ButtonStyle.secondary),
    ControlSpec("like", "weasel:now_playing:like", "❤️", None, 2, discord.ButtonStyle.success),
    ControlSpec(
        "superlike",
        "weasel:now_playing:superlike",
        "💎",
        None,
        2,
        discord.ButtonStyle.success,
    ),
    ControlSpec(
        "dislike",
        "weasel:now_playing:dislike",
        "👎",
        None,
        2,
        discord.ButtonStyle.secondary,
    ),
    ControlSpec(
        "superdislike",
        "weasel:now_playing:superdislike",
        "💀",
        None,
        2,
        discord.ButtonStyle.danger,
    ),
)


MORE_ACTION_OPTIONS: tuple[discord.SelectOption, ...] = (
    discord.SelectOption(
        label="Show queue",
        value="show_queue",
        description="Open a concise private queue preview.",
        emoji="📜",
    ),
    discord.SelectOption(
        label="Track information",
        value="track_info",
        description="Show current track metadata and rating totals.",
        emoji="ℹ️",
    ),
    discord.SelectOption(
        label="Same artist",
        value="same_artist_disabled",
        description="Future option; not implemented yet.",
        emoji="🎙️",
    ),
    discord.SelectOption(
        label="Same category",
        value="same_category_disabled",
        description="Future option; not implemented yet.",
        emoji="🗂️",
    ),
    discord.SelectOption(
        label="Add to playlist",
        value="add_to_playlist_disabled",
        description="Future option; not implemented yet.",
        emoji="➕",
    ),
    discord.SelectOption(
        label="Start similar radio",
        value="similar_radio_disabled",
        description="Future option; not implemented yet.",
        emoji="📡",
    ),
)


def detect_components_v2_support() -> ComponentsV2Support:
    required = (
        "LayoutView",
        "Container",
        "Section",
        "TextDisplay",
        "Thumbnail",
        "Separator",
        "ActionRow",
        "Button",
        "Select",
    )
    missing = tuple(name for name in required if getattr(discord.ui, name, None) is None)
    return ComponentsV2Support(
        supported=not missing,
        discord_version=discord.__version__,
        missing=missing,
    )


def detect_message_render_mode(message: Any, record: NowPlayingPanelRecord) -> PanelRenderMode:
    flags = getattr(message, "flags", None)
    if bool(getattr(flags, "components_v2", False)):
        return PanelRenderMode.COMPONENTS_V2
    if isinstance(record.view, discord.ui.LayoutView):
        return PanelRenderMode.COMPONENTS_V2
    if isinstance(record.view, discord.ui.View):
        return PanelRenderMode.LEGACY_EMBED
    return record.render_mode


def log_panel_event(
    level: int,
    *,
    operation: str,
    renderer: PanelRenderMode,
    guild_id: int,
    channel_id: object,
    message_id: object,
    reason: str,
    exc: BaseException | None,
) -> None:
    status = getattr(exc, "status", None) if exc is not None else None
    code = getattr(exc, "code", None) if exc is not None else None
    error = exc.__class__.__name__ if exc is not None else None
    exception_text = truncate_diagnostic(str(exc), limit=500) if exc is not None else None
    response_text = truncate_diagnostic(getattr(exc, "text", None), limit=500)
    LOGGER.log(
        level,
        "Now Playing panel operation=%s renderer=%s guild_id=%s channel_id=%s "
        "message_id=%s reason=%s error=%s status=%s code=%s exception=%s response_text=%s",
        operation,
        renderer.value,
        guild_id,
        channel_id,
        message_id,
        reason,
        error,
        status,
        code,
        exception_text,
        response_text,
    )


def truncate_diagnostic(value: object | None, *, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def select_panel_renderer(*, prefer_components_v2: bool = True) -> PanelRenderer:
    if prefer_components_v2 and detect_components_v2_support().supported:
        return ComponentsV2PanelRenderer()
    return LegacyEmbedPanelRenderer()


def build_components_v2_canary_view() -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_color=discord.Color(WEASEL_GALAXY_ACCENT))
    container.add_item(discord.ui.TextDisplay("WEASEL GALAXY"))
    container.add_item(
        discord.ui.ActionRow(
            discord.ui.Button(
                emoji="⏯️",
                custom_id="weasel:now_playing:canary",
                style=discord.ButtonStyle.secondary,
            )
        )
    )
    view.add_item(container)
    return view


class ComponentsV2PanelRenderer:
    mode = PanelRenderMode.COMPONENTS_V2

    def render(self, bot: Any, snapshot: NowPlayingSnapshot) -> PanelPayload:
        view = NowPlayingComponentsV2View(bot, snapshot)
        container = discord.ui.Container(accent_color=discord.Color(WEASEL_GALAXY_ACCENT))
        container.add_item(discord.ui.TextDisplay("### WEASEL GALAXY\nNow Playing"))
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))

        main_text = (
            f"## {snapshot.track_display.title}\n"
            f"{snapshot.track_display.metadata_line}\n\n"
            f"{snapshot.status} • {snapshot.volume}% • "
            f"{snapshot.volume_source_label} • {snapshot.queue_length} queued\n"
            f"Next: {snapshot.next_title or 'Nothing queued'}"
        )
        if snapshot.loop_enabled:
            main_text = f"{main_text}\nLoop: experimental"

        if snapshot.artwork and snapshot.artwork.thumbnail_url:
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(main_text),
                    accessory=discord.ui.Thumbnail(
                        snapshot.artwork.thumbnail_url,
                        description=snapshot.artwork.description,
                    ),
                )
            )
        else:
            container.add_item(discord.ui.TextDisplay(main_text))

        container.add_item(
            discord.ui.TextDisplay(
                "❤️ "
                f"{snapshot.rating_counts.like}   "
                "💎 "
                f"{snapshot.rating_counts.superlike}   "
                "👎 "
                f"{snapshot.rating_counts.dislike}   "
                "💀 "
                f"{snapshot.rating_counts.superdislike}"
            )
        )
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        for row_index in range(3):
            row_items = [
                build_control_button(spec, snapshot)
                for spec in PLAYER_CONTROL_SPECS
                if spec.row == row_index
            ]
            container.add_item(discord.ui.ActionRow(*row_items))

        view.add_item(container)
        return PanelPayload(view=view, embed=None, mode=self.mode)


class LegacyEmbedPanelRenderer:
    mode = PanelRenderMode.LEGACY_EMBED

    def render(self, bot: Any, snapshot: NowPlayingSnapshot) -> PanelPayload:
        return PanelPayload(
            view=NowPlayingLegacyView(bot, snapshot),
            embed=build_now_playing_embed(snapshot),
            mode=self.mode,
        )


class NowPlayingPanelService:
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.registry: NowPlayingPanelRegistry = bot.now_playing_panels
        self.renderer: PanelRenderer = select_panel_renderer()
        self.legacy_renderer = LegacyEmbedPanelRenderer()

    def lock_for(self, guild_id: int) -> asyncio.Lock:
        return self.registry.lock_for(guild_id)

    def snapshot_for(self, guild: discord.Guild) -> NowPlayingSnapshot:
        state = self.bot.player_states.get(guild.id)
        rating_counts = self._rating_counts(state)
        track = state.current_track if state is not None else None
        track_display = track_display_for(track)
        queue_preview = queue_preview_for(state)
        next_track = state.next_track_preview() if state is not None else None
        resolved_volume = AudioPlaybackService(
            self.bot,
            self.bot.settings.bot.music_library,
        ).resolve_effective_volume(guild.id, track)
        return NowPlayingSnapshot(
            guild_id=guild.id,
            has_track=track is not None,
            title=track_display.title,
            artist=None if track is None else track.artist_guess,
            category=track_display.category,
            status=self._status_for(state),
            volume=resolved_volume.volume,
            volume_source_label=resolved_volume.source_label,
            loop_enabled=state.loop_current if state is not None else False,
            queue_length=state.queue_length if state is not None else 0,
            next_title=track_title(next_track) if next_track is not None else None,
            previous_available=state.can_go_back if state is not None else False,
            rating_counts=rating_counts,
            relative_path=track.relative_path if track is not None else None,
            lavalink_available=bool(getattr(self.bot, "lavalink_available", False)),
            player_connected=getattr(guild, "voice_client", None) is not None,
            track_display=track_display,
            queue_preview=queue_preview,
            artwork=panel_artwork_for_bot(self.bot),
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
            result = await PlayerActionService(self.bot).rate_current_track(
                guild=guild,
                user_id=interaction.user.id,
                display_name=interaction.user.display_name,
                rating_value=rating_value,
            )
            if result.ok:
                await self.refresh_locked(
                    guild=guild,
                    channel=cast(discord.abc.Messageable | None, interaction.channel),
                    reason=f"rating:{rating_value}",
                )

        await send_ephemeral_once(interaction, result.message)

    async def show_queue(self, interaction: discord.Interaction) -> None:
        await acknowledge_interaction(interaction)
        guild = interaction.guild
        state = self.bot.player_states.get(guild.id) if guild is not None else None
        await send_ephemeral_once(interaction, format_queue(state))

    async def shuffle_queue(self, interaction: discord.Interaction) -> None:
        await acknowledge_interaction(interaction)
        guild = interaction.guild
        if guild is None:
            await send_ephemeral_once(interaction, "This control can only be used in a server.")
            return

        async with self.lock_for(guild.id):
            state = self.bot.player_states.get(guild.id)
            result = shuffle_upcoming_queue(state)
            await self.refresh_locked(
                guild=guild,
                channel=cast(discord.abc.Messageable | None, interaction.channel),
                reason="button:shuffle",
            )

        await send_ephemeral_once(interaction, result.message)

    async def show_more_actions(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        snapshot = self.snapshot_for(guild) if guild is not None else None
        view = MoreActionsView(self.bot, snapshot)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Choose an action.",
                    view=view,
                    ephemeral=True,
                )
                return
        except discord.InteractionResponded:
            pass
        await interaction.followup.send("Choose an action.", view=view, ephemeral=True)

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
            current_mode = detect_message_render_mode(message, record)
            payload = self.renderer.render(self.bot, snapshot)
            await self._edit_message(message, payload, current_mode=current_mode)
        except discord.NotFound:
            log_panel_event(
                logging.INFO,
                operation="recreate",
                renderer=PanelRenderMode.UNKNOWN,
                guild_id=record.guild_id,
                channel_id=record.channel_id,
                message_id=record.message_id,
                reason=reason,
                exc=None,
            )
            self.registry.clear(record.guild_id)
            return None
        except discord.Forbidden as exc:
            log_panel_event(
                logging.WARNING,
                operation="edit",
                renderer=getattr(self.renderer, "mode", PanelRenderMode.UNKNOWN),
                guild_id=record.guild_id,
                channel_id=record.channel_id,
                message_id=record.message_id,
                reason=reason,
                exc=exc,
            )
            return record
        except Exception as exc:  # noqa: BLE001 - refresh must not crash playback.
            log_panel_event(
                logging.WARNING,
                operation="edit",
                renderer=getattr(self.renderer, "mode", PanelRenderMode.UNKNOWN),
                guild_id=record.guild_id,
                channel_id=record.channel_id,
                message_id=record.message_id,
                reason=reason,
                exc=exc,
            )
            try:
                message = await self._fetch_message(channel, record.message_id)
                current_mode = detect_message_render_mode(message, record)
                payload = self.legacy_renderer.render(self.bot, snapshot)
                if current_mode is PanelRenderMode.LEGACY_EMBED:
                    await self._edit_message(message, payload, current_mode=current_mode)
                else:
                    await self._disable_or_delete_broken_message(message, record, reason=reason)
                    return await self._create_panel_with_renderer(
                        guild_id=record.guild_id,
                        channel=channel,
                        snapshot=snapshot,
                        reason=reason,
                        renderer=self.legacy_renderer,
                        operation="fallback",
                    )
            except Exception as fallback_exc:  # noqa: BLE001 - panel must not crash playback.
                log_panel_event(
                    logging.WARNING,
                    operation="fallback",
                    renderer=PanelRenderMode.LEGACY_EMBED,
                    guild_id=record.guild_id,
                    channel_id=record.channel_id,
                    message_id=record.message_id,
                    reason=reason,
                    exc=fallback_exc,
                )
                return record

        updated = NowPlayingPanelRecord(
            guild_id=record.guild_id,
            channel_id=record.channel_id,
            message_id=record.message_id,
            view=payload.view,
            render_mode=payload.mode,
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
        return await self._create_panel_with_renderer(
            guild_id=guild_id,
            channel=channel,
            snapshot=snapshot,
            reason=reason,
            renderer=self.renderer,
            operation="create",
        )

    async def _create_panel_with_renderer(
        self,
        *,
        guild_id: int,
        channel: discord.abc.Messageable,
        snapshot: NowPlayingSnapshot,
        reason: str,
        renderer: PanelRenderer,
        operation: str,
    ) -> NowPlayingPanelRecord | None:
        try:
            payload = renderer.render(self.bot, snapshot)
            message = await self._send_message(channel, payload)
        except discord.Forbidden as exc:
            log_panel_event(
                logging.WARNING,
                operation=operation,
                renderer=getattr(renderer, "mode", PanelRenderMode.UNKNOWN),
                guild_id=guild_id,
                channel_id=getattr(channel, "id", "unknown"),
                message_id=None,
                reason=reason,
                exc=exc,
            )
            return None
        except Exception as exc:  # noqa: BLE001 - refresh must not crash playback.
            log_panel_event(
                logging.WARNING,
                operation=operation,
                renderer=getattr(renderer, "mode", PanelRenderMode.UNKNOWN),
                guild_id=guild_id,
                channel_id=getattr(channel, "id", "unknown"),
                message_id=None,
                reason=reason,
                exc=exc,
            )
            if getattr(renderer, "mode", PanelRenderMode.UNKNOWN) is PanelRenderMode.LEGACY_EMBED:
                return None
            try:
                payload = self.legacy_renderer.render(self.bot, snapshot)
                message = await self._send_message(channel, payload)
            except Exception as fallback_exc:  # noqa: BLE001 - panel must not crash playback.
                log_panel_event(
                    logging.WARNING,
                    operation="fallback",
                    renderer=PanelRenderMode.LEGACY_EMBED,
                    guild_id=guild_id,
                    channel_id=getattr(channel, "id", "unknown"),
                    message_id=None,
                    reason=reason,
                    exc=fallback_exc,
                )
                return None

        record = NowPlayingPanelRecord(
            guild_id=guild_id,
            channel_id=int(getattr(channel, "id", 0)),
            message_id=int(message.id),
            view=payload.view,
            render_mode=payload.mode,
        )
        return self.registry.set(record)

    async def _send_message(self, channel: discord.abc.Messageable, payload: PanelPayload) -> Any:
        if payload.embed is None:
            return await cast(Any, channel).send(view=payload.view)
        return await cast(Any, channel).send(embed=payload.embed, view=payload.view)

    async def _edit_message(
        self,
        message: Any,
        payload: PanelPayload,
        *,
        current_mode: PanelRenderMode,
    ) -> None:
        if payload.embed is None:
            await message.edit(
                content=None,
                embed=None,
                attachments=[],
                view=payload.view,
            )
            return
        if current_mode is not PanelRenderMode.LEGACY_EMBED:
            raise RuntimeError("Refusing to edit a Components V2 message back to legacy embed.")
        await message.edit(embed=payload.embed, view=payload.view)

    async def _disable_or_delete_broken_message(
        self,
        message: Any,
        record: NowPlayingPanelRecord,
        *,
        reason: str,
    ) -> None:
        try:
            if hasattr(message, "delete"):
                await message.delete()
                return
            await message.edit(view=DisabledNowPlayingView())
        except Exception as exc:  # noqa: BLE001 - cleanup is best effort.
            log_panel_event(
                logging.INFO,
                operation="fallback_cleanup",
                renderer=record.render_mode,
                guild_id=record.guild_id,
                channel_id=record.channel_id,
                message_id=record.message_id,
                reason=reason,
                exc=exc,
            )

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
            return "Idle"
        return "Paused" if state.paused else "Playing"


class NowPlayingComponentsV2View(discord.ui.LayoutView):
    def __init__(self, bot: Any, snapshot: NowPlayingSnapshot) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = snapshot.guild_id


class NowPlayingLegacyView(discord.ui.View):
    def __init__(self, bot: Any, snapshot: NowPlayingSnapshot) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = snapshot.guild_id
        for spec in PLAYER_CONTROL_SPECS:
            self.add_item(build_control_button(spec, snapshot))


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


class PanelControlButton(discord.ui.Button[Any]):
    def __init__(self, spec: ControlSpec, snapshot: NowPlayingSnapshot) -> None:
        style = (
            discord.ButtonStyle.success
            if spec.key == "loop" and snapshot.loop_enabled
            else spec.style
        )
        disabled = not snapshot.has_track
        if spec.key == "previous":
            disabled = not snapshot.previous_available or not snapshot.has_track
        if spec.key in {"queue", "more"}:
            disabled = False
        if spec.key == "shuffle":
            disabled = snapshot.queue_length <= 1
        super().__init__(
            style=style,
            label=spec.label,
            emoji=spec.emoji,
            disabled=disabled,
            custom_id=spec.custom_id,
        )
        self.spec = spec

    async def callback(self, interaction: discord.Interaction) -> None:
        service = NowPlayingPanelService(cast(Any, self.view).bot)
        playback = AudioPlaybackService(service.bot, service.bot.settings.bot.music_library)
        match self.spec.key:
            case "previous":
                await service.run_button_action(interaction, playback.back, reason="button:back")
            case "pause_resume":
                await service.run_button_action(
                    interaction,
                    lambda guild: playback.resume(guild)
                    if (
                        service.bot.player_states.get(guild.id) is not None
                        and service.bot.player_states.get(guild.id).paused
                    )
                    else playback.pause(guild),
                    reason="button:pause_resume",
                )
            case "next":
                await service.run_button_action(interaction, playback.skip, reason="button:skip")
            case "stop":
                await service.run_button_action(interaction, playback.stop, reason="button:stop")
            case "loop":
                await service.run_button_action(
                    interaction,
                    lambda guild: playback.toggle_loop(guild.id),
                    reason="button:loop",
                    success_message=True,
                )
            case "volume_down":
                await service.run_button_action(
                    interaction,
                    lambda guild: playback.change_volume(guild, -VOLUME_STEP),
                    reason="button:volume",
                    success_message=True,
                )
            case "volume_up":
                await service.run_button_action(
                    interaction,
                    lambda guild: playback.change_volume(guild, VOLUME_STEP),
                    reason="button:volume",
                    success_message=True,
                )
            case "queue":
                await service.show_queue(interaction)
            case "shuffle":
                await service.shuffle_queue(interaction)
            case "more":
                await service.show_more_actions(interaction)
            case "like" | "superlike" | "dislike" | "superdislike":
                await service.run_rating_action(interaction, self.spec.key)


class MoreActionsSelect(discord.ui.Select[Any]):
    def __init__(self, bot: Any, snapshot: NowPlayingSnapshot | None) -> None:
        super().__init__(
            custom_id="weasel:now_playing:more_actions",
            placeholder="More actions",
            min_values=1,
            max_values=1,
            options=list(MORE_ACTION_OPTIONS),
        )
        self.bot = bot
        self.snapshot = snapshot

    async def callback(self, interaction: discord.Interaction) -> None:
        choice = self.values[0]
        guild = interaction.guild
        state = self.bot.player_states.get(guild.id) if guild is not None else None
        snapshot = (
            NowPlayingPanelService(self.bot).snapshot_for(guild)
            if guild is not None
            else self.snapshot
        )
        if choice == "show_queue":
            await respond_ephemeral_update(interaction, format_queue(state), view=None)
            return
        if choice == "track_info":
            await respond_ephemeral_update(
                interaction,
                format_track_information(snapshot),
                view=None,
            )
            return
        await respond_ephemeral_update(
            interaction,
            "That Weasel Galaxy action is reserved for a future phase.",
            view=None,
        )


class MoreActionsView(discord.ui.View):
    def __init__(self, bot: Any, snapshot: NowPlayingSnapshot | None) -> None:
        super().__init__(timeout=120)
        self.add_item(MoreActionsSelect(bot, snapshot))


def build_control_button(spec: ControlSpec, snapshot: NowPlayingSnapshot) -> PanelControlButton:
    return PanelControlButton(spec, snapshot)


def build_now_playing_embed(snapshot: NowPlayingSnapshot) -> discord.Embed:
    embed = discord.Embed(
        title="WEASEL GALAXY",
        description=(
            "**Now Playing**\n\n"
            f"**{snapshot.track_display.title}**\n"
            f"{snapshot.track_display.metadata_line}\n\n"
            f"{snapshot.status} • {snapshot.volume}% • "
            f"{snapshot.volume_source_label} • {snapshot.queue_length} queued\n"
            f"Next: {snapshot.next_title or 'Nothing queued'}"
        ),
        color=discord.Color(WEASEL_GALAXY_ACCENT),
    )
    loop_value = "On (experimental)" if snapshot.loop_enabled else "Off"
    embed.add_field(name="Loop", value=loop_value, inline=True)
    embed.add_field(
        name="Ratings",
        value=(
            f"❤️ {snapshot.rating_counts.like}   "
            f"💎 {snapshot.rating_counts.superlike}   "
            f"👎 {snapshot.rating_counts.dislike}   "
            f"💀 {snapshot.rating_counts.superdislike}"
        ),
        inline=False,
    )
    embed.set_footer(text="Components V2 fallback panel")
    return embed


def format_queue(state: GuildPlayerState | None, *, limit: int = QUEUE_PREVIEW_LIMIT) -> str:
    if state is None or (not state.has_track and state.queue_length == 0):
        return "Nothing is playing and the queue is empty."

    lines = [f"Now playing: {track_title(state.current_track)}"]
    if not state.upcoming:
        lines.append("Queue is empty.")
        return "\n".join(lines)

    total = len(state.upcoming)
    lines.append(f"Upcoming ({total}):")
    for index, track in enumerate(state.upcoming[:limit], start=1):
        lines.append(f"{index}. {track_title(track)}")
    remaining = total - limit
    if remaining > 0:
        lines.append(f"...and {remaining} more.")
    return "\n".join(lines)


def format_track_information(snapshot: NowPlayingSnapshot | None) -> str:
    if snapshot is None or not snapshot.has_track:
        return "Nothing is playing."
    extension = snapshot.track_display.extension or "unknown"
    category = snapshot.track_display.category or "Uncategorized"
    return "\n".join(
        (
            f"Title: {snapshot.track_display.title}",
            f"Artist: {snapshot.track_display.artist}",
            f"Category: {category}",
            f"Extension: {extension}",
            f"Queue: {snapshot.queue_length} upcoming",
            (
                "Ratings: "
                f"❤️ {snapshot.rating_counts.like}   "
                f"💎 {snapshot.rating_counts.superlike}   "
                f"👎 {snapshot.rating_counts.dislike}   "
                f"💀 {snapshot.rating_counts.superdislike}"
            ),
        )
    )


def queue_preview_for(
    state: GuildPlayerState | None,
    *,
    limit: int = QUEUE_PREVIEW_LIMIT,
) -> QueuePreview:
    if state is None:
        return QueuePreview(current="None", upcoming=(), total_remaining=0)
    return QueuePreview(
        current=track_title(state.current_track),
        upcoming=tuple(track_title(track) for track in state.upcoming[:limit]),
        total_remaining=state.queue_length,
    )


def track_display_for(track: Track | object | None) -> TrackDisplay:
    if track is None:
        return TrackDisplay(title="Nothing playing", artist=UNKNOWN_ARTIST)
    local_track = cast(Any, track)
    artist = clean_text(local_track.artist or local_track.artist_guess) or UNKNOWN_ARTIST
    category = clean_text(local_track.category_guess)
    extension = clean_text(local_track.extension) or extension_from_track(local_track)
    return TrackDisplay(
        title=track_title(track),
        artist=artist,
        category=category,
        extension=extension,
    )


def track_title(track: Track | object | None) -> str:
    if track is None:
        return "None"
    local_track = cast(Any, track)
    return (
        clean_text(local_track.display_title)
        or clean_text(local_track.title)
        or clean_text(local_track.file_name)
        or "Unknown local track"
    )


def extension_from_track(track: Any) -> str | None:
    file_name = clean_text(getattr(track, "file_name", None))
    if not file_name or "." not in file_name:
        return None
    return file_name.rsplit(".", maxsplit=1)[-1].lower()


def clean_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def panel_artwork_for_bot(bot: Any) -> PanelArtwork | None:
    provider = getattr(bot, "now_playing_artwork", None)
    if provider is None:
        return None
    if isinstance(provider, PanelArtwork):
        return provider
    thumbnail_url = clean_text(getattr(provider, "thumbnail_url", None))
    if thumbnail_url is None:
        return None
    return PanelArtwork(thumbnail_url=thumbnail_url)


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


async def respond_ephemeral_update(
    interaction: discord.Interaction,
    content: str,
    *,
    view: discord.ui.View | None,
) -> None:
    try:
        if not interaction.response.is_done():
            await interaction.response.edit_message(content=content, view=view)
            return
    except discord.InteractionResponded:
        pass
    if view is None:
        await interaction.followup.send(content, ephemeral=True)
        return
    await interaction.followup.send(content, view=view, ephemeral=True)


def control_custom_ids() -> tuple[str, ...]:
    return tuple(spec.custom_id for spec in PLAYER_CONTROL_SPECS)


def control_specs() -> tuple[ControlSpec, ...]:
    return PLAYER_CONTROL_SPECS


def control_labels() -> tuple[str | None, ...]:
    snapshot = NowPlayingSnapshot(
        guild_id=0,
        has_track=True,
        title="Test",
        artist="Artist",
        category=None,
        status="Playing",
        volume=100,
        volume_source_label="default",
        loop_enabled=False,
        queue_length=2,
        next_title="Next",
        previous_available=True,
        rating_counts=RatingCounts(),
        relative_path=None,
        lavalink_available=True,
        player_connected=True,
        track_display=TrackDisplay(title="Test", artist="Artist"),
        queue_preview=QueuePreview(current="Test", upcoming=("Next",), total_remaining=1),
    )
    return tuple(build_control_button(spec, snapshot).label for spec in PLAYER_CONTROL_SPECS)


def control_emojis() -> tuple[str | None, ...]:
    snapshot = NowPlayingSnapshot(
        guild_id=0,
        has_track=True,
        title="Test",
        artist="Artist",
        category=None,
        status="Playing",
        volume=100,
        volume_source_label="default",
        loop_enabled=False,
        queue_length=2,
        next_title="Next",
        previous_available=True,
        rating_counts=RatingCounts(),
        relative_path=None,
        lavalink_available=True,
        player_connected=True,
        track_display=TrackDisplay(title="Test", artist="Artist"),
        queue_preview=QueuePreview(current="Test", upcoming=("Next",), total_remaining=1),
    )
    return tuple(
        str(button.emoji) if button.emoji is not None else None
        for button in (build_control_button(spec, snapshot) for spec in PLAYER_CONTROL_SPECS)
    )


def more_action_values() -> tuple[str, ...]:
    return tuple(option.value for option in MORE_ACTION_OPTIONS)


def shuffle_upcoming_queue(state: GuildPlayerState | None) -> PlaybackResult:
    if state is None or state.queue_length == 0:
        return PlaybackResult(ok=False, message="The queue is empty.")
    if state.queue_length == 1:
        return PlaybackResult(ok=False, message="Only one upcoming track is queued.")
    current = state.current_track
    before = list(state.upcoming)
    random.shuffle(state.upcoming)
    if state.upcoming == before:
        state.upcoming.reverse()
    assert state.current_track is current
    return PlaybackResult(ok=True, message=f"Shuffled {state.queue_length} upcoming tracks.")
