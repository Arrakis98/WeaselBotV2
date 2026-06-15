from __future__ import annotations

import inspect
import random
from collections.abc import Sequence
from typing import Any, cast

import discord
from discord import app_commands
from discord.ext import commands

from weasel_bot_v2.bot import WeaselBot
from weasel_bot_v2.models import QuarantineRecord, RatingCounts, UserTrackRating
from weasel_bot_v2.repositories import (
    PlayAllPolicyRepository,
    QuarantineRepository,
    RatingRepository,
    TrackRepository,
    UserRepository,
)
from weasel_bot_v2.services.audio import AudioPlaybackService
from weasel_bot_v2.services.control_center import ControlCenterService, OpenControlPanelView
from weasel_bot_v2.services.local_library import LocalLibraryService
from weasel_bot_v2.services.now_playing_panel import (
    NowPlayingPanelService,
    format_queue,
    resolve_rating_text_emoji,
    track_title,
)
from weasel_bot_v2.services.play_all_policy import (
    PlayAllPolicyService,
    display_artist_for_track,
)
from weasel_bot_v2.services.player_actions import PlayerActionService
from weasel_bot_v2.services.player_state import GuildPlayerState
from weasel_bot_v2.services.quarantine import (
    PurgePreview,
    QuarantineMoveResult,
    QuarantineService,
)
from weasel_bot_v2.services.ratings import RatingService


class MusicCog(commands.Cog):
    def __init__(self, bot: WeaselBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="library_scan",
        description="Index local audio files from the configured music directory.",
    )
    async def library_scan(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        service = self._library_service()
        result = service.scan()
        await interaction.followup.send(
            (
                "Library scan complete. "
                f"Found: {result.found}. Updated: {result.upserted}. Skipped: {result.skipped}."
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="library_stats",
        description="Show indexed local music library status.",
    )
    async def library_stats(self, interaction: discord.Interaction) -> None:
        service = self._library_service()
        count = service.stats()
        message = (
            f"Indexed local tracks: {count}\n"
            f"Configured music root: {self.bot.settings.bot.music_library}"
        )
        await interaction.response.send_message(
            message,
            ephemeral=True,
        )

    @app_commands.command(
        name="search_local",
        description="Search indexed local tracks.",
    )
    async def search_local(self, interaction: discord.Interaction, query: str) -> None:
        service = self._library_service()
        results = service.search(query, limit=5)
        if not results:
            await interaction.response.send_message(
                "No indexed local tracks matched.",
                ephemeral=True,
            )
            return

        lines = []
        for index, track in enumerate(results, start=1):
            title = track.display_title or track.file_name or track.relative_path or "Untitled"
            context = " / ".join(
                part for part in (track.category_guess, track.artist_guess) if part
            )
            suffix = f" - {context}" if context else ""
            lines.append(f"{index}. {title}{suffix}")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(
        name="play_local",
        description="Play the best matching indexed local track.",
    )
    async def play_local(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(thinking=True)
        library = self._library_service()
        matches = library.search(query, limit=1)
        if not matches:
            await interaction.followup.send("No indexed local tracks matched.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            state = self.bot.player_states.get_or_create(guild.id)
            was_active = state.has_track
            result = await playback.play_local_track(interaction=interaction, track=matches[0])
            if result.ok:
                await panel.refresh_locked(
                    guild=guild,
                    channel=cast(discord.abc.Messageable | None, interaction.channel),
                    reason="play_local",
                )
                message = compact_playback_ack(
                    "Added to queue" if was_active else "Playback started",
                    matches[0],
                    detail=f"Queue position: {state.queue_length}" if was_active else None,
                )
                await interaction.followup.send(
                    message,
                    ephemeral=False,
                    view=OpenControlPanelView(self.bot),
                )
                return
        await interaction.followup.send(result.message, ephemeral=True)

    @app_commands.command(
        name="play_all",
        description="Shuffle all indexed local MP3 tracks into the playback queue.",
    )
    @app_commands.describe(
        exclusions="Comma-separated artists to exclude for this run only.",
        use_exceptions="Allow stored track exceptions for this run.",
    )
    async def play_all(
        self,
        interaction: discord.Interaction,
        exclusions: str | None = None,
        use_exceptions: bool = True,
    ) -> None:
        await interaction.response.defer(thinking=True)
        library = self._library_service()
        indexed_tracks = library.list_indexed_mp3_tracks()
        if not indexed_tracks:
            await interaction.followup.send(
                "No indexed local MP3 tracks found. Run /library_scan first.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        policy_service = self._play_all_policy_service()
        exclusion_resolution = policy_service.resolve_invocation_exclusions(exclusions)
        if not exclusion_resolution.ok:
            await interaction.followup.send(exclusion_resolution.message, ephemeral=True)
            return

        policy_pool = policy_service.filter_tracks_for_play_all(
            guild.id,
            indexed_tracks,
            excluded_artist_keys=exclusion_resolution.excluded_artist_keys,
            use_exceptions=use_exceptions,
        )
        tracks = list(policy_pool.eligible_tracks)
        if not tracks:
            if exclusion_resolution.excluded_artist_keys:
                artists = ", ".join(exclusion_resolution.display_artists)
                message = (
                    "No eligible local MP3 tracks remain. "
                    f"The requested artist exclusions removed every Play All track: {artists}."
                )
            else:
                message = "No eligible local MP3 tracks are available for /play_all."
            await interaction.followup.send(
                message,
                ephemeral=True,
            )
            return

        random.shuffle(tracks)
        playback = self._playback_service()
        found_count = policy_pool.total_indexed_mp3
        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            state = self.bot.player_states.get_or_create(guild.id)
            if prepare_play_all_session(state, guild):
                start_position, queued_count = state.enqueue_many(tracks)
                await panel.refresh_locked(
                    guild=guild,
                    channel=cast(discord.abc.Messageable | None, interaction.channel),
                    reason="play_all:enqueue",
                )
                message = (
                    "Added to queue\n"
                    f"{queued_count} track(s) from {found_count} indexed MP3 tracks\n"
                    f"Starting position: {start_position}\n"
                    f"Queue length: {state.queue_length}"
                )
                await interaction.followup.send(
                    message,
                    ephemeral=False,
                    view=OpenControlPanelView(self.bot),
                )
                return

            first = tracks[0]
            remaining = tracks[1:]
            result = await playback.play_local_track(interaction=interaction, track=first)
            if not result.ok:
                await interaction.followup.send(result.message, ephemeral=True)
                return

            state.enqueue_many(remaining)
            await panel.refresh_locked(
                guild=guild,
                channel=cast(discord.abc.Messageable | None, interaction.channel),
                reason="play_all:start",
            )

        await interaction.followup.send(
            (
                "Playback started\n"
                f"{track_title(first)}\n"
                f"Queued {len(remaining)} more track(s) from {found_count} indexed MP3 tracks\n"
                f"Queue length: {state.queue_length}"
            ),
            ephemeral=False,
            view=OpenControlPanelView(self.bot),
        )

    @app_commands.command(name="pause", description="Pause the current local track.")
    async def pause_track(self, interaction: discord.Interaction) -> None:
        await self._run_player_action(interaction, lambda service, guild: service.pause(guild))

    @app_commands.command(name="resume", description="Resume the current local track.")
    async def resume_track(self, interaction: discord.Interaction) -> None:
        await self._run_player_action(interaction, lambda service, guild: service.resume(guild))

    @app_commands.command(name="stop", description="Stop playback and stay in voice.")
    async def stop_track(self, interaction: discord.Interaction) -> None:
        await self._run_player_action(
            interaction,
            lambda service, guild: service.stop(guild),
            public_success_action="Playback stopped",
        )

    @app_commands.command(name="leave", description="Stop playback and leave voice.")
    async def leave_voice(self, interaction: discord.Interaction) -> None:
        await self._run_player_action(
            interaction,
            lambda service, guild: service.leave(guild),
            public_success_action="Left voice channel",
        )

    @app_commands.command(name="volume", description="Show or set this server's volume.")
    async def volume(
        self,
        interaction: discord.Interaction,
        percent: int | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if percent is None:
            message = self._playback_service().current_volume_status(guild.id)
            await interaction.response.send_message(message, ephemeral=True)
            return

        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            result = await self._playback_service().set_current_track_volume(guild, percent)
            if result.ok:
                await panel.refresh_locked(
                    guild=guild,
                    channel=cast(discord.abc.Messageable | None, interaction.channel),
                    reason="volume",
                )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(
        name="default_volume",
        description="Set this server's fallback volume for tracks without presets.",
    )
    async def default_volume(self, interaction: discord.Interaction, percent: int) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            result = await self._playback_service().set_default_volume(guild, percent)
            if result.ok:
                await panel.refresh_locked(
                    guild=guild,
                    channel=cast(discord.abc.Messageable | None, interaction.channel),
                    reason="default_volume",
                )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(
        name="reset_track_volume",
        description="Remove the current track's saved volume preset.",
    )
    async def reset_track_volume(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            result = await self._playback_service().reset_current_track_volume(guild)
            if result.ok:
                await panel.refresh_locked(
                    guild=guild,
                    channel=cast(discord.abc.Messageable | None, interaction.channel),
                    reason="reset_track_volume",
                )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(
        name="now_playing",
        description="Show the current local track and playback controls.",
    )
    async def now_playing(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        state = self.bot.player_states.get(guild.id)
        if state is None or not state.has_track:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await self._refresh_panel(interaction, reason="now_playing")
        await interaction.followup.send("Now Playing panel refreshed.", ephemeral=True)

    @app_commands.command(
        name="controls",
        description="Open your personal Weasel Galaxy control center.",
    )
    async def controls(self, interaction: discord.Interaction) -> None:
        await ControlCenterService(self.bot).open(interaction)

    @app_commands.command(name="queue", description="Show the current local playback queue.")
    async def show_queue(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        state = self.bot.player_states.get(guild.id)
        await interaction.response.send_message(format_queue(state), ephemeral=True)

    @app_commands.command(name="skip", description="Skip to the next queued local track.")
    async def skip_track(self, interaction: discord.Interaction) -> None:
        await self._run_player_action(
            interaction,
            lambda service, guild: service.skip(guild),
            public_success_action="Skipped",
        )

    @app_commands.command(name="back", description="Go back to the previous local track.")
    async def back_track(self, interaction: discord.Interaction) -> None:
        await self._run_player_action(
            interaction,
            lambda service, guild: service.back(guild),
            public_success_action="Previous track",
        )

    @app_commands.command(name="clear_queue", description="Clear upcoming local tracks.")
    async def clear_queue(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            result = self._playback_service().clear_queue(guild.id)
            if result.ok:
                await panel.refresh_locked(
                    guild=guild,
                    channel=cast(discord.abc.Messageable | None, interaction.channel),
                    reason="clear_queue",
                )
        if result.ok:
            await interaction.response.send_message(
                f"Queue cleared\n{result.message}",
                ephemeral=False,
                view=OpenControlPanelView(self.bot),
            )
            return
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(
        name="remove_from_queue",
        description="Remove a queued track by position.",
    )
    async def remove_from_queue(self, interaction: discord.Interaction, position: int) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            result = self._playback_service().remove_from_queue(guild.id, position)
            if result.ok:
                await panel.refresh_locked(
                    guild=guild,
                    channel=cast(discord.abc.Messageable | None, interaction.channel),
                    reason="remove_from_queue",
                )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(name="like", description="Like the current local track.")
    async def like_current_track(self, interaction: discord.Interaction) -> None:
        await self._rate_current_track(interaction, "like")

    @app_commands.command(
        name="superlike",
        description="SuperLike the current local track.",
    )
    async def superlike_current_track(self, interaction: discord.Interaction) -> None:
        await self._rate_current_track(interaction, "superlike")

    @app_commands.command(name="dislike", description="Dislike the current local track.")
    async def dislike_current_track(self, interaction: discord.Interaction) -> None:
        await self._rate_current_track(interaction, "dislike")

    @app_commands.command(
        name="superdislike",
        description="SuperDislike the current local track.",
    )
    async def superdislike_current_track(self, interaction: discord.Interaction) -> None:
        await self._rate_current_track(interaction, "superdislike")

    @app_commands.command(
        name="my_rating",
        description="Show your rating for the current local track.",
    )
    async def my_rating(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        state = self.bot.player_states.get(guild.id)
        result = self._rating_service().get_current_rating(
            state=state,
            user_id=interaction.user.id,
        )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(
        name="my_ratings",
        description="Browse your saved music ratings in this server.",
    )
    @app_commands.describe(
        rating="Rating filter.",
        page="Page number.",
    )
    @app_commands.choices(
        rating=[
            app_commands.Choice(name="all", value="all"),
            app_commands.Choice(name="like", value="like"),
            app_commands.Choice(name="superlike", value="superlike"),
            app_commands.Choice(name="dislike", value="dislike"),
            app_commands.Choice(name="superdislike", value="superdislike"),
        ]
    )
    async def my_ratings(
        self,
        interaction: discord.Interaction,
        rating: str = "all",
        page: int = 1,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return
        rating_filter = rating or "all"
        if page < 1:
            await interaction.response.send_message(
                "Page must be a positive integer.",
                ephemeral=True,
            )
            return
        message = format_my_ratings(
            ratings=RatingRepository(self.bot.database),
            bot=self.bot,
            guild_id=guild.id,
            user_id=interaction.user.id,
            rating_filter=rating_filter,
            page=page,
        )
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(
        name="playall_exception",
        description="Add or remove one persistent /play_all track exception.",
    )
    @app_commands.describe(
        track="Indexed local track search.",
        enabled="true to add the exception, false to remove it.",
    )
    async def playall_exception(
        self,
        interaction: discord.Interaction,
        track: str,
        enabled: bool,
    ) -> None:
        if not await self._require_policy_admin(interaction):
            return
        guild = cast(discord.Guild, interaction.guild)
        policy = self._play_all_policy_service()
        resolution = policy.resolve_available_track(track)
        if not resolution.ok or resolution.track is None:
            await interaction.response.send_message(resolution.message, ephemeral=True)
            return
        if enabled:
            result = policy.add_track_exception_by_track(
                guild_id=guild.id,
                user_id=interaction.user.id,
                display_name=getattr(interaction.user, "display_name", None),
                track=resolution.track,
            )
        else:
            result = policy.remove_track_exception_by_track(
                guild_id=guild.id,
                track=resolution.track,
            )
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(
        name="purge_superdisliked",
        description="Preview or move SuperDisliked tracks into reversible quarantine.",
    )
    async def purge_superdisliked(
        self,
        interaction: discord.Interaction,
        execute: bool = False,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return
        if not await self._is_admin_or_owner(interaction):
            await interaction.response.send_message(
                "Only an administrator or bot owner can run this moderation command.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        service = QuarantineService(self.bot)
        if not execute:
            preview = service.preview_superdisliked(guild.id)
            await interaction.followup.send(format_purge_preview(preview), ephemeral=True)
            return

        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            excluded: set[int] = set()
            state = self.bot.player_states.get(guild.id)
            current = state.current_track if state is not None else None
            if current is not None and current.id is not None and _track_has_superdislike(
                self.bot.database,
                guild.id,
                current.id,
            ):
                skip_result = await self._playback_service().skip(guild)
                if not skip_result.ok:
                    excluded.add(current.id)
            result = service.purge_superdisliked(
                guild_id=guild.id,
                requested_by_user_id=interaction.user.id,
                exclude_track_ids=excluded,
            )
            await panel.refresh_locked(
                guild=guild,
                channel=cast(discord.abc.Messageable | None, interaction.channel),
                reason="purge_superdisliked",
            )
        await interaction.followup.send(format_quarantine_result(result), ephemeral=True)

    @app_commands.command(
        name="quarantine_list",
        description="List recent reversible library quarantine records.",
    )
    async def quarantine_list(self, interaction: discord.Interaction, limit: int = 10) -> None:
        if not await self._is_admin_or_owner(interaction):
            await interaction.response.send_message(
                "Only an administrator or bot owner can inspect quarantine records.",
                ephemeral=True,
            )
            return
        records = QuarantineRepository(self.bot.database).list_records(limit=max(1, min(limit, 20)))
        tracks = TrackRepository(self.bot.database)
        await interaction.response.send_message(
            format_quarantine_list(records, tracks),
            ephemeral=True,
        )

    @app_commands.command(
        name="restore_quarantined",
        description="Restore a quarantined track by quarantine record ID.",
    )
    async def restore_quarantined(self, interaction: discord.Interaction, record_id: int) -> None:
        if not await self._is_admin_or_owner(interaction):
            await interaction.response.send_message(
                "Only an administrator or bot owner can restore quarantined tracks.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = QuarantineService(self.bot).restore(record_id)
        await interaction.followup.send(result.message, ephemeral=True)

    def _library_service(self) -> LocalLibraryService:
        return LocalLibraryService(
            music_root=self.bot.settings.bot.music_library,
            tracks=TrackRepository(self.bot.database),
        )

    def _playback_service(self) -> AudioPlaybackService:
        return AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)

    def _rating_service(self) -> RatingService:
        return RatingService(
            ratings=RatingRepository(self.bot.database),
            users=UserRepository(self.bot.database),
        )

    def _action_service(self) -> PlayerActionService:
        return PlayerActionService(self.bot)

    def _play_all_policy_service(self) -> PlayAllPolicyService:
        return PlayAllPolicyService(
            policy=PlayAllPolicyRepository(self.bot.database),
            tracks=TrackRepository(self.bot.database),
            users=UserRepository(self.bot.database),
            library=self._library_service(),
        )

    async def _require_policy_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return False
        if await self._is_admin_or_owner(interaction):
            return True
        await interaction.response.send_message(
            "Only an administrator or bot owner can manage /play_all policy.",
            ephemeral=True,
        )
        return False

    async def _is_admin_or_owner(self, interaction: discord.Interaction) -> bool:
        permissions = getattr(interaction.user, "guild_permissions", None)
        if bool(getattr(permissions, "administrator", False)):
            return True
        try:
            app_info = await self.bot.application_info()
        except Exception:  # noqa: BLE001 - fall back to guild administrator.
            return False
        owner = getattr(app_info, "owner", None)
        return getattr(owner, "id", None) == interaction.user.id

    async def _rate_current_track(
        self,
        interaction: discord.Interaction,
        rating_value: str,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            result = await self._action_service().rate_current_track(
                guild=guild,
                user_id=interaction.user.id,
                display_name=interaction.user.display_name,
                rating_value=rating_value,
            )
            if result.ok:
                await panel.refresh_locked(
                    guild=guild,
                    channel=cast(discord.abc.Messageable | None, interaction.channel),
                    reason=f"slash_rating:{rating_value}",
                )
        await interaction.response.send_message(result.message, ephemeral=True)

    async def _run_player_action(
        self,
        interaction: discord.Interaction,
        action: Any,
        *,
        public_success_action: str | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            result_or_awaitable = action(self._playback_service(), guild)
            result = (
                await result_or_awaitable
                if inspect.isawaitable(result_or_awaitable)
                else result_or_awaitable
            )
            await panel.refresh_locked(
                guild=guild,
                channel=cast(discord.abc.Messageable | None, interaction.channel),
                reason="slash_player_action",
            )
        if result.ok and public_success_action is not None:
            message = compact_player_action_ack(
                public_success_action,
                self.bot.player_states.get(guild.id),
                fallback=result.message,
            )
            refreshed_state = self.bot.player_states.get(guild.id)
            if refreshed_state is not None and refreshed_state.has_track:
                await interaction.response.send_message(
                    message,
                    ephemeral=False,
                    view=OpenControlPanelView(self.bot),
                )
            else:
                await interaction.response.send_message(message, ephemeral=False)
            return
        await interaction.response.send_message(result.message, ephemeral=True)

    async def _refresh_panel(self, interaction: discord.Interaction, *, reason: str) -> None:
        guild = interaction.guild
        if guild is None:
            return

        await NowPlayingPanelService(self.bot).refresh(
            guild=guild,
            channel=cast(discord.abc.Messageable | None, interaction.channel),
            reason=reason,
        )


async def setup(bot: WeaselBot) -> None:
    await bot.add_cog(MusicCog(bot))


def compact_playback_ack(action: str, track: object, *, detail: str | None = None) -> str:
    lines = [action, track_title(track)]
    metadata = compact_track_metadata(track)
    if metadata:
        lines.append(metadata)
    if detail:
        lines.append(detail)
    return "\n".join(lines)


def compact_track_metadata(track: object) -> str | None:
    local_track = cast(Any, track)
    parts = [
        str(value).strip()
        for value in (
            getattr(local_track, "artist_guess", None),
            getattr(local_track, "category_guess", None),
        )
        if value is not None and str(value).strip()
    ]
    return " • ".join(parts) if parts else None


def compact_player_action_ack(
    action: str,
    state: GuildPlayerState | None,
    *,
    fallback: str,
) -> str:
    if state is None or state.current_track is None:
        return f"{action}\n{fallback}"
    return compact_playback_ack(action, state.current_track)


MY_RATINGS_PAGE_SIZE = 10
RATING_VALUES = ("like", "superlike", "dislike", "superdislike")


def format_my_ratings(
    *,
    ratings: RatingRepository,
    bot: object,
    guild_id: int,
    user_id: int,
    rating_filter: str,
    page: int,
) -> str:
    normalized_filter = rating_filter.casefold()
    if normalized_filter not in ("all", *RATING_VALUES):
        return "Unknown rating filter. Use all, like, superlike, dislike, or superdislike."

    counts = ratings.counts_for_user(guild_id, user_id)
    total = _rating_total(counts)
    summary = [
        "Your ratings",
        f"Total rated tracks: {total}",
        f"Like: {counts.like}",
        f"SuperLike: {counts.superlike}",
        f"Dislike: {counts.dislike}",
        f"SuperDislike: {counts.superdislike}",
    ]
    if total == 0:
        return "\n".join([*summary, "", "You have not rated any tracks in this server yet."])

    filtered_total = total if normalized_filter == "all" else getattr(counts, normalized_filter)
    if filtered_total == 0:
        return "\n".join(
            [
                *summary,
                "",
                f"No {normalized_filter} ratings found for you in this server.",
            ]
        )

    max_page = max(1, (filtered_total + MY_RATINGS_PAGE_SIZE - 1) // MY_RATINGS_PAGE_SIZE)
    if page > max_page:
        return "\n".join(
            [
                *summary,
                "",
                f"Page {page} is outside the available range. Last page: {max_page}.",
            ]
        )

    rows = ratings.list_user_ratings(
        guild_id=guild_id,
        user_id=user_id,
        rating=None if normalized_filter == "all" else normalized_filter,
        limit=MY_RATINGS_PAGE_SIZE,
        offset=(page - 1) * MY_RATINGS_PAGE_SIZE,
    )
    lines = [*summary, "", f"Page {page}/{max_page}"]
    lines.extend(_format_user_rating_row(bot, row) for row in rows)
    return "\n".join(lines)


def _rating_total(counts: RatingCounts) -> int:
    return counts.like + counts.superlike + counts.dislike + counts.superdislike


def _format_user_rating_row(bot: object, row: UserTrackRating) -> str:
    icon = resolve_rating_text_emoji(bot, row.rating, _rating_fallback(row.rating))
    title = track_title(row.track)
    context = _safe_rating_track_context(row.track)
    suffix = f" — {context}" if context else ""
    return f"- {icon} {title}{suffix}"


def _rating_fallback(rating: str) -> str:
    return {
        "like": "❤️",
        "superlike": "💎",
        "dislike": "👎",
        "superdislike": "💀",
    }.get(rating, rating)


def _safe_rating_track_context(track: object) -> str:
    local_track = cast(Any, track)
    artist = display_artist_for_track(local_track)
    category = str(getattr(local_track, "category_guess", "") or "").strip()
    if category and category != artist:
        return f"{artist} • {category}"
    return artist


def format_purge_preview(preview: PurgePreview) -> str:
    lines = [
        "SuperDislike quarantine preview",
        f"Eligible tracks: {len(preview.eligible)}",
        f"Already quarantined: {preview.already_quarantined}",
        f"Destination: {preview.destination}",
        "Execution moves shared library files into reversible quarantine.",
    ]
    if preview.eligible:
        lines.append("Sample:")
        lines.extend(f"- {track_title(track)}" for track in preview.eligible[:10])
    if preview.cannot_move:
        lines.append("Cannot move:")
        lines.extend(f"- {item}" for item in preview.cannot_move[:10])
    return "\n".join(lines)


def format_quarantine_result(result: QuarantineMoveResult) -> str:
    lines = [
        "SuperDislike quarantine complete",
        f"Moved: {result.moved}",
        f"Skipped: {result.skipped}",
        f"Already quarantined: {result.already_quarantined}",
        f"Failed: {result.failed}",
        f"Removed from future queues: {result.removed_from_queue}",
    ]
    if result.failures:
        lines.append("Failures:")
        lines.extend(f"- {failure}" for failure in result.failures[:10])
    return "\n".join(lines)


def format_quarantine_list(records: Sequence[QuarantineRecord], tracks: TrackRepository) -> str:
    if not records:
        return "No quarantine records found."
    lines = ["Recent quarantine records:"]
    for record in records:
        track = tracks.get(record.track_id)
        title = track_title(track) if track is not None else f"Track {record.track_id}"
        metadata = compact_track_metadata(track) if track is not None else None
        suffix = f" — {metadata}" if metadata else ""
        lines.append(
            f"#{record.id} {title}{suffix} | {record.state} | "
            f"{record.quarantined_at or 'unknown date'}"
        )
    return "\n".join(lines)


def _track_has_superdislike(database: object, guild_id: int, track_id: int) -> bool:
    return track_id in RatingRepository(cast(Any, database)).track_ids_for_rating(
        guild_id,
        "superdislike",
    )


def prepare_play_all_session(state: GuildPlayerState, guild: object) -> bool:
    """Return True when /play_all should append to an active session."""
    if state.has_track and getattr(guild, "voice_client", None) is not None:
        return True
    state.clear_all()
    return False
