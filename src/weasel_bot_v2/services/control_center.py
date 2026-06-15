from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

import discord

from weasel_bot_v2.repositories import PlayAllPolicyRepository, TrackRepository, UserRepository
from weasel_bot_v2.services.audio import AudioPlaybackService, PlaybackResult
from weasel_bot_v2.services.local_library import LocalLibraryService
from weasel_bot_v2.services.now_playing_panel import (
    RATINGS_CENTER_PLACEHOLDER_CUSTOM_ID,
    NowPlayingPanelService,
    NowPlayingSnapshot,
    format_queue,
    format_track_information,
    resolve_control_emoji,
    respond_ephemeral_update,
    shuffle_upcoming_queue,
)
from weasel_bot_v2.services.play_all_policy import PlayAllPolicyService
from weasel_bot_v2.services.player_actions import PlayerActionService
from weasel_bot_v2.services.player_state import VOLUME_STEP

OPEN_CONTROL_PANEL_CUSTOM_ID = "weasel:controls:open"


@dataclass(frozen=True)
class ControlCenterButtonSpec:
    key: str
    custom_id: str
    label: str | None
    emoji: str | None
    row: int
    style: discord.ButtonStyle


CONTROL_CENTER_SPECS: tuple[ControlCenterButtonSpec, ...] = (
    ControlCenterButtonSpec(
        "previous",
        "weasel:controls:back",
        None,
        "⏮️",
        0,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "pause_resume",
        "weasel:controls:pause_resume",
        None,
        "⏯️",
        0,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "next",
        "weasel:controls:skip",
        None,
        "⏭️",
        0,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "stop",
        "weasel:controls:stop",
        None,
        "⏹️",
        0,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "loop",
        "weasel:controls:loop",
        None,
        "🔁",
        0,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "volume_down",
        "weasel:controls:volume_down",
        None,
        "🔉",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "volume_up",
        "weasel:controls:volume_up",
        None,
        "🔊",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "shuffle",
        "weasel:controls:shuffle",
        None,
        "🔀",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "queue",
        "weasel:controls:queue",
        None,
        "📜",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "more",
        "weasel:controls:more",
        None,
        "⋯",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "like",
        "weasel:controls:like",
        None,
        "❤️",
        2,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "superlike",
        "weasel:controls:superlike",
        None,
        "💎",
        2,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "placeholder",
        RATINGS_CENTER_PLACEHOLDER_CUSTOM_ID,
        None,
        "❔",
        2,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "dislike",
        "weasel:controls:dislike",
        None,
        "👎",
        2,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "superdislike",
        "weasel:controls:superdislike",
        None,
        "💀",
        2,
        discord.ButtonStyle.secondary,
    ),
)


ADVANCED_ACTIONS: tuple[ControlCenterButtonSpec, ...] = (
    ControlCenterButtonSpec(
        "queue_details",
        "weasel:controls:advanced:queue",
        "Queue Details",
        "📜",
        0,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "now_playing_details",
        "weasel:controls:advanced:details",
        "Now Playing Details",
        "ℹ️",
        0,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "shuffle_queue",
        "weasel:controls:advanced:shuffle",
        "Shuffle Future Queue",
        "🔀",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "reset_volume",
        "weasel:controls:advanced:reset_volume",
        "Reset Track Volume",
        "↩️",
        1,
        discord.ButtonStyle.secondary,
    ),
    ControlCenterButtonSpec(
        "clear_queue",
        "weasel:controls:advanced:clear_queue",
        "Clear Future Queue",
        "🧹",
        1,
        discord.ButtonStyle.danger,
    ),
    ControlCenterButtonSpec(
        "leave",
        "weasel:controls:advanced:leave",
        "Leave Voice",
        "👋",
        2,
        discord.ButtonStyle.danger,
    ),
    ControlCenterButtonSpec(
        "back_to_controls",
        "weasel:controls:advanced:back",
        "Back to Control Center",
        "↩️",
        2,
        discord.ButtonStyle.primary,
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
            elif action_key == "more":
                snapshot = panel.snapshot_for(guild)
                await respond_ephemeral_update(
                    interaction,
                    format_advanced_actions(snapshot),
                    view=AdvancedActionsView(self.bot, snapshot),
                )
                return
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

    async def show_more_actions(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await respond_ephemeral_update(
                interaction,
                "This control can only be used in a server.",
                view=None,
            )
            return
        snapshot = self.snapshot_for(guild)
        await respond_ephemeral_update(
            interaction,
            format_advanced_actions(snapshot),
            view=AdvancedActionsView(self.bot, snapshot),
        )

    async def open_more_actions(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await _send_initial_control_center(
                interaction,
                "This control can only be used in a server.",
                view=None,
            )
            return
        snapshot = self.snapshot_for(guild)
        await _send_initial_control_center(
            interaction,
            format_advanced_actions(snapshot),
            view=AdvancedActionsView(self.bot, snapshot),
        )

    async def run_advanced_action(
        self,
        interaction: discord.Interaction,
        action_key: str,
        *,
        confirmed: bool = False,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await respond_ephemeral_update(
                interaction,
                "This control can only be used in a server.",
                view=None,
            )
            return

        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            snapshot = panel.snapshot_for(guild)
            if action_key == "back_to_controls":
                await respond_ephemeral_update(
                    interaction,
                    format_control_center(snapshot),
                    view=ControlCenterView(self.bot, snapshot),
                )
                return
            if action_key == "queue_details":
                state = self.bot.player_states.get(guild.id)
                await respond_ephemeral_update(
                    interaction,
                    format_queue(state),
                    view=AdvancedActionsView(self.bot, snapshot),
                )
                return
            if action_key == "now_playing_details":
                await respond_ephemeral_update(
                    interaction,
                    format_track_information(snapshot),
                    view=AdvancedActionsView(self.bot, snapshot),
                )
                return
            if action_key in {"clear_queue", "leave"} and not confirmed:
                await respond_ephemeral_update(
                    interaction,
                    confirmation_text(action_key),
                    view=AdvancedConfirmationView(self.bot, action_key),
                )
                return
            if action_key == "toggle_playall_exception":
                if not await _is_admin_or_owner(self.bot, interaction):
                    await respond_ephemeral_update(
                        interaction,
                        "Only an administrator or bot owner can manage /play_all exceptions.",
                        view=AdvancedActionsView(self.bot, snapshot),
                    )
                    return

            result = self._run_advanced_mutation(guild, interaction, action_key)
            if inspect.isawaitable(result):
                result = await result
            await panel.refresh_locked(
                guild=guild,
                channel=cast(discord.abc.Messageable | None, interaction.channel),
                reason=f"controls:advanced:{action_key}",
            )
            snapshot = panel.snapshot_for(guild)

        await respond_ephemeral_update(
            interaction,
            format_advanced_actions(snapshot, notice=result.message),
            view=AdvancedActionsView(self.bot, snapshot),
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
            "shuffle": lambda current_guild: shuffle_upcoming_queue(
                self.bot.player_states.get(current_guild.id)
            ),
            "volume_down": lambda current_guild: playback.change_volume(
                current_guild, -VOLUME_STEP
            ),
            "volume_up": lambda current_guild: playback.change_volume(current_guild, VOLUME_STEP),
        }
        action = actions.get(action_key)
        if action is None:
            return PlaybackResult(ok=False, message="That control is not available.")

        result_or_awaitable = action(guild)
        if inspect.isawaitable(result_or_awaitable):
            return await result_or_awaitable
        return result_or_awaitable

    def _run_advanced_mutation(
        self,
        guild: discord.Guild,
        interaction: discord.Interaction,
        action_key: str,
    ) -> Awaitable[PlaybackResult] | PlaybackResult:
        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        if action_key == "shuffle_queue":
            state = self.bot.player_states.get(guild.id)
            return shuffle_upcoming_queue(state)
        if action_key == "reset_volume":
            return playback.reset_current_track_volume(guild)
        if action_key == "toggle_playall_exception":
            state = self.bot.player_states.get(guild.id)
            track = state.current_track if state is not None else None
            result = _play_all_policy_service(self.bot).toggle_current_track_exception(
                guild_id=guild.id,
                user_id=interaction.user.id,
                display_name=getattr(interaction.user, "display_name", None),
                track=track,
            )
            return PlaybackResult(ok=result.ok, message=result.message)
        if action_key == "clear_queue":
            return playback.clear_queue(guild.id)
        if action_key == "leave":
            return playback.leave(guild)
        return PlaybackResult(ok=False, message="That advanced action is not available.")


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
            if spec.key == "placeholder":
                self.add_item(ControlCenterPlaceholderButton(spec))
                continue
            self.add_item(ControlCenterButton(bot, spec, snapshot))


class ControlCenterPlaceholderButton(discord.ui.Button[Any]):
    def __init__(self, spec: ControlCenterButtonSpec) -> None:
        super().__init__(
            label=None,
            emoji=spec.emoji,
            custom_id=spec.custom_id,
            row=spec.row,
            style=discord.ButtonStyle.secondary,
            disabled=True,
        )
        self.spec = spec


class ControlCenterButton(discord.ui.Button[Any]):
    def __init__(
        self,
        bot: Any,
        spec: ControlCenterButtonSpec,
        snapshot: NowPlayingSnapshot,
    ) -> None:
        disabled = _control_disabled(spec.key, snapshot)
        emoji = resolve_control_emoji(bot, spec.key, snapshot, fallback=spec.emoji)
        super().__init__(
            label=spec.label,
            emoji=emoji,
            custom_id=spec.custom_id,
            row=spec.row,
            style=spec.style,
            disabled=disabled,
        )
        self.spec = spec

    async def callback(self, interaction: discord.Interaction) -> None:
        await ControlCenterService(cast(Any, self.view).bot).run_action(
            interaction,
            self.spec.key,
        )


class AdvancedActionsView(discord.ui.View):
    def __init__(self, bot: Any, snapshot: NowPlayingSnapshot) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        for spec in _advanced_action_specs(bot, snapshot):
            self.add_item(AdvancedActionButton(bot, spec, snapshot))


class AdvancedActionButton(discord.ui.Button[Any]):
    def __init__(
        self,
        bot: Any,
        spec: ControlCenterButtonSpec,
        snapshot: NowPlayingSnapshot,
    ) -> None:
        emoji = resolve_control_emoji(bot, spec.key, snapshot, fallback=spec.emoji)
        super().__init__(
            label=spec.label,
            emoji=emoji,
            custom_id=spec.custom_id,
            row=spec.row,
            style=spec.style,
            disabled=_advanced_disabled(spec.key, snapshot),
        )
        self.spec = spec

    async def callback(self, interaction: discord.Interaction) -> None:
        await ControlCenterService(cast(Any, self.view).bot).run_advanced_action(
            interaction,
            self.spec.key,
        )


class AdvancedConfirmationView(discord.ui.View):
    def __init__(self, bot: Any, action_key: str) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.action_key = action_key
        self.add_item(AdvancedConfirmButton(action_key))
        self.add_item(AdvancedCancelButton())


class AdvancedConfirmButton(discord.ui.Button[Any]):
    def __init__(self, action_key: str) -> None:
        super().__init__(
            label="Confirm",
            custom_id=f"weasel:controls:advanced:{action_key}:confirm",
            style=discord.ButtonStyle.danger,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = cast(Any, self.view)
        await ControlCenterService(view.bot).run_advanced_action(
            interaction,
            view.action_key,
            confirmed=True,
        )


class AdvancedCancelButton(discord.ui.Button[Any]):
    def __init__(self) -> None:
        super().__init__(
            label="Cancel",
            custom_id="weasel:controls:advanced:cancel",
            style=discord.ButtonStyle.secondary,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await respond_ephemeral_update(interaction, "Cancelled.", view=None)
            return
        service = ControlCenterService(cast(Any, self.view).bot)
        snapshot = service.snapshot_for(guild)
        await respond_ephemeral_update(
            interaction,
            format_advanced_actions(snapshot, notice="Cancelled."),
            view=AdvancedActionsView(service.bot, snapshot),
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


def format_advanced_actions(snapshot: NowPlayingSnapshot, *, notice: str | None = None) -> str:
    lines = [
        "### WEASEL GALAXY",
        "More Actions",
        f"Current: {snapshot.track_display.title}",
        f"Queue: {snapshot.queue_length} upcoming",
    ]
    if notice:
        lines.extend(("", notice))
    return "\n".join(lines)


def confirmation_text(action_key: str) -> str:
    if action_key == "leave":
        return "Leave voice and reset the current playback session?"
    return "Clear all future queued tracks? The current track will keep playing."


def control_center_custom_ids() -> tuple[str, ...]:
    return tuple(spec.custom_id for spec in CONTROL_CENTER_SPECS) + (
        OPEN_CONTROL_PANEL_CUSTOM_ID,
    )


def _control_disabled(key: str, snapshot: NowPlayingSnapshot) -> bool:
    if key in {"queue", "more"}:
        return False
    if key == "placeholder":
        return True
    if not snapshot.has_track:
        return True
    if key == "previous":
        return not snapshot.previous_available
    if key == "shuffle":
        return snapshot.queue_length <= 1
    return False


def _advanced_disabled(key: str, snapshot: NowPlayingSnapshot) -> bool:
    if key in {"back_to_controls"}:
        return False
    if key in {"queue_details", "now_playing_details"}:
        return not snapshot.has_track and snapshot.queue_length == 0
    if key in {"shuffle_queue", "clear_queue"}:
        return snapshot.queue_length == 0
    if key == "toggle_playall_exception":
        return not snapshot.has_track
    return not snapshot.has_track


def _advanced_action_specs(
    bot: Any,
    snapshot: NowPlayingSnapshot,
) -> tuple[ControlCenterButtonSpec, ...]:
    specs = list(ADVANCED_ACTIONS)
    state = bot.player_states.get(snapshot.guild_id)
    track = state.current_track if state is not None else None
    if track is not None and track.id is not None and track.is_available:
        has_exception = _play_all_policy_service(bot).has_track_exception(
            guild_id=snapshot.guild_id,
            track=track,
        )
        specs.insert(
            4,
            ControlCenterButtonSpec(
                "toggle_playall_exception",
                "weasel:controls:advanced:playall_exception",
                "Remove Play All Exception" if has_exception else "Add Play All Exception",
                "⭐",
                2,
                discord.ButtonStyle.secondary,
            ),
        )
    return tuple(specs)


def _play_all_policy_service(bot: Any) -> PlayAllPolicyService:
    return PlayAllPolicyService(
        policy=PlayAllPolicyRepository(bot.database),
        tracks=TrackRepository(bot.database),
        users=UserRepository(bot.database),
        library=LocalLibraryService(bot.settings.bot.music_library, TrackRepository(bot.database)),
    )


async def _is_admin_or_owner(bot: Any, interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    if bool(getattr(permissions, "administrator", False)):
        return True
    try:
        app_info = await bot.application_info()
    except Exception:  # noqa: BLE001 - fall back to guild administrator.
        return False
    owner = getattr(app_info, "owner", None)
    return getattr(owner, "id", None) == interaction.user.id


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
