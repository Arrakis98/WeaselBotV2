from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import discord
import pytest

from weasel_bot_v2.cogs.music import MusicCog
from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Rating, Track, UserRecord
from weasel_bot_v2.repositories import (
    PlayAllPolicyRepository,
    RatingRepository,
    TrackRepository,
    TrackVolumeOverrideRepository,
    UserRepository,
)
from weasel_bot_v2.services.application_emojis import ApplicationEmojiRegistry
from weasel_bot_v2.services.control_center import (
    AdvancedActionsView,
    AdvancedConfirmationView,
    ControlCenterService,
    ControlCenterView,
    OpenControlPanelView,
    control_center_custom_ids,
)
from weasel_bot_v2.services.now_playing_panel import NowPlayingPanelRecord, NowPlayingPanelRegistry
from weasel_bot_v2.services.player_state import PlayerStateStore


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    sqlite_database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel-test.db"))
    sqlite_database.initialize()
    return sqlite_database


@pytest.mark.asyncio
async def test_controls_command_creates_ephemeral_control_center(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=None)
    interaction = _FakeInteraction(guild=guild)

    await _run_slash(MusicCog(cast(Any, bot)), "controls", interaction)

    assert interaction.response_ephemeral == [True]
    assert "WEASEL GALAXY CONTROL CENTER" in interaction.response_messages[0]
    assert isinstance(interaction.response_views[0], ControlCenterView)


@pytest.mark.asyncio
async def test_open_control_panel_button_opens_fresh_ephemeral_state(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=None)
    first = _indexed_track(database, "Artist/first.mp3")
    second = _indexed_track(database, "Artist/second.mp3")
    bot.player_states.get_or_create(123).current_track = first
    view = OpenControlPanelView(bot)
    button = cast(discord.ui.Button[Any], view.children[0])
    interaction = _FakeInteraction(guild=guild)
    bot.player_states.get_or_create(123).current_track = second

    await button.callback(interaction)  # type: ignore[misc]

    assert interaction.response_ephemeral == [True]
    assert "second" in interaction.response_messages[0]
    assert "first" not in interaction.response_messages[0]
    assert isinstance(interaction.response_views[0], ControlCenterView)


def test_idle_control_center_disables_unavailable_controls(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=None)
    snapshot = ControlCenterService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    view = ControlCenterView(bot, snapshot)
    enabled_ids = [
        item.custom_id
        for item in view.children
        if isinstance(item, discord.ui.Button) and not item.disabled
    ]
    disabled_ids = [
        item.custom_id
        for item in view.children
        if isinstance(item, discord.ui.Button) and item.disabled
    ]

    assert enabled_ids == ["weasel:controls:queue", "weasel:controls:more"]
    assert "weasel:controls:skip" in disabled_ids
    assert "weasel:controls:like" in disabled_ids
    assert "weasel:controls:playall_exception" in disabled_ids


@pytest.mark.asyncio
async def test_more_actions_navigation_and_disabled_idle_state(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=None)
    interaction = _FakeInteraction(guild=guild)

    await ControlCenterService(bot).run_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "more",
    )

    view = interaction.edited_views[0]
    assert isinstance(view, AdvancedActionsView)
    enabled = _button_labels(view)
    assert enabled == ["Back to Control Center"]


@pytest.mark.asyncio
async def test_more_actions_return_to_control_center_uses_fresh_state(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=None)
    interaction = _FakeInteraction(guild=guild)
    bot.player_states.get_or_create(123).current_track = _indexed_track(
        database,
        "Artist/fresh.mp3",
    )

    await ControlCenterService(bot).run_advanced_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "back_to_controls",
    )

    assert "fresh" in interaction.edited_messages[0]
    assert isinstance(interaction.edited_views[0], ControlCenterView)


@pytest.mark.asyncio
async def test_more_actions_clear_queue_requires_confirmation_and_preserves_current(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=object())
    interaction = _FakeInteraction(guild=guild)
    current = _indexed_track(database, "Artist/current.mp3")
    queued = _indexed_track(database, "Artist/queued.mp3")
    state = bot.player_states.get_or_create(123)
    state.current_track = current
    state.upcoming = [queued]

    await ControlCenterService(bot).run_advanced_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "clear_queue",
    )
    assert isinstance(interaction.edited_views[0], AdvancedConfirmationView)

    await ControlCenterService(bot).run_advanced_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "clear_queue",
        confirmed=True,
    )

    assert state.current_track == current
    assert state.upcoming == []
    assert interaction.edit_count == 1
    assert len(interaction.followup_messages) == 1
    assert "More Actions" in interaction.followup_messages[0]
    assert "Cleared 1 queued track(s)." in interaction.followup_messages[0]


@pytest.mark.asyncio
async def test_more_actions_leave_reuses_hard_reset(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    player = _FakePlayer()
    guild = _FakeGuild(guild_id=123, voice_client=player)
    interaction = _FakeInteraction(guild=guild)
    bot.player_states.get_or_create(123).current_track = _indexed_track(
        database,
        "Artist/current.mp3",
    )

    await ControlCenterService(bot).run_advanced_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "leave",
        confirmed=True,
    )

    assert player.stop_count == 1
    assert player.disconnected is True
    assert bot.player_states.get_or_create(123).current_track is None
    assert interaction.edit_count == 1


@pytest.mark.asyncio
async def test_more_actions_reset_track_volume_reuses_existing_reset_action(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    player = _FakePlayer()
    guild = _FakeGuild(guild_id=123, voice_client=player)
    interaction = _FakeInteraction(guild=guild)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current
    bot.player_states.get_or_create(123).set_volume(140)
    overrides = TrackVolumeOverrideRepository(database)
    overrides.save(123, current.id, 140)

    await ControlCenterService(bot).run_advanced_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "reset_volume",
    )

    assert overrides.get(123, current.id) is None
    assert bot.player_states.get_or_create(123).volume == 100
    assert player.volumes == [100]
    assert interaction.edit_count == 1
    assert "Track volume reset to default: 100%" in interaction.edited_messages[0]
    assert isinstance(interaction.edited_views[0], AdvancedActionsView)


def test_more_actions_show_add_or_remove_play_all_exception(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=None)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current
    snapshot = ControlCenterService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    add_view = AdvancedActionsView(bot, snapshot)
    add_labels = _button_labels(add_view)
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Listener"))
    _store_exception(database, track_id=current.id)
    remove_view = AdvancedActionsView(bot, snapshot)
    remove_labels = _button_labels(remove_view)

    assert "Add Play All Exception" in add_labels
    assert "Remove Play All Exception" in remove_labels


@pytest.mark.asyncio
async def test_more_actions_toggle_adds_and_removes_play_all_exception(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=None)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current
    interaction = _FakeInteraction(guild=guild)
    policy = PlayAllPolicyRepository(database)

    await ControlCenterService(bot).run_advanced_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "toggle_playall_exception",
    )

    assert policy.has_track_exception(guild_id=123, track_id=current.id)
    assert "Added exception" in interaction.edited_messages[0]
    assert isinstance(interaction.edited_views[0], AdvancedActionsView)

    second = _FakeInteraction(guild=guild)
    await ControlCenterService(bot).run_advanced_action(  # type: ignore[arg-type]
        second,  # type: ignore[arg-type]
        "toggle_playall_exception",
    )

    assert not policy.has_track_exception(guild_id=123, track_id=current.id)
    assert "Removed exception" in second.edited_messages[0]


@pytest.mark.asyncio
async def test_more_actions_play_all_exception_toggle_rejects_non_admin(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=None)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current
    interaction = _FakeInteraction(guild=guild, administrator=False)

    await ControlCenterService(bot).run_advanced_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "toggle_playall_exception",
    )

    assert "Only an administrator" in interaction.edited_messages[0]
    assert not PlayAllPolicyRepository(database).has_track_exception(
        guild_id=123,
        track_id=current.id,
    )


@pytest.mark.asyncio
async def test_control_center_playback_action_reuses_playback_service_and_refreshes_public_panel(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    player = _FakePlayer()
    guild = _FakeGuild(guild_id=123, voice_client=player)
    channel = _FakeChannel(channel_id=10)
    bot.channels[10] = channel
    interaction = _FakeInteraction(guild=guild, channel=channel)
    current = _indexed_track(database, "Artist/current.mp3")
    bot.player_states.get_or_create(123).current_track = current
    public_message = await channel.send(view=discord.ui.View())
    bot.now_playing_panels.set(NowPlayingPanelRecord(123, 10, public_message.id))

    await ControlCenterService(bot).run_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "next",
    )

    assert player.stop_count == 1
    assert bot.player_states.get_or_create(123).current_track is None
    assert public_message.edit_count == 1
    assert interaction.edit_count == 1
    assert interaction.followup_messages == []


@pytest.mark.asyncio
async def test_control_center_like_reuses_rating_service_without_skip(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    player = _FakePlayer()
    guild = _FakeGuild(guild_id=123, voice_client=player)
    interaction = _FakeInteraction(guild=guild)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current

    await ControlCenterService(bot).run_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "like",
    )

    assert RatingRepository(database).get_rating(123, 42, current.id) == Rating(
        guild_id=123,
        user_id=42,
        track_id=current.id,
        rating="like",
    )
    assert player.stop_count == 0
    assert bot.player_states.get_or_create(123).current_track == current
    assert interaction.edit_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("rating_value", ["dislike", "superdislike"])
async def test_control_center_negative_ratings_save_then_skip(
    database: SQLiteDatabase,
    rating_value: str,
) -> None:
    bot = _FakeBot(database)
    player = _FakePlayer()
    guild = _FakeGuild(guild_id=123, voice_client=player)
    interaction = _FakeInteraction(guild=guild)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current

    await ControlCenterService(bot).run_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        rating_value,
    )

    assert RatingRepository(database).get_rating(123, 42, current.id) == Rating(
        guild_id=123,
        user_id=42,
        track_id=current.id,
        rating=rating_value,
    )
    assert player.stop_count == 1
    assert bot.player_states.get_or_create(123).current_track is None
    assert interaction.edit_count == 1


@pytest.mark.asyncio
async def test_control_center_queue_action_edits_once_without_public_panel_refresh(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=None)
    interaction = _FakeInteraction(guild=guild)
    bot.player_states.get_or_create(123).current_track = _indexed_track(
        database,
        "Artist/current.mp3",
    )

    await ControlCenterService(bot).run_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "queue",
    )

    assert "Now playing: current" in interaction.edited_messages[0]
    assert interaction.edit_count == 1
    assert interaction.followup_messages == []


@pytest.mark.asyncio
async def test_successful_play_local_acknowledgement_includes_control_panel_opener(
    database: SQLiteDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _FakeBot(database)
    cog = MusicCog(cast(Any, bot))
    track = _indexed_track(database, "Rock/Artist/current.mp3")
    _patch_cog_services(cog, library=_FakeLibrary([track]), playback=_FakePlayback(bot))
    monkeypatch.setattr(
        "weasel_bot_v2.cogs.music.AudioPlaybackService",
        lambda current_bot, music_root: _FakePlayback(current_bot),
    )
    guild = _FakeGuild(guild_id=123, voice_client=object())
    interaction = _FakeInteraction(guild=guild)

    await _run_slash(cog, "play_local", interaction, "current")

    assert interaction.deferred_public is True
    assert interaction.followup_ephemeral == [False]
    assert interaction.followup_messages == ["Playback started\ncurrent\nArtist • Rock"]
    assert isinstance(interaction.followup_views[0], OpenControlPanelView)
    assert _button_labels(interaction.followup_views[0]) == ["Open Control Panel"]


@pytest.mark.asyncio
async def test_successful_play_all_acknowledgement_includes_control_panel_opener(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    cog = MusicCog(cast(Any, bot))
    tracks = [
        _indexed_track(database, "Rock/Artist/first.mp3"),
        _indexed_track(database, "Rock/Artist/second.mp3"),
    ]
    _patch_cog_services(cog, library=_FakeLibrary(tracks), playback=_FakePlayback(bot))
    guild = _FakeGuild(guild_id=123, voice_client=object())
    interaction = _FakeInteraction(guild=guild)

    await _run_slash(cog, "play_all", interaction)

    assert interaction.followup_ephemeral == [False]
    assert "Playback started" in interaction.followup_messages[0]
    assert "Queued 1 more track(s)" in interaction.followup_messages[0]
    assert isinstance(interaction.followup_views[0], OpenControlPanelView)
    assert _button_labels(interaction.followup_views[0]) == ["Open Control Panel"]


@pytest.mark.asyncio
async def test_manual_skip_uses_single_compact_public_acknowledgement(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    cog = MusicCog(cast(Any, bot))
    player = _FakePlayer()
    guild = _FakeGuild(guild_id=123, voice_client=player)
    interaction = _FakeInteraction(guild=guild)
    bot.player_states.get_or_create(123).current_track = _indexed_track(
        database,
        "Artist/current.mp3",
    )

    await _run_slash(cog, "skip", interaction)

    assert interaction.response_ephemeral == [False]
    assert interaction.response_messages == ["Skipped\nSkipped. The queue is empty."]
    assert interaction.followup_messages == []


def test_control_center_custom_ids_are_stable_and_unique() -> None:
    ids = control_center_custom_ids()

    assert "weasel:controls:open" in ids
    assert "weasel:controls:playall_exception" in ids
    assert "weasel:placeholder:ratings-center" not in ids
    assert "weasel:controls:reset_volume" not in ids
    assert "weasel:controls:advanced:reset_volume" not in ids
    assert len(ids) == len(set(ids))


def test_control_center_main_grid_matches_required_3x5_layout(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=None)
    state = bot.player_states.get_or_create(123)
    state.current_track = _indexed_track(database, "Artist/current.mp3")
    state.upcoming = [
        _indexed_track(database, "Artist/next.mp3"),
        _indexed_track(database, "Artist/later.mp3"),
    ]
    snapshot = ControlCenterService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    view = ControlCenterView(bot, snapshot)
    rows: list[list[discord.ui.Button[Any]]] = [[], [], []]
    for child in view.children:
        assert isinstance(child, discord.ui.Button)
        row = child.row
        assert row is not None
        rows[row].append(child)

    assert [len(row) for row in rows] == [5, 5, 5]
    assert [[button.custom_id for button in row] for row in rows] == [
        [
            "weasel:controls:back",
            "weasel:controls:pause_resume",
            "weasel:controls:skip",
            "weasel:controls:stop",
            "weasel:controls:loop",
        ],
        [
            "weasel:controls:volume_down",
            "weasel:controls:volume_up",
            "weasel:controls:shuffle",
            "weasel:controls:queue",
            "weasel:controls:more",
        ],
        [
            "weasel:controls:like",
            "weasel:controls:superlike",
            "weasel:controls:playall_exception",
            "weasel:controls:dislike",
            "weasel:controls:superdislike",
        ],
    ]
    buttons = [button for row in rows for button in row]
    exception = [
        button for button in buttons if button.custom_id == "weasel:controls:playall_exception"
    ]
    assert len(buttons) == 15
    assert len(exception) == 1
    assert exception[0].disabled is False
    assert exception[0].emoji is not None
    assert str(exception[0].emoji) == "➕"
    assert all(button.label is None for button in buttons)
    assert all(button.style is discord.ButtonStyle.secondary for button in buttons)
    assert all(button.emoji is not None for button in buttons)


def test_control_center_rating_buttons_use_application_emojis(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    bot.application_emoji_registry = ApplicationEmojiRegistry(
        {
            "wg_like": discord.PartialEmoji(name="wg_like", id=301),
            "wg_superlike": discord.PartialEmoji(name="wg_superlike", id=302),
            "wg_dislike": discord.PartialEmoji(name="wg_dislike", id=303),
            "wg_superdislike": discord.PartialEmoji(name="wg_superdislike", id=304),
        }
    )
    guild = _FakeGuild(guild_id=123, voice_client=None)
    state = bot.player_states.get_or_create(123)
    state.current_track = _indexed_track(database, "Artist/current.mp3")
    snapshot = ControlCenterService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    view = ControlCenterView(bot, snapshot)
    buttons = {
        button.custom_id: button
        for button in view.children
        if isinstance(button, discord.ui.Button)
    }

    assert buttons["weasel:controls:like"].emoji is not None
    assert str(buttons["weasel:controls:like"].emoji) == "<:wg_like:301>"
    assert buttons["weasel:controls:superlike"].emoji is not None
    assert str(buttons["weasel:controls:superlike"].emoji) == "<:wg_superlike:302>"
    assert buttons["weasel:controls:dislike"].emoji is not None
    assert str(buttons["weasel:controls:dislike"].emoji) == "<:wg_dislike:303>"
    assert buttons["weasel:controls:superdislike"].emoji is not None
    assert str(buttons["weasel:controls:superdislike"].emoji) == "<:wg_superdislike:304>"


def test_control_center_exception_button_resolves_add_and_remove_visuals(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    bot.application_emoji_registry = ApplicationEmojiRegistry(
        {
            "wg_exception_add": discord.PartialEmoji(name="wg_exception_add", id=501),
            "wg_exception_remove": discord.PartialEmoji(name="wg_exception_remove", id=502),
        }
    )
    guild = _FakeGuild(guild_id=123, voice_client=None)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current

    add_snapshot = ControlCenterService(bot).snapshot_for(guild)  # type: ignore[arg-type]
    add_view = ControlCenterView(bot, add_snapshot)
    add_button = _button_by_id(add_view, "weasel:controls:playall_exception")

    _store_exception(database, track_id=current.id)
    remove_snapshot = ControlCenterService(bot).snapshot_for(guild)  # type: ignore[arg-type]
    remove_view = ControlCenterView(bot, remove_snapshot)
    remove_button = _button_by_id(remove_view, "weasel:controls:playall_exception")

    assert add_button.emoji is not None
    assert str(add_button.emoji) == "<:wg_exception_add:501>"
    assert remove_button.emoji is not None
    assert str(remove_button.emoji) == "<:wg_exception_remove:502>"


def test_control_center_exception_button_fallbacks_and_disabled_states(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=None)

    idle_snapshot = ControlCenterService(bot).snapshot_for(guild)  # type: ignore[arg-type]
    idle_view = ControlCenterView(bot, idle_snapshot)

    unavailable = replace(_indexed_track(database, "Artist/unavailable.mp3"), is_available=False)
    unavailable = TrackRepository(database).upsert(unavailable)
    bot.player_states.get_or_create(123).current_track = unavailable
    unavailable_snapshot = ControlCenterService(bot).snapshot_for(guild)  # type: ignore[arg-type]
    unavailable_view = ControlCenterView(bot, unavailable_snapshot)

    non_local = Track(source="web", source_id="remote", display_title="remote")
    bot.player_states.get_or_create(123).current_track = non_local
    non_local_snapshot = ControlCenterService(bot).snapshot_for(guild)  # type: ignore[arg-type]
    non_local_view = ControlCenterView(bot, non_local_snapshot)

    local = _indexed_track(database, "Artist/local.mp3")
    assert local.id is not None
    bot.player_states.get_or_create(123).current_track = local
    add_snapshot = ControlCenterService(bot).snapshot_for(guild)  # type: ignore[arg-type]
    add_view = ControlCenterView(bot, add_snapshot)
    _store_exception(database, track_id=local.id)
    remove_snapshot = ControlCenterService(bot).snapshot_for(guild)  # type: ignore[arg-type]
    remove_view = ControlCenterView(bot, remove_snapshot)

    assert _button_by_id(idle_view, "weasel:controls:playall_exception").disabled is True
    assert _button_by_id(unavailable_view, "weasel:controls:playall_exception").disabled is True
    assert _button_by_id(non_local_view, "weasel:controls:playall_exception").disabled is True
    assert str(_button_by_id(add_view, "weasel:controls:playall_exception").emoji) == "➕"
    assert str(_button_by_id(remove_view, "weasel:controls:playall_exception").emoji) == "➖"


@pytest.mark.asyncio
async def test_control_center_exception_button_toggles_policy_and_refreshes_views(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    player = _FakePlayer()
    guild = _FakeGuild(guild_id=123, voice_client=player)
    channel = _FakeChannel(channel_id=10)
    bot.channels[10] = channel
    interaction = _FakeInteraction(guild=guild, channel=channel)
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current
    public_message = await channel.send(view=discord.ui.View())
    bot.now_playing_panels.set(NowPlayingPanelRecord(123, 10, public_message.id))

    await ControlCenterService(bot).run_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "toggle_playall_exception",
    )

    assert PlayAllPolicyRepository(database).has_track_exception(
        guild_id=123,
        track_id=current.id,
    )
    assert public_message.edit_count == 1
    assert interaction.edit_count == 1
    assert "Added exception" in interaction.edited_messages[0]
    assert isinstance(interaction.edited_views[0], ControlCenterView)
    refreshed_button = _button_by_id(
        interaction.edited_views[0],
        "weasel:controls:playall_exception",
    )
    assert str(refreshed_button.emoji) == "➖"
    assert player.stop_count == 0
    assert player.disconnected is False
    assert player.volumes == []

    second = _FakeInteraction(guild=guild, channel=channel)
    await ControlCenterService(bot).run_action(  # type: ignore[arg-type]
        second,  # type: ignore[arg-type]
        "toggle_playall_exception",
    )

    assert not PlayAllPolicyRepository(database).has_track_exception(
        guild_id=123,
        track_id=current.id,
    )
    assert public_message.edit_count == 2
    assert "Removed exception" in second.edited_messages[0]


@pytest.mark.asyncio
async def test_control_center_exception_button_rejects_unauthorized_without_public_refresh(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123, voice_client=None)
    channel = _FakeChannel(channel_id=10)
    bot.channels[10] = channel
    current = _indexed_track(database, "Artist/current.mp3")
    assert current.id is not None
    bot.player_states.get_or_create(123).current_track = current
    public_message = await channel.send(view=discord.ui.View())
    bot.now_playing_panels.set(NowPlayingPanelRecord(123, 10, public_message.id))
    interaction = _FakeInteraction(guild=guild, channel=channel, administrator=False)

    await ControlCenterService(bot).run_action(  # type: ignore[arg-type]
        interaction,  # type: ignore[arg-type]
        "toggle_playall_exception",
    )

    assert not PlayAllPolicyRepository(database).has_track_exception(
        guild_id=123,
        track_id=current.id,
    )
    assert public_message.edit_count == 0
    assert "Only an administrator" in interaction.edited_messages[0]


async def _run_slash(
    cog: MusicCog,
    command_name: str,
    interaction: _FakeInteraction,
    *args: object,
) -> None:
    command = next(
        command for command in MusicCog.__cog_app_commands__ if command.name == command_name
    )
    await cast(Any, command).callback(cog, interaction, *args)


def _patch_cog_services(cog: MusicCog, *, library: object, playback: object) -> None:
    cog_any = cast(Any, cog)
    cog_any._library_service = lambda: library
    cog_any._playback_service = lambda: playback


def _button_labels(view: discord.ui.View | None) -> list[str | None]:
    if view is None:
        return []
    return [
        item.label
        for item in view.children
        if isinstance(item, discord.ui.Button) and not item.disabled
    ]


def _button_by_id(view: discord.ui.View | None, custom_id: str) -> discord.ui.Button[Any]:
    if view is None:
        raise AssertionError(f"Button not found: {custom_id}")
    for item in view.children:
        if isinstance(item, discord.ui.Button) and item.custom_id == custom_id:
            return item
    raise AssertionError(f"Button not found: {custom_id}")


def _store_exception(database: SQLiteDatabase, *, track_id: int) -> None:
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Listener"))
    PlayAllPolicyRepository(database).add_track_exception(
        guild_id=123,
        track_id=track_id,
        created_by_user_id=42,
    )


def _indexed_track(database: SQLiteDatabase, relative_path: str) -> Track:
    return TrackRepository(database).upsert(
        Track(
            source="local",
            source_id=relative_path,
            relative_path=relative_path,
            file_name=relative_path.rsplit("/", maxsplit=1)[-1],
            display_title=relative_path.rsplit("/", maxsplit=1)[-1].removesuffix(".mp3"),
            title=relative_path.rsplit("/", maxsplit=1)[-1].removesuffix(".mp3"),
            artist_guess="Artist",
            category_guess="Rock" if relative_path.count("/") >= 2 else None,
            extension=".mp3",
        )
    )


class _FakeBot:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        self.player_states = PlayerStateStore()
        self.now_playing_panels = NowPlayingPanelRegistry()
        self.lavalink_available = True
        self.settings = SimpleNamespace(bot=SimpleNamespace(music_library=Path("/music")))
        self.channels: dict[int, _FakeChannel] = {}
        self.application_emoji_registry = ApplicationEmojiRegistry.empty()

    def get_channel(self, channel_id: int) -> _FakeChannel | None:
        return self.channels.get(channel_id)


class _FakeGuild:
    def __init__(self, *, guild_id: int, voice_client: object | None) -> None:
        self.id = guild_id
        self.voice_client = voice_client


class _FakePlayer:
    def __init__(self) -> None:
        self.stop_count = 0
        self.disconnected = False
        self.volumes: list[int] = []

    async def stop(self) -> None:
        self.stop_count += 1

    async def disconnect(self) -> None:
        self.disconnected = True

    async def set_volume(self, volume: int) -> None:
        self.volumes.append(volume)


class _FakeLibrary:
    def __init__(self, tracks: list[Track]) -> None:
        self.tracks = tracks

    def search(self, query: str, *, limit: int) -> list[Track]:
        return self.tracks[:limit]

    def list_indexed_mp3_tracks(self) -> list[Track]:
        return list(self.tracks)


class _FakePlayback:
    def __init__(self, bot: _FakeBot) -> None:
        self.bot = bot

    async def play_local_track(self, *, interaction: _FakeInteraction, track: Track) -> Any:
        state = self.bot.player_states.get_or_create(interaction.guild.id)
        if state.current_track is not None:
            position = state.enqueue(track)
            return SimpleNamespace(ok=True, message=f"Added to queue at position {position}")
        state.set_current_track(track)
        return SimpleNamespace(ok=True, message=f"Now playing: {track.display_title}")


class _FakeInteraction:
    def __init__(
        self,
        *,
        guild: _FakeGuild,
        channel: _FakeChannel | None = None,
        administrator: bool = True,
    ) -> None:
        self.guild = guild
        self.user = SimpleNamespace(
            id=42,
            display_name="Listener",
            guild_permissions=SimpleNamespace(administrator=administrator),
        )
        self.channel = channel or _FakeChannel(channel_id=10)
        self.response = _FakeResponse(self)
        self.followup = _FakeFollowup(self)
        self.message = None
        self.response_messages: list[str] = []
        self.response_views: list[discord.ui.View | None] = []
        self.response_ephemeral: list[bool] = []
        self.followup_messages: list[str] = []
        self.followup_views: list[discord.ui.View | None] = []
        self.followup_ephemeral: list[bool] = []
        self.edited_messages: list[str] = []
        self.edited_views: list[discord.ui.View | None] = []
        self.edit_count = 0
        self.deferred_public = False


class _FakeResponse:
    def __init__(self, interaction: _FakeInteraction) -> None:
        self.interaction = interaction
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def defer(self, *, ephemeral: bool = False, thinking: bool = False) -> None:
        self._done = True
        self.interaction.deferred_public = not ephemeral

    async def send_message(
        self,
        message: str,
        *,
        view: discord.ui.View | None = None,
        ephemeral: bool = False,
    ) -> None:
        self._done = True
        self.interaction.response_messages.append(message)
        self.interaction.response_views.append(view)
        self.interaction.response_ephemeral.append(ephemeral)

    async def edit_message(
        self,
        *,
        content: str,
        view: discord.ui.View | None = None,
    ) -> None:
        self._done = True
        self.interaction.edit_count += 1
        self.interaction.edited_messages.append(content)
        self.interaction.edited_views.append(view)


class _FakeFollowup:
    def __init__(self, interaction: _FakeInteraction) -> None:
        self.interaction = interaction

    async def send(
        self,
        message: str,
        *,
        view: discord.ui.View | None = None,
        ephemeral: bool = False,
    ) -> None:
        self.interaction.followup_messages.append(message)
        self.interaction.followup_views.append(view)
        self.interaction.followup_ephemeral.append(ephemeral)


class _FakeChannel:
    def __init__(self, *, channel_id: int) -> None:
        self.id = channel_id
        self.sent_messages: list[_FakeMessage] = []
        self.next_message_id = 100

    async def send(self, **kwargs: Any) -> _FakeMessage:
        message = _FakeMessage(message_id=self.next_message_id)
        self.next_message_id += 1
        self.sent_messages.append(message)
        return message

    async def fetch_message(self, message_id: int) -> _FakeMessage:
        for message in self.sent_messages:
            if message.id == message_id:
                return message
        raise discord.NotFound(response=cast(Any, None), message="missing")


class _FakeMessage:
    def __init__(self, *, message_id: int) -> None:
        self.id = message_id
        self.edit_count = 0
        self.flags = SimpleNamespace(components_v2=False)

    async def edit(self, **kwargs: Any) -> None:
        self.edit_count += 1
