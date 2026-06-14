from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from weasel_bot_v2.models import Track, TrackVolumeOverride
from weasel_bot_v2.repositories import GuildSettingsRepository, TrackVolumeOverrideRepository
from weasel_bot_v2.services.guild_settings import GuildSettingsService
from weasel_bot_v2.services.player_state import DEFAULT_VOLUME, clamp_volume


class VolumeSource(StrEnum):
    TRACK = "track"
    DEFAULT = "default"


@dataclass(frozen=True)
class ResolvedVolume:
    volume: int
    source: VolumeSource
    guild_default: int
    track_id: int | None = None

    @property
    def source_label(self) -> str:
        return "track preset" if self.source is VolumeSource.TRACK else "default"


class VolumeService:
    def __init__(
        self,
        guild_settings: GuildSettingsRepository,
        track_overrides: TrackVolumeOverrideRepository,
    ) -> None:
        self.guild_settings = GuildSettingsService(guild_settings)
        self.track_overrides = track_overrides

    def get_guild_default(self, guild_id: int) -> int:
        return self.guild_settings.get_volume(guild_id)

    def set_guild_default(self, guild_id: int, volume: int) -> int:
        return self.guild_settings.set_volume(guild_id, volume)

    def get_track_override(
        self,
        guild_id: int,
        track_id: int,
    ) -> TrackVolumeOverride | None:
        return self.track_overrides.get(guild_id, track_id)

    def set_track_override(
        self,
        guild_id: int,
        track_id: int,
        volume: int,
    ) -> TrackVolumeOverride:
        return self.track_overrides.save(guild_id, track_id, clamp_volume(volume))

    def remove_track_override(self, guild_id: int, track_id: int) -> bool:
        return self.track_overrides.delete(guild_id, track_id)

    def resolve(self, guild_id: int, track: Track | None) -> ResolvedVolume:
        if track is not None and track.id is not None:
            override = self.get_track_override(guild_id, track.id)
            if override is not None:
                return ResolvedVolume(
                    volume=clamp_volume(override.volume),
                    source=VolumeSource.TRACK,
                    guild_default=DEFAULT_VOLUME,
                    track_id=track.id,
                )

        return ResolvedVolume(
            volume=DEFAULT_VOLUME,
            source=VolumeSource.DEFAULT,
            guild_default=DEFAULT_VOLUME,
            track_id=track.id if track is not None else None,
        )
