from __future__ import annotations

from weasel_bot_v2.models import Track
from weasel_bot_v2.services.player_state import (
    DEFAULT_VOLUME,
    MAX_VOLUME,
    MIN_VOLUME,
    GuildPlayerState,
    PlayerStateStore,
    clamp_volume,
)


def test_clamp_volume_bounds_values() -> None:
    assert clamp_volume(-10) == MIN_VOLUME
    assert clamp_volume(75) == 75
    assert clamp_volume(999) == MAX_VOLUME


def test_player_state_updates_current_track_and_pause_state() -> None:
    state = GuildPlayerState(guild_id=123, paused=True)
    track = _track("Artist/song.mp3")

    state.set_current_track(track)

    assert state.current_track == track
    assert state.has_track is True
    assert state.paused is False


def test_player_state_clears_current_track_safely() -> None:
    state = GuildPlayerState(guild_id=123, current_track=_track("song.mp3"), loop_current=True)

    state.clear_current_track()

    assert state.current_track is None
    assert state.has_track is False
    assert state.paused is False
    assert state.loop_current is False


def test_player_state_volume_changes_are_clamped() -> None:
    state = GuildPlayerState(guild_id=123)

    assert state.volume == DEFAULT_VOLUME
    assert state.change_volume(150) == MAX_VOLUME
    assert state.change_volume(-500) == MIN_VOLUME


def test_player_state_loop_toggle() -> None:
    state = GuildPlayerState(guild_id=123)

    assert state.toggle_loop() is True
    assert state.loop_current is True
    assert state.toggle_loop() is False
    assert state.loop_current is False


def test_player_state_store_returns_empty_state_when_no_track_active() -> None:
    store = PlayerStateStore()

    state = store.get_or_create(123)

    assert state.has_track is False
    assert store.get(456) is None


def test_player_state_store_clear_is_safe_without_active_track() -> None:
    store = PlayerStateStore()

    store.clear(123)

    assert store.get(123) is not None
    assert store.get_or_create(123).has_track is False


def _track(relative_path: str) -> Track:
    return Track(
        source="local",
        source_id=relative_path,
        relative_path=relative_path,
        file_name=relative_path.rsplit("/", maxsplit=1)[-1],
        display_title="Test Track",
    )
