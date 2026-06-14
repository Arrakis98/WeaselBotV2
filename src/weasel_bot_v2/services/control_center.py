from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

import discord

from weasel_bot_v2.services.audio import AudioPlaybackService, PlaybackResult
from weasel_bot_v2.services.now_playing_panel import (
    NowPlayingPanelService,
    NowPlayingSnapshot,
    format_queue,
    respond_ephemeral_update,
)
from weasel_bot_v2.services.player_actions import PlayerActionService
from weasel_bot_v2.services.player_state import VOLUME_STEP

OPEN_CONTROL_PANEL_CUSTOM_ID = "weasel:controls:open"


@dataclass(frozen=True)
class ControlCenterButtonSpec:
    key: str
    custom_id: str
    label: str
    emoji: str | None
    row: int
    style: discord.ButtonStyle


CONTROL_CENTER_SPECS: tuple[ControlCenterButtonSpec, ...] = (
    ControlCenterButtonSpec(
        "previous",
        "weasel:controls:back",
        "Back",
        "⏮️",
        0,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "pause_resume",
        "weasel:controls:pause_resume",
        "Pause",
        "⏯️",
        0,
        discord.ButtonStyle.primary,
    ),
    ControlCenterButtonSpec(
        "next",
        "weasel:controls:skip",
        "Skip",
        "⏭️",
        0,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "stop",
        "weasel:controls:stop",
        "Stop",
        "⏹️",
        0,
        discord.ButtonStyle.danger,
    ),
    ControlCenterButtonSpec(
        "loop",
        "weasel:controls:loop",
        "Loop",
        "🔁",
        0,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "volume_down",
        "weasel:controls:volume_down",
        "Volume -",
        "🔉",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "volume_up",
        "weasel:controls:volume_up",
        "Volume +",
        "🔊",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "reset_volume",
        "weasel:controls:reset_volume",
        "Reset Volume",
        "↩️",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "queue",
        "weasel:controls:queue",
        "Queue",
        "📜",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "like",
        "weasel:controls:like",
        "Like",
        "❤️",
        2,
        discord.ButtonStyle.success,
    ),
    ControlCenterButtonSpec(
        "superlike",
        "weasel:controls:superlike",
        "SuperLike",
        "💎",
        2,
        discord.ButtonStyle.success,
    ),
    ControlCenterButtonSpec(
        "dislike",
        "weasel:controls:dislike",
        "Dislike",
        "👎",
        2,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "superdislike",
        "weasel:controls:superdislike",
        "SuperDislike",
        "💀",
        2,
        discord.ButtonStyle.danger,
    ),
)


class ControlCenterService:
    def __init__(self, bot: Any) -> None:
        self.bot = bot

    async def open(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await _send_initial_control_center(
                interaction,
                "This command can only be used in a server.",
                view=None,
            )
            return

        snapshot = self.snapshot_for(guild)
        await _send_initial_control_center(
            interaction,
            format_control_center(snapshot),
            view=ControlCenterView(self.bot, snapshot),
        )

    async def run_action(self, interaction: discord.Interaction, action_key: str) -> None:
        guild = interaction.guild
        if guild is None:
            await respond_ephemeral_update(
                interaction,
                "This control can only be used in a server.",
                view=None,
            )
            return

        panel = NowPlayingPanelService(self.bot)
        action_message: str | None = None
        async with panel.lock_for(guild.id):
            if action_key == "queue":
                state = self.bot.player_states.get(guild.id)
                action_message = format_queue(state)
            else:
                result = await self._run_mutating_action(guild, interaction, action_key)
                action_message = result.message
                await panel.refresh_locked(
                    guild=guild,
                    channel=cast(discord.abc.Messageable | None, interaction.channel),
                    reason=f"controls:{action_key}",
                )
            snapshot = panel.snapshot_for(guild)

        content = format_control_center(snapshot, notice=action_message)
        await respond_ephemeral_update(
            interaction,
            content,
            view=ControlCenterView(self.bot, snapshot),
        )

    def snapshot_for(self, guild: discord.Guild) -> NowPlayingSnapshot:
        return NowPlayingPanelService(self.bot).snapshot_for(guild)

    async def _run_mutating_action(
        self,
        guild: discord.Guild,
        interaction: discord.Interaction,
        action_key: str,
    ) -> PlaybackResult:
        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        if action_key == "pause_resume":
            state = self.bot.player_states.get(guild.id)
            if state is not None and state.paused:
                return await playback.resume(guild)
            return await playback.pause(guild)
        if action_key in {"like", "superlike", "dislike", "superdislike"}:
            return await PlayerActionService(self.bot).rate_current_track(
                guild=guild,
                user_id=interaction.user.id,
                display_name=interaction.user.display_name,
                rating_value=action_key,
            )

        actions: dict[
            str,
            Callable[[discord.Guild], Awaitable[PlaybackResult] | PlaybackResult],
        ] = {
            "previous": playback.back,
            "next": playback.skip,
            "stop": playback.stop,
            "loop": lambda current_guild: playback.toggle_loop(current_guild.id),
            "volume_down": lambda current_guild: playback.change_volume(
                current_guild, -VOLUME_STEP
            ),
            "volume_up": lambda current_guild: playback.change_volume(current_guild, VOLUME_STEP),
            "reset_volume": playback.reset_current_track_volume,
        }
        action = actions.get(action_key)
        if action is None:
            return PlaybackResult(ok=False, message="That control is not available.")

        result_or_awaitable = action(guild)
        if inspect.isawaitable(result_or_awaitable):
            return await result_or_awaitable
        return result_or_awaitable


class OpenControlPanelView(discord.ui.View):
    def __init__(self, bot: Any) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(OpenControlPanelButton())


class OpenControlPanelButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(
            label="Open Control Panel",
            custom_id=OPEN_CONTROL_PANEL_CUSTOM_ID,
            style=discord.ButtonStyle.primary,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await ControlCenterService(cast(Any, self.view).bot).open(interaction)


class ControlCenterView(discord.ui.View):
    def __init__(self, bot: Any, snapshot: NowPlayingSnapshot) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = snapshot.guild_id
        for spec in CONTROL_CENTER_SPECS:
            self.add_item(ControlCenterButton(spec, snapshot))


class ControlCenterButton(discord.ui.Button[Any]):
    def __init__(self, spec: ControlCenterButtonSpec, snapshot: NowPlayingSnapshot) -> None:
        label = (
            "Resume"
            if spec.key == "pause_resume" and snapshot.status == "Paused"
            else spec.label
        )
        disabled = _control_disabled(spec.key, snapshot)
        style = (
            discord.ButtonStyle.success
            if spec.key == "loop" and snapshot.loop_enabled
            else spec.style
        )
        super().__init__(
            label=label,
            emoji=spec.emoji,
            custom_id=spec.custom_id,
            row=spec.row,
            style=style,
            disabled=disabled,
        )
        self.spec = spec

    async def callback(self, interaction: discord.Interaction) -> None:
        await ControlCenterService(cast(Any, self.view).bot).run_action(
            interaction,
            self.spec.key,
        )


def format_control_center(snapshot: NowPlayingSnapshot, *, notice: str | None = None) -> str:
    lines = [
        "### WEASEL GALAXY CONTROL CENTER",
        f"**{snapshot.track_display.title}**",
        snapshot.track_display.metadata_line,
        (
            f"{snapshot.status} • {snapshot.volume}% • "
            f"{snapshot.volume_source_label} • {snapshot.queue_length} queued"
        ),
        f"Next: {snapshot.next_title or 'Nothing queued'}",
        (
            "Ratings: "
            f"❤️ {snapshot.rating_counts.like}   "
            f"💎 {snapshot.rating_counts.superlike}   "
            f"👎 {snapshot.rating_counts.dislike}   "
            f"💀 {snapshot.rating_counts.superdislike}"
        ),
    ]
    if notice:
        lines.extend(("", notice))
    return "\n".join(lines)


def control_center_custom_ids() -> tuple[str, ...]:
    return tuple(spec.custom_id for spec in CONTROL_CENTER_SPECS) + (
        OPEN_CONTROL_PANEL_CUSTOM_ID,
    )


def _control_disabled(key: str, snapshot: NowPlayingSnapshot) -> bool:
    if key == "queue":
        return False
    if not snapshot.has_track:
        return True
    if key == "previous":
        return not snapshot.previous_available
    return False


async def _send_initial_control_center(
    interaction: discord.Interaction,
    content: str,
    *,
    view: discord.ui.View | None,
) -> None:
    try:
        if not interaction.response.is_done():
            if view is None:
                await interaction.response.send_message(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, view=view, ephemeral=True)
            return
    except discord.InteractionResponded:
        pass
    if view is None:
        await interaction.followup.send(content, ephemeral=True)
        return
    await interaction.followup.send(content, view=view, ephemeral=True)
