from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import discord
import pytest

from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Track
from weasel_bot_v2.repositories import TrackRepository
from weasel_bot_v2.services.application_emojis import (
    APPLICATION_EMOJI_ASSETS,
    APPLICATION_EMOJI_NAMES,
    OPTIONAL_APPLICATION_EMOJI_NAMES,
    ApplicationEmojiRegistry,
    sync_application_emojis,
    validate_application_emoji_assets,
)
from weasel_bot_v2.services.control_center import ControlCenterView, control_center_custom_ids
from weasel_bot_v2.services.now_playing_panel import (
    PLAY_ALL_EXCEPTION_CONTROL_CUSTOM_ID,
    NowPlayingPanelRegistry,
    NowPlayingPanelService,
    build_control_button,
    control_custom_ids,
    control_specs,
    resolve_control_emoji,
)
from weasel_bot_v2.services.player_state import PlayerStateStore

EXPECTED_EMOJI_NAMES = (
    "wg_back",
    "wg_dislike",
    "wg_superdislike",
    "wg_like",
    "wg_superlike",
    "wg_more",
    "wg_loop_off",
    "wg_loop_on",
    "wg_play_pause",
    "wg_queue",
    "wg_shuffle",
    "wg_stop",
    "wg_skip",
    "wg_volume_up",
    "wg_volume_down",
)


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    sqlite_database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel-test.db"))
    sqlite_database.initialize()
    return sqlite_database


def test_application_emoji_inventory_is_exact_15_name_pack() -> None:
    assert APPLICATION_EMOJI_NAMES == EXPECTED_EMOJI_NAMES
    assert tuple(APPLICATION_EMOJI_ASSETS) == EXPECTED_EMOJI_NAMES
    assert set(APPLICATION_EMOJI_ASSETS.values()) == {
        f"{name}.png" for name in EXPECTED_EMOJI_NAMES
    }
    assert "wg_pause" not in APPLICATION_EMOJI_NAMES
    assert "wg_shuffle_off" not in APPLICATION_EMOJI_NAMES
    assert "wg_shuffle_on" not in APPLICATION_EMOJI_NAMES


def test_all_15_application_emoji_assets_validate_successfully(tmp_path: Path) -> None:
    root = _write_valid_emoji_pack(tmp_path)

    result = validate_application_emoji_assets(root)

    assert result.valid_count == 15
    assert result.invalid_count == 0
    assert tuple(check.stable_name for check in result.checks) == EXPECTED_EMOJI_NAMES


def test_registry_resolves_application_emoji_and_falls_back() -> None:
    registry = ApplicationEmojiRegistry(
        {
            "wg_back": discord.PartialEmoji(name="wg_back", id=111456789012345678),
            "wg_skip": discord.PartialEmoji(name="wg_skip", id=123456789012345678),
            "wg_queue": discord.PartialEmoji(name="wg_queue", id=223456789012345678),
        }
    )
    bot = SimpleNamespace(application_emoji_registry=registry)
    snapshot = SimpleNamespace()

    emoji = resolve_control_emoji(bot, "next", snapshot, fallback="⏭️")
    back_emoji = resolve_control_emoji(bot, "previous", snapshot, fallback="⏮️")
    queue_emoji = resolve_control_emoji(bot, "queue", snapshot, fallback="📜")
    fallback = resolve_control_emoji(SimpleNamespace(), "stop", snapshot, fallback="⏹️")

    assert isinstance(emoji, discord.PartialEmoji)
    assert emoji.name == "wg_skip"
    assert emoji.id == 123456789012345678
    assert isinstance(back_emoji, discord.PartialEmoji)
    assert back_emoji.name == "wg_back"
    assert back_emoji.id == 111456789012345678
    assert isinstance(queue_emoji, discord.PartialEmoji)
    assert queue_emoji.name == "wg_queue"
    assert fallback == "⏹️"


@pytest.mark.asyncio
async def test_registry_load_failure_uses_empty_registry() -> None:
    client = _FailingEmojiClient()

    registry = await ApplicationEmojiRegistry.load(client)
    emoji = registry.resolve("wg_skip", "⏭️")

    assert emoji == "⏭️"
    assert client.fetch_calls == 1
    assert client.create_calls == 0


def test_validate_application_emoji_assets_detects_missing_files(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    source = Path("assets/emojis/weasel_galaxy/v1/wg_like.png")

    for filename in list(APPLICATION_EMOJI_ASSETS.values())[:-1]:
        (root / filename).write_bytes(source.read_bytes())

    result = validate_application_emoji_assets(root)

    assert result.invalid_count == 1
    assert result.invalid_checks[0].stable_name == "wg_volume_down"
    assert result.invalid_checks[0].reason == "missing"


@pytest.mark.asyncio
async def test_sync_application_emojis_dry_run_does_not_create_duplicates(
    tmp_path: Path,
) -> None:
    root = _write_valid_emoji_pack(tmp_path)
    client = _RecordingEmojiClient(
        remote_emojis=[
            _FakeRemoteEmoji("wg_skip", 101),
            _FakeRemoteEmoji("wg_skip", 102),
        ]
    )

    result = await sync_application_emojis(client, asset_root=root, dry_run=True)

    assert result.created_count == 0
    assert result.existing_count == 1
    assert result.skipped_count == len(APPLICATION_EMOJI_NAMES) - 1
    assert client.create_calls == []


@pytest.mark.asyncio
async def test_sync_application_emojis_apply_creates_each_missing_name_once(
    tmp_path: Path,
) -> None:
    root = _write_valid_emoji_pack(tmp_path)
    client = _RecordingEmojiClient(remote_emojis=[])

    result = await sync_application_emojis(client, asset_root=root, dry_run=False)

    assert result.invalid_count == 0
    assert result.failed_count == 0
    assert result.created_count == len(APPLICATION_EMOJI_NAMES)
    assert sorted(name for name, _ in client.create_calls) == sorted(APPLICATION_EMOJI_NAMES)
    assert len(client.create_calls) == len(set(name for name, _ in client.create_calls))


@pytest.mark.asyncio
async def test_sync_application_emojis_apply_does_not_duplicate_existing_names(
    tmp_path: Path,
) -> None:
    root = _write_valid_emoji_pack(tmp_path)
    client = _RecordingEmojiClient(
        remote_emojis=[
            _FakeRemoteEmoji("wg_like", 101),
            _FakeRemoteEmoji("wg_like", 102),
            _FakeRemoteEmoji("wg_superlike", 103),
        ]
    )

    result = await sync_application_emojis(client, asset_root=root, dry_run=False)

    created_names = [name for name, _ in client.create_calls]
    assert result.existing_count == 2
    assert "wg_like" not in created_names
    assert "wg_superlike" not in created_names
    assert len(created_names) == len(APPLICATION_EMOJI_NAMES) - 2
    assert len(created_names) == len(set(created_names))


@pytest.mark.asyncio
async def test_registry_load_does_not_upload_during_ordinary_startup() -> None:
    client = _RecordingEmojiClient(remote_emojis=[_FakeRemoteEmoji("wg_skip", 101)])

    registry = await ApplicationEmojiRegistry.load(client)

    assert registry.resolve("wg_skip", "⏭️") != "⏭️"
    assert client.fetch_calls == 1
    assert client.create_calls == []


@pytest.mark.asyncio
async def test_control_center_buttons_use_application_emoji_registry(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    bot.application_emoji_registry = ApplicationEmojiRegistry(
        {
            "wg_back": discord.PartialEmoji(name="wg_back", id=222),
            "wg_skip": discord.PartialEmoji(name="wg_skip", id=333),
            "wg_queue": discord.PartialEmoji(name="wg_queue", id=444),
            "wg_more": discord.PartialEmoji(name="wg_more", id=555),
            "wg_volume_up": discord.PartialEmoji(name="wg_volume_up", id=556),
            "wg_volume_down": discord.PartialEmoji(name="wg_volume_down", id=557),
        }
    )
    guild = _FakeGuild(guild_id=123)
    bot.player_states.get_or_create(123).current_track = _indexed_track(database, "Artist/song.mp3")
    snapshot = NowPlayingPanelService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    view = ControlCenterView(bot, snapshot)
    ids_to_emojis = {
        button.custom_id: button.emoji
        for button in view.children
        if isinstance(button, discord.ui.Button)
    }

    assert isinstance(ids_to_emojis["weasel:controls:back"], discord.PartialEmoji)
    assert ids_to_emojis["weasel:controls:back"].id == 222
    assert isinstance(ids_to_emojis["weasel:controls:skip"], discord.PartialEmoji)
    assert ids_to_emojis["weasel:controls:skip"].id == 333
    assert isinstance(ids_to_emojis["weasel:controls:queue"], discord.PartialEmoji)
    assert ids_to_emojis["weasel:controls:queue"].id == 444
    assert isinstance(ids_to_emojis["weasel:controls:more"], discord.PartialEmoji)
    assert ids_to_emojis["weasel:controls:more"].id == 555
    assert isinstance(ids_to_emojis["weasel:controls:volume_up"], discord.PartialEmoji)
    assert ids_to_emojis["weasel:controls:volume_up"].id == 556
    assert isinstance(ids_to_emojis["weasel:controls:volume_down"], discord.PartialEmoji)
    assert ids_to_emojis["weasel:controls:volume_down"].id == 557


@pytest.mark.asyncio
async def test_now_playing_buttons_use_application_emoji_registry(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    bot.application_emoji_registry = ApplicationEmojiRegistry(
        {
            "wg_shuffle": discord.PartialEmoji(name="wg_shuffle", id=555),
            "wg_like": discord.PartialEmoji(name="wg_like", id=666),
            "wg_dislike": discord.PartialEmoji(name="wg_dislike", id=777),
            "wg_superlike": discord.PartialEmoji(name="wg_superlike", id=888),
            "wg_superdislike": discord.PartialEmoji(name="wg_superdislike", id=999),
        }
    )
    guild = _FakeGuild(guild_id=123)
    bot.player_states.get_or_create(123).current_track = _indexed_track(database, "Artist/song.mp3")
    snapshot = NowPlayingPanelService(bot).snapshot_for(guild)  # type: ignore[arg-type]

    shuffle_button = build_control_button(
        next(spec for spec in control_specs() if spec.key == "shuffle"),
        snapshot,
        bot,
    )
    like_button = build_control_button(
        next(spec for spec in control_specs() if spec.key == "like"),
        snapshot,
        bot,
    )
    dislike_button = build_control_button(
        next(spec for spec in control_specs() if spec.key == "dislike"),
        snapshot,
        bot,
    )
    superlike_button = build_control_button(
        next(spec for spec in control_specs() if spec.key == "superlike"),
        snapshot,
        bot,
    )
    superdislike_button = build_control_button(
        next(spec for spec in control_specs() if spec.key == "superdislike"),
        snapshot,
        bot,
    )

    assert isinstance(shuffle_button.emoji, discord.PartialEmoji)
    assert shuffle_button.emoji.id == 555
    assert isinstance(like_button.emoji, discord.PartialEmoji)
    assert like_button.emoji.id == 666
    assert isinstance(dislike_button.emoji, discord.PartialEmoji)
    assert dislike_button.emoji.id == 777
    assert isinstance(superlike_button.emoji, discord.PartialEmoji)
    assert superlike_button.emoji.id == 888
    assert isinstance(superdislike_button.emoji, discord.PartialEmoji)
    assert superdislike_button.emoji.id == 999


def test_loop_button_selects_visual_from_existing_loop_state() -> None:
    bot = SimpleNamespace(
        application_emoji_registry=ApplicationEmojiRegistry(
            {
                "wg_loop_off": discord.PartialEmoji(name="wg_loop_off", id=123),
                "wg_loop_on": discord.PartialEmoji(name="wg_loop_on", id=456),
            }
        )
    )

    loop_off = resolve_control_emoji(
        bot,
        "loop",
        SimpleNamespace(loop_enabled=False),
        fallback="🔁",
    )
    loop_on = resolve_control_emoji(
        bot,
        "loop",
        SimpleNamespace(loop_enabled=True),
        fallback="🔁",
    )

    assert isinstance(loop_off, discord.PartialEmoji)
    assert loop_off.name == "wg_loop_off"
    assert loop_off.id == 123
    assert isinstance(loop_on, discord.PartialEmoji)
    assert loop_on.name == "wg_loop_on"
    assert loop_on.id == 456


def test_pause_and_resume_share_play_pause_visual() -> None:
    registry = ApplicationEmojiRegistry(
        {"wg_play_pause": discord.PartialEmoji(name="wg_play_pause", id=321)}
    )
    bot = SimpleNamespace(application_emoji_registry=registry)

    pause = resolve_control_emoji(
        bot,
        "pause_resume",
        SimpleNamespace(status="Playing", loop_enabled=False),
        fallback="⏯️",
    )
    resume = resolve_control_emoji(
        bot,
        "pause_resume",
        SimpleNamespace(status="Paused", loop_enabled=False),
        fallback="⏯️",
    )

    assert pause is resume
    assert isinstance(pause, discord.PartialEmoji)
    assert pause.name == "wg_play_pause"


def test_main_grid_application_emoji_mapping_is_exact() -> None:
    registry = ApplicationEmojiRegistry(
        {
            name: discord.PartialEmoji(name=name, id=index)
            for index, name in enumerate(EXPECTED_EMOJI_NAMES, start=1)
        }
    )
    bot = SimpleNamespace(
        application_emoji_registry=registry,
        player_states=PlayerStateStore(),
    )
    snapshot = SimpleNamespace(
        guild_id=123,
        status="Playing",
        loop_enabled=False,
        has_track=True,
        previous_available=True,
        queue_length=2,
    )

    expected = {
        "previous": "wg_back",
        "pause_resume": "wg_play_pause",
        "next": "wg_skip",
        "stop": "wg_stop",
        "loop": "wg_loop_off",
        "volume_down": "wg_volume_down",
        "volume_up": "wg_volume_up",
        "shuffle": "wg_shuffle",
        "queue": "wg_queue",
        "more": "wg_more",
        "like": "wg_like",
        "superlike": "wg_superlike",
        "dislike": "wg_dislike",
        "superdislike": "wg_superdislike",
    }

    for spec in control_specs():
        button = build_control_button(spec, cast(Any, snapshot), bot)
        if spec.key == "toggle_playall_exception":
            assert str(button.emoji) == "➕"
            continue
        assert isinstance(button.emoji, discord.PartialEmoji)
        assert button.emoji.name == expected[spec.key]


def test_optional_exception_emojis_are_not_mandatory_sync_assets() -> None:
    assert "wg_exception_add" in OPTIONAL_APPLICATION_EMOJI_NAMES
    assert "wg_exception_remove" in OPTIONAL_APPLICATION_EMOJI_NAMES
    assert "wg_exception_add" not in APPLICATION_EMOJI_NAMES
    assert "wg_exception_remove" not in APPLICATION_EMOJI_NAMES
    assert "wg_exception_add" not in APPLICATION_EMOJI_ASSETS
    assert "wg_exception_remove" not in APPLICATION_EMOJI_ASSETS


def test_missing_application_emoji_uses_unicode_fallback() -> None:
    bot = SimpleNamespace(application_emoji_registry=ApplicationEmojiRegistry.empty())

    assert (
        resolve_control_emoji(
            bot,
            "superdislike",
            SimpleNamespace(loop_enabled=False),
            fallback="💀",
        )
        == "💀"
    )


def test_visual_mapping_does_not_change_ids_order_rows_or_labels() -> None:
    assert control_custom_ids() == (
        "weasel:now_playing:back",
        "weasel:now_playing:pause_resume",
        "weasel:now_playing:skip",
        "weasel:now_playing:stop",
        "weasel:now_playing:loop",
        "weasel:now_playing:volume_down",
        "weasel:now_playing:volume_up",
        "weasel:now_playing:shuffle",
        "weasel:now_playing:queue",
        "weasel:now_playing:more",
        "weasel:now_playing:like",
        "weasel:now_playing:superlike",
        PLAY_ALL_EXCEPTION_CONTROL_CUSTOM_ID,
        "weasel:now_playing:dislike",
        "weasel:now_playing:superdislike",
    )
    assert tuple(spec.row for spec in control_specs()) == (
        0,
        0,
        0,
        0,
        0,
        1,
        1,
        1,
        1,
        1,
        2,
        2,
        2,
        2,
        2,
    )
    assert tuple(spec.label for spec in control_specs()) == (None,) * 15
    assert all(spec.style is discord.ButtonStyle.secondary for spec in control_specs())
    assert control_center_custom_ids() == (
        "weasel:controls:back",
        "weasel:controls:pause_resume",
        "weasel:controls:skip",
        "weasel:controls:stop",
        "weasel:controls:loop",
        "weasel:controls:volume_down",
        "weasel:controls:volume_up",
        "weasel:controls:shuffle",
        "weasel:controls:queue",
        "weasel:controls:more",
        "weasel:controls:like",
        "weasel:controls:superlike",
        "weasel:controls:playall_exception",
        "weasel:controls:dislike",
        "weasel:controls:superdislike",
        "weasel:controls:open",
    )


class _FailingEmojiClient:
    application_id = 1

    def __init__(self) -> None:
        self.fetch_calls = 0
        self.create_calls = 0

    async def fetch_application_emojis(self) -> list[object]:
        self.fetch_calls += 1
        raise RuntimeError("boom")

    async def create_application_emoji(self, *args: Any, **kwargs: Any) -> object:
        self.create_calls += 1
        raise AssertionError("create_application_emoji must not be called")


class _RecordingEmojiClient:
    application_id = 1

    def __init__(self, remote_emojis: list[object]) -> None:
        self.remote_emojis = remote_emojis
        self.fetch_calls = 0
        self.create_calls: list[tuple[str, int]] = []

    async def fetch_application_emojis(self) -> list[object]:
        self.fetch_calls += 1
        return list(self.remote_emojis)

    async def create_application_emoji(self, *, name: str, image: bytes) -> object:
        self.create_calls.append((name, len(image)))
        return SimpleNamespace(id=10_000 + len(self.create_calls), name=name)


class _FakeRemoteEmoji:
    def __init__(self, name: str, emoji_id: int) -> None:
        self.name = name
        self.id = emoji_id

    def _to_partial(self) -> discord.PartialEmoji:
        return discord.PartialEmoji(name=self.name, id=self.id)


def _write_valid_emoji_pack(tmp_path: Path) -> Path:
    root = tmp_path / "assets"
    root.mkdir()
    source = Path("assets/emojis/weasel_galaxy/v1/wg_like.png")
    data = source.read_bytes()
    for filename in APPLICATION_EMOJI_ASSETS.values():
        (root / filename).write_bytes(data)
    return root


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


class _FakeGuild:
    def __init__(self, *, guild_id: int) -> None:
        self.id = guild_id


class _FakeBot:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        self.player_states = PlayerStateStore()
        self.now_playing_panels = NowPlayingPanelRegistry()
        self.lavalink_available = True
        self.settings = SimpleNamespace(bot=SimpleNamespace(music_library=Path("/music")))
        self.application_emoji_registry = ApplicationEmojiRegistry.empty()
