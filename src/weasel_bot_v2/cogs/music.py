from __future__ import annotations

import random
from typing import Any, cast

import discord
from discord import app_commands
from discord.ext import commands

from weasel_bot_v2.bot import WeaselBot
from weasel_bot_v2.repositories import (
    GuildSettingsRepository,
    RatingRepository,
    TrackRepository,
    UserRepository,
)
from weasel_bot_v2.services.audio import AudioPlaybackService
from weasel_bot_v2.services.guild_settings import GuildSettingsService
from weasel_bot_v2.services.local_library import LocalLibraryService
from weasel_bot_v2.services.now_playing_panel import (
    NowPlayingPanelService,
    format_queue,
    track_title,
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
        await interaction.response.defer(ephemeral=True, thinking=True)
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
            result = await playback.play_local_track(interaction=interaction, track=matches[0])
            if result.ok:
                await panel.refresh_locked(
                    guild=guild,
                    channel=cast(discord.abc.Messageable | None, interaction.channel),
                    reason="play_local",
                )
        await interaction.followup.send(result.message, ephemeral=True)

    @app_commands.command(
        name="play_all",
        description="Shuffle all indexed local MP3 tracks into the playback queue.",
    )
    async def play_all(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        library = self._library_service()
        tracks = library.list_indexed_mp3_tracks()
        if not tracks:
            await interaction.followup.send(
                "No indexed local MP3 tracks found. Run /library_scan first.",
                ephemeral=True,
            )
            return

        random.shuffle(tracks)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        playback = self._playback_service()
        found_count = len(tracks)
        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            state = self.bot.player_states.get_or_create(guild.id)
            if state.has_track:
                start_position, queued_count = state.enqueue_many(tracks)
                await panel.refresh_locked(
                    guild=guild,
                    channel=cast(discord.abc.Messageable | None, interaction.channel),
                    reason="play_all:enqueue",
                )
                message = (
                    f"Found {found_count} indexed MP3 tracks. "
                    f"Added {queued_count} to the queue starting at position {start_position}. "
                    f"Queue length is now {state.queue_length}."
                )
                await interaction.followup.send(message, ephemeral=True)
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
                f"Found {found_count} indexed MP3 tracks. "
                f"Now playing: {track_title(first)}. "
                f"Queued {len(remaining)} more track(s). "
                f"Queue length is now {state.queue_length}."
            ),
            ephemeral=True,
        )

    @app_commands.command(name="pause", description="Pause the current local track.")
    async def pause_track(self, interaction: discord.Interaction) -> None:
        await self._run_player_action(interaction, lambda service, guild: service.pause(guild))

    @app_commands.command(name="resume", description="Resume the current local track.")
    async def resume_track(self, interaction: discord.Interaction) -> None:
        await self._run_player_action(interaction, lambda service, guild: service.resume(guild))

    @app_commands.command(name="stop", description="Stop playback and stay in voice.")
    async def stop_track(self, interaction: discord.Interaction) -> None:
        await self._run_player_action(interaction, lambda service, guild: service.stop(guild))

    @app_commands.command(name="leave", description="Stop playback and leave voice.")
    async def leave_voice(self, interaction: discord.Interaction) -> None:
        await self._run_player_action(interaction, lambda service, guild: service.leave(guild))

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
            state = self.bot.player_states.get(guild.id)
            volume = (
                state.volume
                if state is not None
                else GuildSettingsService(GuildSettingsRepository(self.bot.database)).get_volume(
                    guild.id
                )
            )
            await interaction.response.send_message(f"Volume: {volume}%", ephemeral=True)
            return

        panel = NowPlayingPanelService(self.bot)
        async with panel.lock_for(guild.id):
            result = await self._playback_service().set_volume(guild, percent)
            await panel.refresh_locked(
                guild=guild,
                channel=cast(discord.abc.Messageable | None, interaction.channel),
                reason="volume",
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
        await self._run_player_action(interaction, lambda service, guild: service.skip(guild))

    @app_commands.command(name="back", description="Go back to the previous local track.")
    async def back_track(self, interaction: discord.Interaction) -> None:
        await self._run_player_action(interaction, lambda service, guild: service.back(guild))

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
            state = self.bot.player_states.get(guild.id)
            result = self._rating_service().rate_current_track(
                state=state,
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
            result = await action(self._playback_service(), guild)
            await panel.refresh_locked(
                guild=guild,
                channel=cast(discord.abc.Messageable | None, interaction.channel),
                reason="slash_player_action",
            )
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
