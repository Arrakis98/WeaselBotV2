from __future__ import annotations

from typing import Any

import discord

from weasel_bot_v2.repositories import RatingRepository, UserRepository
from weasel_bot_v2.services.audio import AudioPlaybackService, PlaybackResult
from weasel_bot_v2.services.quarantine import QuarantineService
from weasel_bot_v2.services.ratings import RATINGS_THAT_SKIP, RatingService


class PlayerActionService:
    def __init__(self, bot: Any) -> None:
        self.bot = bot

    async def rate_current_track(
        self,
        *,
        guild: discord.Guild,
        user_id: int,
        display_name: str | None,
        rating_value: str,
    ) -> PlaybackResult:
        state = self.bot.player_states.get(guild.id)
        captured_track = state.current_track if state is not None else None
        rating_result = self._rating_service().rate_current_track(
            state=state,
            user_id=user_id,
            display_name=display_name,
            rating_value=rating_value,
        )
        if not rating_result.ok:
            return PlaybackResult(ok=False, message=rating_result.message)

        if rating_value not in RATINGS_THAT_SKIP:
            return PlaybackResult(ok=True, message=rating_result.message)

        skip_result = await self._playback_service().skip(guild)
        message = f"{rating_result.message} {skip_result.message}"
        moderation = getattr(self.bot.settings, "library_moderation", None)
        auto_quarantine = bool(getattr(moderation, "auto_quarantine_superdislike", False))
        if rating_value == "superdislike" and auto_quarantine and captured_track is not None:
            quarantine_result = QuarantineService(self.bot).quarantine_track(
                captured_track,
                guild_id=guild.id,
                requested_by_user_id=user_id,
                reason="auto_superdislike",
            )
            if quarantine_result.moved:
                message = f"{message} Quarantined from the playable library."
            elif quarantine_result.failed:
                message = f"{message} Quarantine failed; rating and skip were kept."
        return PlaybackResult(
            ok=True,
            message=message,
        )

    def _playback_service(self) -> AudioPlaybackService:
        return AudioPlaybackService(self.bot, self.bot.settings.bot.music_library)

    def _rating_service(self) -> RatingService:
        return RatingService(
            ratings=RatingRepository(self.bot.database),
            users=UserRepository(self.bot.database),
        )
