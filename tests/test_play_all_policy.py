from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

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
from weasel_bot_v2.services.local_library import LocalLibraryService
from weasel_bot_v2.services.now_playing_panel import NowPlayingPanelRegistry
from weasel_bot_v2.services.play_all_policy import PlayAllPolicyService
from weasel_bot_v2.services.player_state import PlayerStateStore


@pytest.fixture
def database(tmp_path: Path) -> SQLiteDatabase:
    sqlite_database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel-test.db"))
    sqlite_database.initialize()
    return sqlite_database


def test_policy_persistence_normalization_and_guild_isolation(database: SQLiteDatabase) -> None:
    service = _policy_service(database)
    gims = _track(database, "Pop/GIMS/a.mp3", artist="GIMS")
    artist_b = _track(database, "Pop/Artist B/b.mp3", artist="Artist B")
    other_gims = _track(database, "Pop/Gíms/c.mp3", artist="Gíms")

    first = service.add_artist_exclusion(
        guild_id=123,
        user_id=42,
        display_name="Admin",
        artist_query="gíms",
    )
    duplicate = service.add_artist_exclusion(
        guild_id=123,
        user_id=42,
        display_name="Admin",
        artist_query="GIMS",
    )
    second = service.add_artist_exclusion(
        guild_id=123,
        user_id=42,
        display_name="Admin",
        artist_query="Artist B",
    )
    service.add_track_exception(
        guild_id=123,
        user_id=42,
        display_name="Admin",
        track_query="a",
    )
    service.add_track_exception(
        guild_id=123,
        user_id=42,
        display_name="Admin",
        track_query="b",
    )
    service.set_strict(guild_id=123, user_id=42, display_name="Admin", enabled=True)
    service.remove_artist_exclusion(guild_id=123, artist_query="GIMS")

    summary = service.summary(123)
    other_guild = service.summary(999)
    assert first.created is True
    assert duplicate.created is False
    assert second.created is True
    assert [exclusion.display_artist for exclusion in summary.exclusions] == ["Artist B"]
    assert len(summary.exceptions) == 2
    assert summary.policy.strict_exclusions is True
    assert other_guild.exclusions == ()
    assert other_guild.exceptions == ()
    assert other_guild.policy.strict_exclusions is False
    assert {gims.id, artist_b.id, other_gims.id}


def test_play_all_filter_supports_multiple_exclusions_and_exceptions(
    database: SQLiteDatabase,
) -> None:
    service = _policy_service(database)
    gims_keep = _track(database, "Pop/GIMS/Balader.mp3", artist="GIMS")
    gims_drop = _track(database, "Pop/GIMS/Drop.mp3", artist="GIMS")
    b_keep = _track(database, "Rock/Artist B/Special.mp3", artist="Artist B")
    b_drop = _track(database, "Rock/Artist B/Other.mp3", artist="Artist B")
    other = _track(database, "Rock/Other/Free.mp3", artist="Other")
    _exclude(service, "GIMS")
    _exclude(service, "Artist B")
    _exception(service, "Balader")
    _exception(service, "Special")

    eligible = service.eligible_tracks_for_play_all(123)

    assert _ids(eligible) == _ids([gims_keep, b_keep, other])
    assert gims_drop.id not in _ids(eligible)
    assert b_drop.id not in _ids(eligible)


def test_play_all_eligible_pool_includes_opus_and_keeps_mp3_behavior(
    database: SQLiteDatabase,
) -> None:
    service = _policy_service(database)
    mp3 = _track(database, "Pop/Artist/One.mp3", artist="Artist")
    opus = _track(database, "Pop/Artist/Two.opus", artist="Artist", extension=".opus")
    _track(database, "Pop/Artist/Three.flac", artist="Artist", extension=".flac")

    eligible = service.eligible_tracks_for_play_all(123)

    assert _ids(eligible) == _ids([mp3, opus])


def test_play_all_filter_exclusions_and_exceptions_work_with_opus(
    database: SQLiteDatabase,
) -> None:
    service = _policy_service(database)
    keep = _track(database, "Pop/GIMS/Keep.opus", artist="GIMS", extension=".opus")
    drop = _track(database, "Pop/GIMS/Drop.opus", artist="GIMS", extension=".opus")
    other = _track(database, "Pop/Other/Free.opus", artist="Other", extension=".opus")
    _exclude(service, "GIMS")
    _exception(service, "Keep")

    eligible = service.eligible_tracks_for_play_all(123)

    assert _ids(eligible) == _ids([keep, other])
    assert drop.id not in _ids(eligible)


def test_ratings_and_volume_overrides_can_be_stored_for_opus_tracks(
    database: SQLiteDatabase,
) -> None:
    track = _track(database, "Pop/Artist/Track.opus", artist="Artist", extension=".opus")
    assert track.id is not None

    RatingRepository(database).set_rating(
        Rating(guild_id=123, user_id=42, track_id=track.id, rating="superlike")
    )
    TrackVolumeOverrideRepository(database).save(123, track.id, 135)

    saved_rating = RatingRepository(database).get_rating(123, 42, track.id)
    saved_volume = TrackVolumeOverrideRepository(database).get(123, track.id)
    assert saved_rating is not None and saved_rating.rating == "superlike"
    assert saved_volume is not None and saved_volume.volume == 135


def test_invocation_exclusions_parse_multiple_artists_and_deduplicate(
    database: SQLiteDatabase,
) -> None:
    service = _policy_service(database)
    _track(database, "Pop/GIMS/One.mp3", artist="GIMS")
    _track(database, "Pop/Gíms/Two.mp3", artist="Gíms")
    _track(database, "Rock/Sardou/Three.mp3", artist="Michel Sardou")

    resolution = service.resolve_invocation_exclusions(" GIMS, gims, Gíms, Michel Sardou ,, ")

    assert resolution.ok is True
    assert resolution.excluded_artist_keys == frozenset({"gims", "michel sardou"})
    assert resolution.display_artists == ("GIMS", "Michel Sardou")


def test_invocation_exclusions_filter_several_artists_without_persisting(
    database: SQLiteDatabase,
) -> None:
    service = _policy_service(database)
    gims = _track(database, "Pop/GIMS/One.mp3", artist="GIMS")
    sardou = _track(database, "Rock/Sardou/Two.mp3", artist="Michel Sardou")
    other = _track(database, "Rock/Other/Three.mp3", artist="Other")
    resolution = service.resolve_invocation_exclusions("gíms, michel sardou")

    pool = service.filter_tracks_for_play_all(
        123,
        [gims, sardou, other],
        excluded_artist_keys=resolution.excluded_artist_keys,
        use_exceptions=True,
    )

    assert _ids(list(pool.eligible_tracks)) == _ids([other])
    assert service.summary(123).exclusions == ()


def test_strict_mode_ignores_and_then_reactivates_stored_exceptions(
    database: SQLiteDatabase,
) -> None:
    service = _policy_service(database)
    keep = _track(database, "Pop/GIMS/Keep.mp3", artist="GIMS")
    drop = _track(database, "Pop/GIMS/Drop.mp3", artist="GIMS")
    other = _track(database, "Pop/Other/Free.mp3", artist="Other")
    _exclude(service, "GIMS")
    _exception(service, "Keep")

    service.set_strict(guild_id=123, user_id=42, display_name="Admin", enabled=True)
    strict_ids = _ids(service.eligible_tracks_for_play_all(123))
    service.set_strict(guild_id=123, user_id=42, display_name="Admin", enabled=False)
    relaxed_ids = _ids(service.eligible_tracks_for_play_all(123))

    assert strict_ids == _ids([other])
    assert relaxed_ids == _ids([keep, other])
    assert drop.id not in relaxed_ids


def test_unavailable_exception_remains_ineligible_and_search_remains_unaffected(
    database: SQLiteDatabase,
) -> None:
    service = _policy_service(database)
    keep = _track(database, "Pop/GIMS/Keep.mp3", artist="GIMS")
    _track(database, "Pop/GIMS/Drop.mp3", artist="GIMS")
    _track(database, "Pop/Other/Free.mp3", artist="Other")
    _exclude(service, "GIMS")
    _exception(service, "Keep")
    TrackRepository(database).set_available(keep.id or 0, False)

    eligible = service.eligible_tracks_for_play_all(123)
    search_results = LocalLibraryService(Path("/music"), TrackRepository(database)).search(
        "Drop",
        limit=5,
    )

    assert keep.id not in _ids(eligible)
    assert [track.display_title for track in search_results] == ["Drop"]


@pytest.mark.asyncio
async def test_play_all_invocation_exclusions_do_not_mutate_existing_queue(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    cog = MusicCog(cast(Any, bot))
    current = _track(database, "Pop/Other/Current.mp3", artist="Other")
    queued = _track(database, "Pop/GIMS/AlreadyQueued.mp3", artist="GIMS")
    allowed = _track(database, "Pop/Other/Allowed.mp3", artist="Other")
    _track(database, "Pop/GIMS/Blocked.mp3", artist="GIMS")
    state = bot.player_states.get_or_create(123)
    state.current_track = current
    state.upcoming = [queued]
    guild = _FakeGuild(guild_id=123, voice_client=object())
    interaction = _FakeInteraction(guild=guild)

    await _run_slash(cog, "play_all", interaction, "GIMS", True)

    assert state.upcoming[0] == queued
    assert allowed in state.upcoming
    assert all(track.artist_guess != "GIMS" or track == queued for track in state.upcoming)
    assert "Added to queue" in interaction.followup_messages[0]
    assert _policy_service(database).summary(123).exclusions == ()


@pytest.mark.asyncio
async def test_play_all_empty_invocation_pool_returns_clear_response(
    database: SQLiteDatabase,
) -> None:
    bot = _FakeBot(database)
    cog = MusicCog(cast(Any, bot))
    _track(database, "Pop/GIMS/Blocked.mp3", artist="GIMS")
    interaction = _FakeInteraction(guild=_FakeGuild(guild_id=123, voice_client=None))

    await _run_slash(cog, "play_all", interaction, "GIMS", True)

    assert interaction.followup_ephemeral == [True]
    assert "removed every Play All track" in interaction.followup_messages[0]


@pytest.mark.asyncio
async def test_play_all_unknown_and_ambiguous_invocation_exclusions_do_not_mutate_queue(
    database: SQLiteDatabase,
) -> None:
    _track(database, "Pop/Alpha/One.mp3", artist="Alpha")
    _track(database, "Pop/Alpine/Two.mp3", artist="Alpine")
    bot = _FakeBot(database)
    cog = MusicCog(cast(Any, bot))
    unknown = _FakeInteraction(guild=_FakeGuild(guild_id=123, voice_client=None))
    ambiguous = _FakeInteraction(guild=_FakeGuild(guild_id=123, voice_client=None))

    await _run_slash(cog, "play_all", unknown, "Unknown", True)
    await _run_slash(cog, "play_all", ambiguous, "Al", True)

    assert "unknown: Unknown" in unknown.followup_messages[0]
    assert "ambiguous: Al" in ambiguous.followup_messages[0]
    assert bot.player_states.get_or_create(123).upcoming == []


@pytest.mark.asyncio
async def test_play_all_exceptions_are_invocation_scoped_and_strict_flag_is_not_persisted(
    database: SQLiteDatabase,
) -> None:
    keep = _track(database, "Pop/GIMS/Keep.mp3", artist="GIMS")
    drop = _track(database, "Pop/GIMS/Drop.mp3", artist="GIMS")
    other = _track(database, "Pop/Other/Free.mp3", artist="Other")
    current = _track(database, "Pop/Current/Current.mp3", artist="Current")
    _exception(_policy_service(database), "Keep")
    bot = _FakeBot(database)
    bot.player_states.get_or_create(123).current_track = current
    cog = MusicCog(cast(Any, bot))
    with_exceptions = _FakeInteraction(guild=_FakeGuild(guild_id=123, voice_client=object()))
    strict = _FakeInteraction(guild=_FakeGuild(guild_id=123, voice_client=object()))

    await _run_slash(cog, "play_all", with_exceptions, "gíms", True)
    first_state = bot.player_states.get_or_create(123)
    first_ids = _ids(first_state.upcoming)
    first_state.upcoming = []
    await _run_slash(cog, "play_all", strict, "GIMS", False)
    second_state = bot.player_states.get_or_create(123)
    second_ids = _ids(second_state.upcoming)

    assert keep.id in first_ids
    assert other.id in first_ids
    assert drop.id not in first_ids
    assert keep.id not in second_ids
    assert other.id in second_ids
    assert _policy_service(database).summary(123).exclusions == ()
    assert _policy_service(database).summary(123).policy.strict_exclusions is False


@pytest.mark.asyncio
async def test_playall_exception_command_adds_removes_and_enforces_permissions(
    database: SQLiteDatabase,
) -> None:
    track = _track(database, "Pop/GIMS/Balader.mp3", artist="GIMS")
    assert track.id is not None
    bot = _FakeBot(database)
    cog = MusicCog(cast(Any, bot))
    denied = _FakeInteraction(
        guild=_FakeGuild(guild_id=123, voice_client=None),
        administrator=False,
    )
    allowed = _FakeInteraction(guild=_FakeGuild(guild_id=123, voice_client=None))

    await _run_slash(cog, "playall_exception", denied, "Balader", True)
    await _run_slash(cog, "playall_exception", allowed, "Balader", True)
    assert "Only an administrator" in denied.response_messages[0]
    assert "Added exception" in allowed.response_messages[0]
    assert PlayAllPolicyRepository(database).has_track_exception(guild_id=123, track_id=track.id)

    await _run_slash(cog, "playall_exception", allowed, "Balader", False)
    assert "Removed exception" in allowed.response_messages[1]
    assert not PlayAllPolicyRepository(database).has_track_exception(
        guild_id=123,
        track_id=track.id,
    )


@pytest.mark.asyncio
async def test_playall_exception_rejects_unknown_ambiguous_and_unavailable_tracks(
    database: SQLiteDatabase,
) -> None:
    unavailable = _track(database, "Pop/GIMS/Unavailable.mp3", artist="GIMS")
    _track(database, "Pop/Alpha/One.mp3", artist="Alpha")
    _track(database, "Pop/Alpine/Two.mp3", artist="Alpine")
    assert unavailable.id is not None
    TrackRepository(database).set_available(unavailable.id, False)
    cog = MusicCog(cast(Any, _FakeBot(database)))
    interaction = _FakeInteraction(guild=_FakeGuild(guild_id=123, voice_client=None))

    await _run_slash(cog, "playall_exception", interaction, "Missing", True)
    await _run_slash(cog, "playall_exception", interaction, "Al", True)
    await _run_slash(cog, "playall_exception", interaction, "Unavailable", True)

    assert "No indexed available track matched" in interaction.response_messages[0]
    assert "ambiguous" in interaction.response_messages[1]
    assert "No indexed available track matched" in interaction.response_messages[2]
    assert PlayAllPolicyRepository(database).list_track_exceptions(123) == []


def test_play_all_command_surface_is_simplified() -> None:
    command_names = {command.name for command in MusicCog.__cog_app_commands__}

    assert {
        "playall_exclude_artist",
        "playall_unexclude_artist",
        "playall_exclusions",
        "playall_add_exception",
        "playall_remove_exception",
        "playall_exceptions",
        "playall_strict",
        "playall_policy",
    }.isdisjoint(command_names)
    assert "play_all" in command_names
    assert "playall_exception" in command_names
    play_all = cast(
        Any,
        next(command for command in MusicCog.__cog_app_commands__ if command.name == "play_all"),
    )
    assert {parameter.name for parameter in play_all.parameters} >= {
        "exclusions",
        "use_exceptions",
    }
    assert "MP3" not in play_all.description


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


def _policy_service(database: SQLiteDatabase) -> PlayAllPolicyService:
    return PlayAllPolicyService(
        policy=PlayAllPolicyRepository(database),
        tracks=TrackRepository(database),
        users=UserRepository(database),
        library=LocalLibraryService(Path("/music"), TrackRepository(database)),
    )


def _track(
    database: SQLiteDatabase,
    relative_path: str,
    *,
    artist: str,
    extension: str | None = None,
) -> Track:
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Admin"))
    return TrackRepository(database).upsert_local(
        Track(
            source="local",
            source_id=relative_path,
            relative_path=relative_path,
            file_name=Path(relative_path).name,
            display_title=Path(relative_path).stem,
            title=Path(relative_path).stem,
            artist=artist,
            artist_guess=artist,
            category_guess="Pop",
            extension=extension or Path(relative_path).suffix.lower(),
        )
    )


def _exclude(service: PlayAllPolicyService, artist: str) -> None:
    result = service.add_artist_exclusion(
        guild_id=123,
        user_id=42,
        display_name="Admin",
        artist_query=artist,
    )
    assert result.ok is True


def _exception(service: PlayAllPolicyService, track: str) -> None:
    result = service.add_track_exception(
        guild_id=123,
        user_id=42,
        display_name="Admin",
        track_query=track,
    )
    assert result.ok is True


def _ids(tracks: list[Track]) -> set[int | None]:
    return {track.id for track in tracks}


class _FakeBot:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        self.player_states = PlayerStateStore()
        self.now_playing_panels = NowPlayingPanelRegistry()
        self.lavalink_available = True
        self.settings = SimpleNamespace(bot=SimpleNamespace(music_library=Path("/music")))
        self.channels: dict[int, object] = {}


class _FakeGuild:
    def __init__(self, *, guild_id: int, voice_client: object | None) -> None:
        self.id = guild_id
        self.voice_client = voice_client


class _FakeInteraction:
    def __init__(self, *, guild: _FakeGuild, administrator: bool = True) -> None:
        self.guild = guild
        self.user = SimpleNamespace(
            id=42,
            display_name="Admin",
            guild_permissions=SimpleNamespace(administrator=administrator),
        )
        self.channel = None
        self.response = _FakeResponse(self)
        self.followup = _FakeFollowup(self)
        self.response_messages: list[str] = []
        self.response_ephemeral: list[bool] = []
        self.followup_messages: list[str] = []
        self.followup_ephemeral: list[bool] = []
        self.followup_views: list[object | None] = []
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
        ephemeral: bool = False,
        view: object | None = None,
    ) -> None:
        self._done = True
        self.interaction.response_messages.append(message)
        self.interaction.response_ephemeral.append(ephemeral)


class _FakeFollowup:
    def __init__(self, interaction: _FakeInteraction) -> None:
        self.interaction = interaction

    async def send(
        self,
        message: str,
        *,
        ephemeral: bool = False,
        view: object | None = None,
    ) -> None:
        self.interaction.followup_messages.append(message)
        self.interaction.followup_ephemeral.append(ephemeral)
        self.interaction.followup_views.append(view)
