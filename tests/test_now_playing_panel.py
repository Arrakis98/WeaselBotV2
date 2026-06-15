from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import discord
import pytest

from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Rating, RatingCounts, Track, UserRecord
from weasel_bot_v2.repositories import (
    RatingRepository,
    TrackRepository,
    TrackVolumeOverrideRepository,
    UserRepository,
)
from weasel_bot_v2.services.application_emojis import ApplicationEmojiRegistry
from weasel_bot_v2.services.now_playing_panel import (
    RATINGS_CENTER_PLACEHOLDER_CUSTOM_ID,
    ComponentsV2PanelRenderer,
    LegacyEmbedPanelRenderer,
    NowPlayingPanelRecord,
    NowPlayingPanelRegistry,
    NowPlayingPanelService,
    PanelRenderMode,
    build_components_v2_canary_view,
    control_custom_ids,
    control_emojis,
    control_labels,
    control_specs,
    detect_components_v2_support,
    detect_message_render_mode,
    format_components_v2_rating_totals,
    format_queue,
    more_action_values,
    select_panel_renderer,
    shuffle_upcoming_queue,
)
from weasel_bot_v2.services.player_state import PlayerStateStore


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    sqlite_database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel-test.db"))
    sqlite_database.initialize()
    return sqlite_database


def test_registry_keeps_one_panel_record_per_guild() -> None:
    registry = NowPlayingPanelRegistry()
    first = NowPlayingPanelRecord(guild_id=123, channel_id=10, message_id=100)
    second = NowPlayingPanelRecord(guild_id=123, channel_id=11, message_id=101)

    registry.set(first)
    registry.set(second)

    assert registry.get(123) == second


def test_registry_reuses_per_guild_lock() -> None:
    registry = NowPlayingPanelRegistry()

    assert registry.lock_for(123) is registry.lock_for(123)
    assert registry.lock_for(123) is not registry.lock_for(456)


def test_snapshot_reflects_queue_volume_loop_and_ratings(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    current = _indexed_track(database, "Rock/Artist/current.mp3")
    next_track = _indexed_track(database, "Rock/Artist/next.mp3")
    previous = _indexed_track(database, "Rock/Artist/previous.mp3")
    state = bot.player_states.get_or_create(123)
    state.current_track = current
    state.upcoming.append(next_track)
    state.recently_played.append(previous)
    state.paused = True
    state.volume = 75
    state.loop_current = True
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Tester"))
    assert current.id is not None
    TrackVolumeOverrideRepository(database).save(123, current.id, 75)
    RatingRepository(database).set_rating(
        Rating(guild_id=123, user_id=42, track_id=current.id, rating="superlike")
    )

    snapshot = NowPlayingPanelService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    assert snapshot.title == "current"
    assert snapshot.artist == "Artist"
    assert snapshot.track_display.artist == "Artist"
    assert snapshot.category == "Rock"
    assert snapshot.track_display.metadata_line == "Artist • Rock"
    assert snapshot.status == "Paused"
    assert snapshot.volume == 75
    assert snapshot.volume_source_label == "track preset"
    assert snapshot.loop_enabled is True
    assert snapshot.queue_length == 1
    assert snapshot.next_title == "next"
    assert snapshot.previous_available is True
    assert snapshot.rating_counts.superlike == 1
    assert snapshot.relative_path == "Rock/Artist/current.mp3"


def test_idle_panel_snapshot_has_no_stale_track_or_queue(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    state = bot.player_states.get_or_create(123)
    state.clear_all()

    snapshot = NowPlayingPanelService(bot).snapshot_for(guild)  # type: ignore[arg-type]
    payload = ComponentsV2PanelRenderer().render(bot, snapshot)
    rendered = str(payload.view.to_components())

    assert snapshot.has_track is False
    assert snapshot.title == "Nothing playing"
    assert snapshot.status == "Idle"
    assert snapshot.queue_length == 0
    assert snapshot.next_title is None
    assert snapshot.volume == 100
    assert snapshot.volume_source_label == "default"
    assert "Idle" in rendered
    assert "0 queued" in rendered


def test_snapshot_displays_track_volume_source(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    current = _indexed_track(database, "Rock/Artist/current.mp3")
    assert current.id is not None
    TrackVolumeOverrideRepository(database).save(123, current.id, 120)
    state = bot.player_states.get_or_create(123)
    state.current_track = current
    state.volume = 100

    snapshot = NowPlayingPanelService(bot).snapshot_for(guild)  # type: ignore[arg-type]
    payload = ComponentsV2PanelRenderer().render(bot, snapshot)

    assert snapshot.volume == 120
    assert snapshot.volume_source_label == "track preset"
    assert "120%" in str(payload.view.to_components())
    assert "track preset" in str(payload.view.to_components())


def test_snapshot_uses_divers_artist_fallback_without_category_leak(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    state = bot.player_states.get_or_create(123)
    state.current_track = Track(
        source="local",
        source_id="Misc/song.mp3",
        relative_path="Misc/song.mp3",
        file_name="song.mp3",
        display_title="song",
        category_guess="Misc",
    )

    snapshot = NowPlayingPanelService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    assert snapshot.track_display.artist == "Divers"
    assert snapshot.track_display.category == "Misc"
    assert snapshot.track_display.metadata_line == "Divers • Misc"


def test_components_v2_capability_detection() -> None:
    support = detect_components_v2_support()

    assert support.discord_version
    assert support.supported is True
    assert support.missing == ()


def test_panel_renderer_selection_prefers_components_v2() -> None:
    assert isinstance(select_panel_renderer(), ComponentsV2PanelRenderer)
    assert isinstance(select_panel_renderer(prefer_components_v2=False), LegacyEmbedPanelRenderer)


def test_components_v2_payload_has_no_public_raw_path(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    bot.player_states.get_or_create(123).current_track = _indexed_track(
        database,
        "Rock/Artist/current.mp3",
    )
    snapshot = NowPlayingPanelService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    payload = ComponentsV2PanelRenderer().render(bot, snapshot)
    rendered = str(payload.view.to_components())

    assert payload.mode == PanelRenderMode.COMPONENTS_V2
    assert "WEASEL GALAXY" in rendered
    assert "current" in rendered
    assert "Rock/Artist/current.mp3" not in rendered
    assert "Lavalink" not in rendered


def test_emoji_only_controls_and_stable_custom_ids() -> None:
    ids = control_custom_ids()

    assert "weasel:now_playing:queue" in ids
    assert "weasel:now_playing:shuffle" in ids
    assert "weasel:now_playing:more" in ids
    assert RATINGS_CENTER_PLACEHOLDER_CUSTOM_ID in ids
    assert len(ids) == len(set(ids))
    labels = dict(zip((spec.key for spec in control_specs()), control_labels(), strict=True))
    emojis = dict(zip((spec.key for spec in control_specs()), control_emojis(), strict=True))
    assert all(label is None for label in labels.values())
    assert emojis["volume_down"] == "🔉"
    assert emojis["volume_up"] == "🔊"
    assert emojis["more"] == "⋯"
    assert emojis["shuffle"] == "🔀"
    assert emojis["placeholder"] == "❔"


def test_public_main_grid_specs_match_required_3x5_layout() -> None:
    specs = control_specs()
    row_counts: dict[int, int] = {}
    for spec in specs:
        assert spec.custom_id
        assert spec.label or spec.emoji
        row_counts[spec.row] = row_counts.get(spec.row, 0) + 1

    assert row_counts == {0: 5, 1: 5, 2: 5}
    assert all(count <= 5 for count in row_counts.values())
    assert tuple(spec.key for spec in specs) == (
        "previous",
        "pause_resume",
        "next",
        "stop",
        "loop",
        "volume_down",
        "volume_up",
        "shuffle",
        "queue",
        "more",
        "like",
        "superlike",
        "placeholder",
        "dislike",
        "superdislike",
    )
    assert sum(1 for spec in specs if spec.key != "placeholder") == 14
    assert sum(1 for spec in specs if spec.key == "placeholder") == 1
    assert specs[12].row == 2
    assert specs[12].custom_id == RATINGS_CENTER_PLACEHOLDER_CUSTOM_ID
    assert all(
        spec.style is discord.ButtonStyle.secondary
        for spec in specs
        if spec.key != "placeholder"
    )
    assert all(spec.label is None for spec in specs)


def test_declared_button_emojis_are_single_valid_emoji_fields() -> None:
    invalid_fragments = ("+", "−")
    for emoji in control_emojis():
        if emoji is None:
            continue
        assert all(fragment not in emoji for fragment in invalid_fragments)


def test_public_components_v2_panel_renders_exactly_three_five_button_rows(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    state = bot.player_states.get_or_create(123)
    state.current_track = _indexed_track(database, "one.mp3")
    state.upcoming = [
        _indexed_track(database, "two.mp3"),
        _indexed_track(database, "three.mp3"),
    ]
    snapshot = NowPlayingPanelService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    payload = ComponentsV2PanelRenderer().render(bot, snapshot)
    rows = [
        component
        for component in payload.view.to_components()[0]["components"]
        if component["type"] == 1
    ]
    button_rows = [[button["custom_id"] for button in row["components"]] for row in rows]

    assert len(button_rows) == 3
    assert all(len(row) == 5 for row in button_rows)
    assert button_rows == [
        [
            "weasel:now_playing:back",
            "weasel:now_playing:pause_resume",
            "weasel:now_playing:skip",
            "weasel:now_playing:stop",
            "weasel:now_playing:loop",
        ],
        [
            "weasel:now_playing:volume_down",
            "weasel:now_playing:volume_up",
            "weasel:now_playing:shuffle",
            "weasel:now_playing:queue",
            "weasel:now_playing:more",
        ],
        [
            "weasel:now_playing:like",
            "weasel:now_playing:superlike",
            RATINGS_CENTER_PLACEHOLDER_CUSTOM_ID,
            "weasel:now_playing:dislike",
            "weasel:now_playing:superdislike",
        ],
    ]
    buttons = [button for row in rows for button in row["components"]]
    placeholder_buttons = [
        button for button in buttons if button["custom_id"] == RATINGS_CENTER_PLACEHOLDER_CUSTOM_ID
    ]
    functional_buttons = [
        button for button in buttons if button["custom_id"] != RATINGS_CENTER_PLACEHOLDER_CUSTOM_ID
    ]
    assert len(functional_buttons) == 14
    assert len(placeholder_buttons) == 1
    assert placeholder_buttons[0]["disabled"] is True
    assert placeholder_buttons[0]["style"] == discord.ButtonStyle.secondary.value
    assert placeholder_buttons[0]["emoji"]["name"] == "❔"
    assert all("label" not in button for button in functional_buttons)
    assert all(
        button["style"] == discord.ButtonStyle.secondary.value
        for button in functional_buttons
    )
    assert all("emoji" in button for button in functional_buttons)


def test_public_rating_buttons_render_application_emojis(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    bot.application_emoji_registry = ApplicationEmojiRegistry(
        {
            "wg_like": discord.PartialEmoji(name="wg_like", id=101),
            "wg_superlike": discord.PartialEmoji(name="wg_superlike", id=102),
            "wg_dislike": discord.PartialEmoji(name="wg_dislike", id=103),
            "wg_superdislike": discord.PartialEmoji(name="wg_superdislike", id=104),
        }
    )
    guild = _FakeGuild(guild_id=123)
    state = bot.player_states.get_or_create(123)
    state.current_track = _indexed_track(database, "one.mp3")
    snapshot = NowPlayingPanelService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    payload = ComponentsV2PanelRenderer().render(bot, snapshot)
    rows = [
        component
        for component in payload.view.to_components()[0]["components"]
        if component["type"] == 1
    ]
    rating_buttons = rows[2]["components"]

    assert rating_buttons[0]["custom_id"] == "weasel:now_playing:like"
    assert rating_buttons[0]["emoji"]["name"] == "wg_like"
    assert rating_buttons[1]["custom_id"] == "weasel:now_playing:superlike"
    assert rating_buttons[1]["emoji"]["name"] == "wg_superlike"
    assert rating_buttons[3]["custom_id"] == "weasel:now_playing:dislike"
    assert rating_buttons[3]["emoji"]["name"] == "wg_dislike"
    assert rating_buttons[4]["custom_id"] == "weasel:now_playing:superdislike"
    assert rating_buttons[4]["emoji"]["name"] == "wg_superdislike"


def test_components_v2_rating_summary_uses_application_emojis_when_available() -> None:
    bot = SimpleNamespace(
        application_emoji_registry=ApplicationEmojiRegistry(
            {
                "wg_like": discord.PartialEmoji(name="wg_like", id=201),
                "wg_superlike": discord.PartialEmoji(name="wg_superlike", id=202),
                "wg_dislike": discord.PartialEmoji(name="wg_dislike", id=203),
                "wg_superdislike": discord.PartialEmoji(name="wg_superdislike", id=204),
            }
        )
    )
    counts = RatingCounts(like=1, superlike=2, dislike=3, superdislike=4)

    summary = format_components_v2_rating_totals(bot, counts)

    assert summary == (
        "<:wg_like:201> 1   "
        "<:wg_superlike:202> 2   "
        "<:wg_dislike:203> 3   "
        "<:wg_superdislike:204> 4"
    )


def test_components_v2_rating_summary_retains_unicode_fallbacks() -> None:
    counts = RatingCounts(like=5, superlike=6, dislike=7, superdislike=8)

    summary = format_components_v2_rating_totals(SimpleNamespace(), counts)

    assert summary == "❤️ 5   💎 6   👎 7   💀 8"


def test_renderers_use_compatible_distinct_view_classes(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    bot.player_states.get_or_create(123).current_track = _indexed_track(database, "one.mp3")
    snapshot = NowPlayingPanelService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    components = ComponentsV2PanelRenderer().render(bot, snapshot)
    legacy = LegacyEmbedPanelRenderer().render(bot, snapshot)

    assert isinstance(components.view, discord.ui.LayoutView)
    assert not isinstance(components.view, discord.ui.View)
    assert isinstance(legacy.view, discord.ui.View)
    assert not isinstance(legacy.view, discord.ui.LayoutView)


def test_minimal_components_v2_canary_serializes() -> None:
    view = build_components_v2_canary_view()
    rendered = view.to_components()

    assert isinstance(view, discord.ui.LayoutView)
    assert "WEASEL GALAXY" in str(rendered)
    assert "weasel:now_playing:canary" in str(rendered)


def test_more_actions_options_include_only_initial_functional_choices() -> None:
    values = more_action_values()

    assert values[:2] == ("show_queue", "track_info")
    assert "same_artist_disabled" in values
    assert "add_to_playlist_disabled" in values
    assert "similar_radio_disabled" in values


def test_queue_preview_truncates(database: SQLiteDatabase) -> None:
    state = PlayerStateStore().get_or_create(123)
    state.current_track = _indexed_track(database, "current.mp3")
    state.upcoming.extend(_indexed_track(database, f"next-{index}.mp3") for index in range(12))

    message = format_queue(state, limit=5)

    assert "Upcoming (12):" in message
    assert "next-0" in message
    assert "next-5" not in message
    assert "...and 7 more." in message


def test_shuffle_preserves_current_and_changes_only_upcoming(database: SQLiteDatabase) -> None:
    current = _indexed_track(database, "current.mp3")
    first = _indexed_track(database, "first.mp3")
    second = _indexed_track(database, "second.mp3")
    state = PlayerStateStore().get_or_create(123)
    state.current_track = current
    state.upcoming = [first, second]

    result = shuffle_upcoming_queue(state)

    assert result.ok is True
    assert state.current_track == current
    assert set(state.upcoming) == {first, second}
    assert state.upcoming != [first, second]


def test_shuffle_empty_or_single_queue_behavior(database: SQLiteDatabase) -> None:
    empty = PlayerStateStore().get_or_create(123)
    single = PlayerStateStore().get_or_create(456)
    single.upcoming.append(_indexed_track(database, "one.mp3"))

    assert shuffle_upcoming_queue(empty).ok is False
    assert shuffle_upcoming_queue(single).ok is False


@pytest.mark.asyncio
async def test_refresh_creates_then_edits_authoritative_panel(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    bot.channels[10] = channel
    bot.player_states.get_or_create(123).current_track = _indexed_track(database, "one.mp3")
    service = NowPlayingPanelService(bot)

    first = await service.refresh(guild=guild, channel=channel, reason="test")  # type: ignore[arg-type]
    second = await service.refresh(guild=guild, channel=channel, reason="test")  # type: ignore[arg-type]

    assert first is not None
    assert second is not None
    assert first.message_id == second.message_id
    assert first.render_mode == PanelRenderMode.COMPONENTS_V2
    assert len(channel.sent_messages) == 1
    assert channel.sent_messages[0].edit_count == 1


@pytest.mark.asyncio
async def test_fresh_components_v2_panel_sends_only_layout_view(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    bot.player_states.get_or_create(123).current_track = _indexed_track(database, "one.mp3")

    record = await NowPlayingPanelService(bot).refresh(
        guild=guild,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
        reason="fresh",
    )

    assert record is not None
    assert record.render_mode == PanelRenderMode.COMPONENTS_V2
    assert channel.send_kwargs == [{"view": channel.sent_messages[0].last_view}]
    assert isinstance(channel.sent_messages[0].last_view, discord.ui.LayoutView)


@pytest.mark.asyncio
async def test_legacy_message_converts_to_components_v2_with_legacy_fields_cleared(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    bot.channels[10] = channel
    state = bot.player_states.get_or_create(123)
    state.current_track = _indexed_track(database, "one.mp3")
    legacy_payload = LegacyEmbedPanelRenderer().render(
        bot,
        NowPlayingPanelService(bot).snapshot_for(guild),  # type: ignore[arg-type]
    )
    legacy = await channel.send(embed=legacy_payload.embed, view=legacy_payload.view)
    bot.now_playing_panels.set(
        NowPlayingPanelRecord(
            guild_id=123,
            channel_id=10,
            message_id=legacy.id,
            view=legacy_payload.view,
            render_mode=PanelRenderMode.LEGACY_EMBED,
        )
    )

    record = await NowPlayingPanelService(bot).refresh(
        guild=guild,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
        reason="convert",
    )

    assert record is not None
    assert record.message_id == legacy.id
    assert record.render_mode == PanelRenderMode.COMPONENTS_V2
    assert legacy.edit_kwargs[-1]["content"] is None
    assert legacy.edit_kwargs[-1]["embed"] is None
    assert legacy.edit_kwargs[-1]["attachments"] == []
    assert isinstance(legacy.edit_kwargs[-1]["view"], discord.ui.LayoutView)


@pytest.mark.asyncio
async def test_existing_components_v2_message_refreshes_with_layout_view(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    state = bot.player_states.get_or_create(123)
    state.current_track = _indexed_track(database, "first.mp3")
    service = NowPlayingPanelService(bot)
    record = await service.refresh(
        guild=guild,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
        reason="create",
    )
    assert record is not None
    state.current_track = _indexed_track(database, "second.mp3")

    refreshed = await service.refresh(
        guild=guild,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
        reason="refresh",
    )

    assert refreshed is not None
    message = channel.sent_messages[0]
    assert message.edit_kwargs[-1]["content"] is None
    assert message.edit_kwargs[-1]["embed"] is None
    assert message.edit_kwargs[-1]["attachments"] == []
    assert isinstance(message.edit_kwargs[-1]["view"], discord.ui.LayoutView)


@pytest.mark.asyncio
async def test_deleted_panel_message_recreates_reference(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    channel.deleted_message_ids.add(100)
    bot.channels[10] = channel
    bot.player_states.get_or_create(123).current_track = _indexed_track(database, "one.mp3")
    bot.now_playing_panels.set(NowPlayingPanelRecord(123, 10, 100))

    record = await NowPlayingPanelService(bot).refresh(
        guild=guild,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
        reason="deleted",
    )

    assert record is not None
    assert record.message_id != 100
    assert bot.now_playing_panels.get(123) == record
    assert len(channel.sent_messages) == 1


@pytest.mark.asyncio
async def test_refresh_does_not_create_duplicate_panels(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    bot.player_states.get_or_create(123).current_track = _indexed_track(database, "one.mp3")
    service = NowPlayingPanelService(bot)

    await service.refresh(guild=guild, channel=channel, reason="first")  # type: ignore[arg-type]
    await service.refresh(guild=guild, channel=channel, reason="second")  # type: ignore[arg-type]
    await service.refresh(guild=guild, channel=channel, reason="third")  # type: ignore[arg-type]

    assert len(channel.sent_messages) == 1
    assert bot.now_playing_panels.get(123) is not None


@pytest.mark.asyncio
async def test_components_v2_failure_falls_back_to_legacy_embed(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    channel.fail_components_v2 = True
    bot.player_states.get_or_create(123).current_track = _indexed_track(database, "one.mp3")

    record = await NowPlayingPanelService(bot).refresh(
        guild=guild,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
        reason="fallback",
    )

    assert record is not None
    assert channel.sent_messages[0].last_embed is not None
    assert channel.sent_messages[0].last_view is not None
    assert record.render_mode == PanelRenderMode.LEGACY_EMBED
    assert bot.player_states.get_or_create(123).current_track is not None


@pytest.mark.asyncio
async def test_components_v2_edit_failure_recreates_new_legacy_message(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    state = bot.player_states.get_or_create(123)
    state.current_track = _indexed_track(database, "first.mp3")
    service = NowPlayingPanelService(bot)
    original = await service.refresh(
        guild=guild,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
        reason="create",
    )
    assert original is not None
    channel.fail_components_v2_edit = True

    fallback = await service.refresh(
        guild=guild,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
        reason="fallback",
    )

    assert fallback is not None
    assert fallback.message_id != original.message_id
    assert fallback.render_mode == PanelRenderMode.LEGACY_EMBED
    assert channel.sent_messages[0].deleted is True
    assert channel.sent_messages[1].last_embed is not None
    assert bot.now_playing_panels.get(123) == fallback
    assert state.current_track is not None


@pytest.mark.asyncio
async def test_no_panel_state_always_attempts_message_creation(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    bot.player_states.get_or_create(123).current_track = _indexed_track(database, "one.mp3")

    record = await NowPlayingPanelService(bot).refresh(
        guild=guild,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
        reason="no-panel",
    )

    assert record is not None
    assert len(channel.send_kwargs) == 1


@pytest.mark.asyncio
async def test_refresh_uses_newest_state(database: SQLiteDatabase) -> None:
    bot = _FakeBot(database)
    guild = _FakeGuild(guild_id=123)
    channel = _FakeChannel(channel_id=10)
    state = bot.player_states.get_or_create(123)
    state.current_track = _indexed_track(database, "first.mp3")
    service = NowPlayingPanelService(bot)
    await service.refresh(guild=guild, channel=channel, reason="first")  # type: ignore[arg-type]

    state.current_track = _indexed_track(database, "second.mp3")
    state.volume = 55
    assert state.current_track.id is not None
    TrackVolumeOverrideRepository(database).save(123, state.current_track.id, 55)
    await service.refresh(guild=guild, channel=channel, reason="second")  # type: ignore[arg-type]

    view = channel.sent_messages[0].last_view
    assert view is not None
    rendered = str(view.to_components())
    assert "second" in rendered
    assert "55%" in rendered


def test_renderer_type_detection() -> None:
    legacy_record = NowPlayingPanelRecord(
        guild_id=123,
        channel_id=10,
        message_id=100,
        view=discord.ui.View(),
        render_mode=PanelRenderMode.LEGACY_EMBED,
    )
    v2_record = NowPlayingPanelRecord(
        guild_id=123,
        channel_id=10,
        message_id=101,
        view=discord.ui.LayoutView(),
        render_mode=PanelRenderMode.COMPONENTS_V2,
    )

    assert (
        detect_message_render_mode(_BareMessage(components_v2=False), legacy_record)
        is PanelRenderMode.LEGACY_EMBED
    )
    assert (
        detect_message_render_mode(_BareMessage(components_v2=True), legacy_record)
        is PanelRenderMode.COMPONENTS_V2
    )
    assert (
        detect_message_render_mode(_BareMessage(components_v2=False), v2_record)
        is PanelRenderMode.COMPONENTS_V2
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
            artist_guess="Artist" if "/" in relative_path else None,
            category_guess="Rock" if relative_path.count("/") >= 2 else None,
        )
    )


def _field_value(embed: discord.Embed, name: str) -> str | None:
    for field in embed.fields:
        if field.name == name:
            return str(field.value)
    return None


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
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id
        self.voice_client: Any = object()


class _FakeChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.sent_messages: list[_FakeMessage] = []
        self.send_kwargs: list[dict[str, Any]] = []
        self.deleted_message_ids: set[int] = set()
        self.next_message_id = 100
        self.fail_components_v2 = False
        self.fail_components_v2_edit = False

    async def send(
        self,
        *,
        embed: discord.Embed | None = None,
        view: Any,
    ) -> _FakeMessage:
        if embed is None and self.fail_components_v2:
            raise TypeError("components v2 rejected")
        kwargs = {"view": view} if embed is None else {"embed": embed, "view": view}
        self.send_kwargs.append(kwargs)
        while self.next_message_id in self.deleted_message_ids:
            self.next_message_id += 1
        message = _FakeMessage(
            message_id=self.next_message_id,
            channel=self,
            embed=embed,
            view=view,
        )
        self.next_message_id += 1
        self.sent_messages.append(message)
        return message

    async def fetch_message(self, message_id: int) -> _FakeMessage:
        if message_id in self.deleted_message_ids:
            raise discord.NotFound(response=_not_found_response(), message="deleted")
        for message in self.sent_messages:
            if message.id == message_id:
                return message
        raise discord.NotFound(response=_not_found_response(), message="missing")


class _FakeMessage:
    def __init__(
        self,
        *,
        message_id: int,
        channel: _FakeChannel,
        embed: discord.Embed | None,
        view: Any,
    ) -> None:
        self.id = message_id
        self.channel = channel
        self.last_embed = embed
        self.last_view = view
        self.edit_count = 0
        self.edit_kwargs: list[dict[str, Any]] = []
        self.deleted = False
        self.flags = SimpleNamespace(components_v2=isinstance(view, discord.ui.LayoutView))

    async def edit(self, **kwargs: Any) -> None:
        view = kwargs.get("view")
        embed = kwargs.get("embed")
        if isinstance(view, discord.ui.LayoutView) and self.channel.fail_components_v2_edit:
            raise TypeError("components v2 rejected")
        if embed is None and self.channel.fail_components_v2:
            raise TypeError("components v2 rejected")
        self.edit_count += 1
        self.edit_kwargs.append(kwargs)
        self.last_embed = embed
        self.last_view = view
        self.flags = SimpleNamespace(components_v2=isinstance(view, discord.ui.LayoutView))

    async def delete(self) -> None:
        self.deleted = True
        self.channel.deleted_message_ids.add(self.id)


class _BareMessage:
    def __init__(self, *, components_v2: bool) -> None:
        self.flags = SimpleNamespace(components_v2=components_v2)


def _not_found_response() -> Any:
    return SimpleNamespace(status=404, reason="Not Found")
