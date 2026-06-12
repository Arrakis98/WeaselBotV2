from __future__ import annotations

from typing import Any, cast

import discord
from discord import app_commands
from discord.ext import commands

from weasel_bot_v2.bot import WeaselBot
from weasel_bot_v2.repositories import TrackRepository
from weasel_bot_v2.services.audio import AudioPlaybackService, PlaybackResult
from weasel_bot_v2.services.local_library import LocalLibraryService
from weasel_bot_v2.services.player_state import VOLUME_STEP, GuildPlayerState


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

        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        result = await playback.play_local_track(interaction=interaction, track=matches[0])
        await interaction.followup.send(result.message, ephemeral=True)
        if result.ok:
            await self._send_now_playing_panel(interaction)

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

        await interaction.response.send_message(
            embed=build_now_playing_embed(state),
            view=NowPlayingView(self.bot, state),
        )

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

        result = self._playback_service().clear_queue(guild.id)
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

        result = self._playback_service().remove_from_queue(guild.id, position)
        await interaction.response.send_message(result.message, ephemeral=True)

    def _library_service(self) -> LocalLibraryService:
        return LocalLibraryService(
            music_root=self.bot.settings.bot.music_library,
            tracks=TrackRepository(self.bot.database),
        )

    def _playback_service(self) -> AudioPlaybackService:
        return AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)

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

        result = await action(self._playback_service(), guild)
        await interaction.response.send_message(result.message, ephemeral=True)

    async def _send_now_playing_panel(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return

        state = self.bot.player_states.get(guild.id)
        if state is None or not state.has_track:
            return

        channel = cast(Any, interaction.channel)
        if channel is None or not hasattr(channel, "send"):
            return

        await channel.send(
            embed=build_now_playing_embed(state),
            view=NowPlayingView(self.bot, state),
        )


def build_now_playing_embed(state: GuildPlayerState) -> discord.Embed:
    track = state.current_track
    title = "Unknown local track"
    if track is not None:
        title = track.display_title or track.file_name or track.relative_path or title

    embed = discord.Embed(
        title="Now Playing",
        description=f"**{title}**",
        color=discord.Color.blurple(),
    )
    if track is not None and track.artist_guess:
        embed.add_field(name="Artist", value=track.artist_guess, inline=True)
    if track is not None and track.category_guess:
        embed.add_field(name="Category", value=track.category_guess, inline=True)
    embed.add_field(name="Status", value="Paused" if state.paused else "Playing", inline=True)
    embed.add_field(name="Volume", value=f"{state.volume}%", inline=True)
    embed.add_field(name="Loop", value="On" if state.loop_current else "Off", inline=True)
    embed.add_field(name="Queue", value=f"{state.queue_length} upcoming", inline=True)
    next_track = state.next_track_preview()
    embed.add_field(
        name="Next",
        value=track_title(next_track) if next_track is not None else "Nothing queued",
        inline=False,
    )
    embed.add_field(
        name="Previous",
        value="Available" if state.can_go_back else "None",
        inline=True,
    )
    if track is not None and track.relative_path:
        embed.set_footer(text=track.relative_path)
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


def track_title(track: object | None) -> str:
    if track is None:
        return "None"
    local_track = cast(Any, track)
    return (
        local_track.display_title
        or local_track.file_name
        or local_track.relative_path
        or "Unknown local track"
    )


class NowPlayingView(discord.ui.View):
    def __init__(self, bot: WeaselBot, state: GuildPlayerState) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self._update_button_state(state)

    @discord.ui.button(label="Pause / Resume", emoji="⏯️", style=discord.ButtonStyle.primary)
    async def pause_resume(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This control can only be used in a server.",
                ephemeral=True,
            )
            return

        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        state = self.bot.player_states.get(guild.id)
        if state is None or not state.has_track:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return

        result = await (playback.resume(guild) if state.paused else playback.pause(guild))
        await self._finish_control(interaction, result)

    @discord.ui.button(label="Back", emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This control can only be used in a server.",
                ephemeral=True,
            )
            return

        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        result = await playback.back(guild)
        await self._finish_control(interaction, result)

    @discord.ui.button(label="Skip", emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def skip_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This control can only be used in a server.",
                ephemeral=True,
            )
            return

        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        result = await playback.skip(guild)
        await self._finish_control(interaction, result)

    @discord.ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This control can only be used in a server.",
                ephemeral=True,
            )
            return

        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        result = await playback.stop(guild)
        await self._finish_control(interaction, result)

    @discord.ui.button(label="Volume Down", emoji="🔉", style=discord.ButtonStyle.secondary)
    async def volume_down(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        await self._volume(interaction, -VOLUME_STEP)

    @discord.ui.button(label="Volume Up", emoji="🔊", style=discord.ButtonStyle.secondary)
    async def volume_up(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        await self._volume(interaction, VOLUME_STEP)

    @discord.ui.button(label="Loop", emoji="🔁", style=discord.ButtonStyle.secondary)
    async def loop_current(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[NowPlayingView],
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This control can only be used in a server.",
                ephemeral=True,
            )
            return

        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        result = playback.toggle_loop(guild.id)
        await self._finish_control(interaction, result)

    async def _volume(self, interaction: discord.Interaction, delta: int) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This control can only be used in a server.",
                ephemeral=True,
            )
            return

        playback = AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)
        result = await playback.change_volume(guild, delta)
        await self._finish_control(interaction, result)

    async def _finish_control(
        self,
        interaction: discord.Interaction,
        result: PlaybackResult,
    ) -> None:
        guild = interaction.guild
        state = self.bot.player_states.get(guild.id) if guild is not None else None
        if result.ok and state is not None and state.has_track:
            self._update_button_state(state)
            await interaction.response.edit_message(
                embed=build_now_playing_embed(state),
                view=self,
            )
            return

        await interaction.response.send_message(result.message, ephemeral=True)

    def _update_button_state(self, state: GuildPlayerState) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.label == "Loop":
                    item.style = (
                        discord.ButtonStyle.success
                        if state.loop_current
                        else discord.ButtonStyle.secondary
                    )


async def setup(bot: WeaselBot) -> None:
    await bot.add_cog(MusicCog(bot))
