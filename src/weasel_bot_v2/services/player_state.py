from __future__ import annotations

from dataclasses import dataclass

from weasel_bot_v2.models import Track

MIN_VOLUME = 0
MAX_VOLUME = 200
DEFAULT_VOLUME = 100
VOLUME_STEP = 10


@dataclass
class GuildPlayerState:
    guild_id: int
    current_track: Track | None = None
    paused: bool = False
    volume: int = DEFAULT_VOLUME
    loop_current: bool = False

    @property
    def has_track(self) -> bool:
        return self.current_track is not None

    def set_current_track(self, track: Track) -> None:
        self.current_track = track
        self.paused = False

    def clear_current_track(self) -> None:
        self.current_track = None
        self.paused = False
        self.loop_current = False

    def set_volume(self, volume: int) -> int:
        self.volume = clamp_volume(volume)
        return self.volume

    def change_volume(self, delta: int) -> int:
        return self.set_volume(self.volume + delta)

    def toggle_loop(self) -> bool:
        self.loop_current = not self.loop_current
        return self.loop_current


class PlayerStateStore:
    def __init__(self) -> None:
        self._states: dict[int, GuildPlayerState] = {}

    def get_or_create(self, guild_id: int) -> GuildPlayerState:
        state = self._states.get(guild_id)
        if state is None:
            state = GuildPlayerState(guild_id=guild_id)
            self._states[guild_id] = state
        return state

    def get(self, guild_id: int) -> GuildPlayerState | None:
        return self._states.get(guild_id)

    def clear(self, guild_id: int) -> None:
        state = self.get_or_create(guild_id)
        state.clear_current_track()


def clamp_volume(volume: int) -> int:
    return min(MAX_VOLUME, max(MIN_VOLUME, volume))
