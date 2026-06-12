from __future__ import annotations

from dataclasses import dataclass, field

from weasel_bot_v2.models import Track

MIN_VOLUME = 0
MAX_VOLUME = 200
DEFAULT_VOLUME = 100
VOLUME_STEP = 10


@dataclass
class GuildPlayerState:
    guild_id: int
    current_track: Track | None = None
    upcoming: list[Track] = field(default_factory=list)
    recently_played: list[Track] = field(default_factory=list)
    paused: bool = False
    volume: int = DEFAULT_VOLUME
    loop_current: bool = False

    @property
    def has_track(self) -> bool:
        return self.current_track is not None

    def set_current_track(self, track: Track) -> None:
        if self.current_track is not None:
            self.recently_played.append(self.current_track)
        self.current_track = track
        self.paused = False

    def clear_current_track(self) -> None:
        self.current_track = None
        self.paused = False
        self.loop_current = False

    def clear_all(self) -> None:
        self.clear_current_track()
        self.upcoming.clear()
        self.recently_played.clear()

    def enqueue(self, track: Track) -> int:
        self.upcoming.append(track)
        return len(self.upcoming)

    def start_or_enqueue(self, track: Track) -> tuple[str, int | None]:
        if self.current_track is None:
            self.set_current_track(track)
            return "started", None
        position = self.enqueue(track)
        return "queued", position

    def pop_next(self) -> Track | None:
        if not self.upcoming:
            return None
        return self.upcoming.pop(0)

    def skip_to_next(self) -> Track | None:
        next_track = self.pop_next()
        if next_track is None:
            self.clear_current_track()
            return None
        self.set_current_track(next_track)
        return next_track

    def back_to_previous(self) -> Track | None:
        if not self.recently_played:
            return None
        if self.current_track is not None:
            self.upcoming.insert(0, self.current_track)
        return self.recently_played.pop()

    def clear_queue(self) -> int:
        cleared = len(self.upcoming)
        self.upcoming.clear()
        return cleared

    def remove_queue_item(self, position: int) -> Track | None:
        if position < 1 or position > len(self.upcoming):
            return None
        return self.upcoming.pop(position - 1)

    @property
    def queue_length(self) -> int:
        return len(self.upcoming)

    @property
    def can_go_back(self) -> bool:
        return bool(self.recently_played)

    def next_track_preview(self) -> Track | None:
        return self.upcoming[0] if self.upcoming else None

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
        state.clear_all()


def clamp_volume(volume: int) -> int:
    return min(MAX_VOLUME, max(MIN_VOLUME, volume))
