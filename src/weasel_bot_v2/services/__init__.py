"""Service classes that hold bot business workflows."""

from weasel_bot_v2.services.audio import AudioPlaybackService
from weasel_bot_v2.services.guild_settings import GuildSettingsService
from weasel_bot_v2.services.history import HistoryService
from weasel_bot_v2.services.local_library import LocalLibraryService
from weasel_bot_v2.services.playlists import PlaylistService
from weasel_bot_v2.services.ratings import RatingService
from weasel_bot_v2.services.tracks import TrackService
from weasel_bot_v2.services.users import UserService

__all__ = [
    "GuildSettingsService",
    "AudioPlaybackService",
    "HistoryService",
    "LocalLibraryService",
    "PlaylistService",
    "RatingService",
    "TrackService",
    "UserService",
]
