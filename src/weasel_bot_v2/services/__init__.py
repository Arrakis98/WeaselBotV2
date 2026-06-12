"""Service classes that hold bot business workflows."""

from weasel_bot_v2.services.guild_settings import GuildSettingsService
from weasel_bot_v2.services.history import HistoryService
from weasel_bot_v2.services.playlists import PlaylistService
from weasel_bot_v2.services.ratings import RatingService
from weasel_bot_v2.services.tracks import TrackService
from weasel_bot_v2.services.users import UserService

__all__ = [
    "GuildSettingsService",
    "HistoryService",
    "PlaylistService",
    "RatingService",
    "TrackService",
    "UserService",
]
