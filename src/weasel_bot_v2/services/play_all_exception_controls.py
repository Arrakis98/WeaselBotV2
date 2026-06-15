from __future__ import annotations

from typing import Any

import discord

from weasel_bot_v2.models import Track
from weasel_bot_v2.repositories import PlayAllPolicyRepository, TrackRepository, UserRepository
from weasel_bot_v2.services.application_emojis import ApplicationEmojiRegistry
from weasel_bot_v2.services.local_library import LocalLibraryService
from weasel_bot_v2.services.play_all_policy import PlayAllPolicyService, TrackExceptionResult

PLAY_ALL_EXCEPTION_PERMISSION_ERROR = (
    "Only an administrator or bot owner can manage /play_all exceptions."
)


def play_all_policy_service(bot: Any) -> PlayAllPolicyService:
    return PlayAllPolicyService(
        policy=PlayAllPolicyRepository(bot.database),
        tracks=TrackRepository(bot.database),
        users=UserRepository(bot.database),
        library=LocalLibraryService(bot.settings.bot.music_library, TrackRepository(bot.database)),
    )


def current_track_can_toggle_play_all_exception(track: Track | None) -> bool:
    return (
        track is not None
        and track.source == "local"
        and track.id is not None
        and track.is_available
    )


def current_track_has_play_all_exception(
    bot: Any,
    *,
    guild_id: int,
    track: Track | None,
) -> bool:
    if not current_track_can_toggle_play_all_exception(track):
        return False
    try:
        return play_all_policy_service(bot).has_track_exception(guild_id=guild_id, track=track)
    except Exception:  # noqa: BLE001 - unsafe resolution disables the UI affordance.
        return False


def play_all_exception_button_disabled(
    bot: Any,
    *,
    guild_id: int,
    track: Track | None,
) -> bool:
    if not current_track_can_toggle_play_all_exception(track):
        return True
    try:
        play_all_policy_service(bot).has_track_exception(guild_id=guild_id, track=track)
    except Exception:  # noqa: BLE001 - avoid exposing a button that cannot safely resolve.
        return True
    return False


def resolve_play_all_exception_emoji(
    bot: Any | None,
    *,
    guild_id: int,
    track: Track | None,
) -> discord.PartialEmoji | str:
    registry = getattr(bot, "application_emoji_registry", None)
    if not isinstance(registry, ApplicationEmojiRegistry):
        registry = ApplicationEmojiRegistry.empty()
    has_exception = (
        current_track_has_play_all_exception(bot, guild_id=guild_id, track=track)
        if bot is not None
        else False
    )
    key = "playall_exception_remove" if has_exception else "playall_exception_add"
    fallback = "➖" if has_exception else "➕"
    resolved = registry.resolve_button(key, fallback)
    return resolved if resolved is not None else fallback


def toggle_current_play_all_exception(
    bot: Any,
    *,
    guild_id: int,
    user_id: int,
    display_name: str | None,
    track: Track | None,
) -> TrackExceptionResult:
    return play_all_policy_service(bot).toggle_current_track_exception(
        guild_id=guild_id,
        user_id=user_id,
        display_name=display_name,
        track=track,
    )


async def can_manage_play_all_exceptions(bot: Any, interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    if bool(getattr(permissions, "administrator", False)):
        return True
    try:
        app_info = await bot.application_info()
    except Exception:  # noqa: BLE001 - fall back to guild administrator.
        return False
    owner = getattr(app_info, "owner", None)
    return getattr(owner, "id", None) == interaction.user.id
