"""Repository classes for SQLite-backed persistence."""

from weasel_bot_v2.repositories.guild_settings import GuildSettingsRepository
from weasel_bot_v2.repositories.history import HistoryRepository
from weasel_bot_v2.repositories.playlists import PlaylistRepository
from weasel_bot_v2.repositories.quarantine import QuarantineRepository
from weasel_bot_v2.repositories.ratings import RatingRepository
from weasel_bot_v2.repositories.track_volume_overrides import TrackVolumeOverrideRepository
from weasel_bot_v2.repositories.tracks import TrackRepository
from weasel_bot_v2.repositories.users import UserRepository

__all__ = [
    "GuildSettingsRepository",
    "HistoryRepository",
    "PlaylistRepository",
    "QuarantineRepository",
    "RatingRepository",
    "TrackVolumeOverrideRepository",
    "TrackRepository",
    "UserRepository",
]
