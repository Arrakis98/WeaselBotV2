from __future__ import annotations

from weasel_bot_v2.cogs.music import format_queue
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


def test_start_or_enqueue_plays_immediately_when_idle() -> None:
    state = GuildPlayerState(guild_id=123)
    track = _track("first.mp3")

    action, position = state.start_or_enqueue(track)

    assert action == "started"
    assert position is None
    assert state.current_track == track
    assert state.queue_length == 0


def test_start_or_enqueue_adds_to_queue_when_already_playing() -> None:
    state = GuildPlayerState(guild_id=123, current_track=_track("first.mp3"))
    second = _track("second.mp3")

    action, position = state.start_or_enqueue(second)

    assert action == "queued"
    assert position == 1
    assert state.current_track is not None
    assert state.upcoming == [second]


def test_start_or_enqueue_many_empty_library_behavior() -> None:
    state = GuildPlayerState(guild_id=123)

    action, current, queued_count = state.start_or_enqueue_many([])

    assert action == "empty"
    assert current is None
    assert queued_count == 0
    assert state.current_track is None
    assert state.queue_length == 0


def test_start_or_enqueue_many_idle_starts_first_and_queues_rest() -> None:
    first = _track("first.mp3")
    second = _track("second.mp3")
    third = _track("third.mp3")
    state = GuildPlayerState(guild_id=123)

    action, current, queued_count = state.start_or_enqueue_many([first, second, third])

    assert action == "started"
    assert current == first
    assert queued_count == 2
    assert state.current_track == first
    assert state.upcoming == [second, third]
    assert state.queue_length == 2


def test_start_or_enqueue_many_active_queues_all_without_replacing_current() -> None:
    current = _track("current.mp3")
    first = _track("first.mp3")
    second = _track("second.mp3")
    state = GuildPlayerState(guild_id=123, current_track=current)

    action, started, queued_count = state.start_or_enqueue_many([first, second])

    assert action == "queued"
    assert started is None
    assert queued_count == 2
    assert state.current_track == current
    assert state.upcoming == [first, second]
    assert state.queue_length == 2


def test_enqueue_many_returns_start_position_and_count() -> None:
    state = GuildPlayerState(guild_id=123, upcoming=[_track("existing.mp3")])

    start_position, queued_count = state.enqueue_many([
        _track("first.mp3"),
        _track("second.mp3"),
    ])

    assert start_position == 2
    assert queued_count == 2
    assert state.queue_length == 3


def test_skip_with_next_track_moves_current_to_history() -> None:
    first = _track("first.mp3")
    second = _track("second.mp3")
    state = GuildPlayerState(guild_id=123, current_track=first, upcoming=[second])

    next_track = state.skip_to_next()

    assert next_track == second
    assert state.current_track == second
    assert state.recently_played == [first]
    assert state.upcoming == []


def test_skip_with_empty_queue_clears_current_track() -> None:
    state = GuildPlayerState(guild_id=123, current_track=_track("first.mp3"))

    next_track = state.skip_to_next()

    assert next_track is None
    assert state.current_track is None
    assert state.has_track is False


def test_back_with_previous_track_moves_current_to_front_of_queue() -> None:
    first = _track("first.mp3")
    second = _track("second.mp3")
    state = GuildPlayerState(guild_id=123, current_track=second, recently_played=[first])

    previous = state.back_to_previous()

    assert previous == first
    assert state.upcoming == [second]
    assert state.recently_played == []


def test_back_without_previous_track_is_safe() -> None:
    state = GuildPlayerState(guild_id=123, current_track=_track("first.mp3"))

    assert state.back_to_previous() is None


def test_clear_queue_returns_removed_count() -> None:
    state = GuildPlayerState(
        guild_id=123,
        current_track=_track("first.mp3"),
        upcoming=[_track("second.mp3"), _track("third.mp3")],
    )

    assert state.clear_queue() == 2
    assert state.upcoming == []


def test_remove_queue_item_by_position() -> None:
    second = _track("second.mp3")
    third = _track("third.mp3")
    state = GuildPlayerState(guild_id=123, upcoming=[second, third])

    assert state.remove_queue_item(2) == third
    assert state.upcoming == [second]
    assert state.remove_queue_item(2) is None
    assert state.remove_queue_item(0) is None


def test_queue_display_formatting() -> None:
    state = GuildPlayerState(
        guild_id=123,
        current_track=_track("first.mp3"),
        upcoming=[_track("second.mp3")],
    )

    message = format_queue(state)

    assert "Now playing: Test Track" in message
    assert "1. Test Track" in message


def _track(relative_path: str) -> Track:
    return Track(
        source="local",
        source_id=relative_path,
        relative_path=relative_path,
        file_name=relative_path.rsplit("/", maxsplit=1)[-1],
        display_title="Test Track",
    )
