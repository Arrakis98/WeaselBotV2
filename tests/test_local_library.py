from __future__ import annotations

from pathlib import Path

import pytest

from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import QuarantineRecord, Rating, Track, UserRecord
from weasel_bot_v2.repositories import (
    QuarantineRepository,
    RatingRepository,
    TrackRepository,
    TrackVolumeOverrideRepository,
    UserRepository,
)
from weasel_bot_v2.services.local_library import (
    LocalLibraryService,
    safe_relative_path,
    select_play_all_eligible_tracks,
)


@pytest.fixture
def library(tmp_path: Path) -> tuple[Path, LocalLibraryService, TrackRepository]:
    database = SQLiteDatabase(DatabaseConfig(path=tmp_path / "weasel.db"))
    database.initialize()
    music_root = tmp_path / "music"
    music_root.mkdir()
    tracks = TrackRepository(database)
    return music_root, LocalLibraryService(music_root=music_root, tracks=tracks), tracks


def test_recursive_scan_stores_relative_paths_and_infers_metadata(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, tracks = library
    _write_audio(music_root / "song.mp3")
    _write_audio(music_root / "Artist" / "artist song.mp3")
    _write_audio(music_root / "France" / "Renaud" / "Mistral gagnant.mp3")
    _write_audio(music_root / "notes.txt")

    result = service.scan()

    assert result.found == 3
    assert result.upserted == 3
    assert result.marked_unavailable == 0
    assert result.skipped == 0

    direct = tracks.get_local_by_relative_path("song.mp3")
    artist = tracks.get_local_by_relative_path("Artist/artist song.mp3")
    categorized = tracks.get_local_by_relative_path("France/Renaud/Mistral gagnant.mp3")

    assert direct is not None
    assert direct.category_guess is None
    assert direct.artist_guess is None
    assert direct.relative_path == "song.mp3"

    assert artist is not None
    assert artist.category_guess is None
    assert artist.artist_guess == "Artist"

    assert categorized is not None
    assert categorized.category_guess == "France"
    assert categorized.artist_guess == "Renaud"
    assert categorized.display_title == "Mistral gagnant"
    assert categorized.extension == ".mp3"


def test_scan_supports_common_audio_extensions(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, tracks = library
    for extension in (".mp3", ".flac", ".wav", ".ogg", ".m4a", ".opus"):
        _write_audio(music_root / f"track{extension}")

    result = service.scan()

    assert result.found == 6
    assert tracks.count_local() == 6
    opus = tracks.get_local_by_relative_path("track.opus")
    assert opus is not None
    assert opus.extension == ".opus"


def test_scan_ignores_unsupported_extensions(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, tracks = library
    _write_audio(music_root / "track.opus")
    _write_audio(music_root / "cover.jpg")
    _write_audio(music_root / "notes.txt")

    result = service.scan()

    assert result.found == 1
    assert tracks.count_local() == 1
    assert tracks.get_local_by_relative_path("track.opus") is not None


def test_scan_skips_symlink_that_escapes_music_root(
    library: tuple[Path, LocalLibraryService, TrackRepository],
    tmp_path: Path,
) -> None:
    music_root, service, tracks = library
    outside = tmp_path / "outside.mp3"
    _write_audio(outside)
    (music_root / "escape.mp3").symlink_to(outside)

    result = service.scan()

    assert result.found == 0
    assert result.skipped == 1
    assert tracks.count_local() == 0


def test_search_matches_filename_artist_category_and_accents(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, _ = library
    _write_audio(music_root / "France" / "Renaud" / "Mistral gagnant.mp3")
    _write_audio(music_root / "Anime" / "Composer" / "Opening.mp3")
    service.scan()

    assert service.search("mistral")[0].relative_path == "France/Renaud/Mistral gagnant.mp3"
    assert service.search("renaud")[0].relative_path == "France/Renaud/Mistral gagnant.mp3"
    assert service.search("france")[0].relative_path == "France/Renaud/Mistral gagnant.mp3"
    assert service.search("gagnánt")[0].relative_path == "France/Renaud/Mistral gagnant.mp3"
    assert service.search("anime")[0].relative_path == "Anime/Composer/Opening.mp3"


def test_search_finds_opus_after_scan(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, _ = library
    _write_audio(music_root / "France" / "Renaud" / "Mistral gagnant.opus")
    service.scan()

    match = service.search("mistral")[0]

    assert match.relative_path == "France/Renaud/Mistral gagnant.opus"
    assert match.extension == ".opus"


def test_scan_upserts_existing_local_track(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, tracks = library
    track_path = music_root / "Artist" / "song.mp3"
    _write_audio(track_path, content=b"first")
    service.scan()
    first = tracks.get_local_by_relative_path("Artist/song.mp3")
    assert first is not None

    _write_audio(track_path, content=b"second version")
    service.scan()
    second = tracks.get_local_by_relative_path("Artist/song.mp3")

    assert second is not None
    assert second.id == first.id
    assert second.size_bytes == len(b"second version")
    assert tracks.count_local() == 1


def test_scan_marks_missing_previously_available_tracks_unavailable(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, tracks = library
    kept_path = music_root / "kept.mp3"
    missing_path = music_root / "missing.mp3"
    _write_audio(kept_path)
    _write_audio(missing_path)
    service.scan()
    missing = tracks.get_local_by_relative_path("missing.mp3")
    assert missing is not None
    assert missing.is_available is True

    missing_path.unlink()
    result = service.scan()

    assert result.found == 1
    assert result.upserted == 1
    assert result.marked_unavailable == 1
    assert tracks.get_local_by_relative_path("kept.mp3") is not None
    stale = tracks.get_local_by_relative_path("missing.mp3")
    assert stale is not None
    assert stale.is_available is False
    assert tracks.count_local() == 1


def test_scan_does_not_delete_stale_rows(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, tracks = library
    stale_path = music_root / "stale.mp3"
    _write_audio(stale_path)
    service.scan()
    indexed = tracks.get_local_by_relative_path("stale.mp3")
    assert indexed is not None

    stale_path.unlink()
    service.scan()

    assert tracks.get(indexed.id or 0) is not None
    assert [track.relative_path for track in tracks.list_local()] == ["stale.mp3"]


def test_scan_preserves_track_id_ratings_and_volume_references(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, tracks = library
    database = tracks.database
    track_path = music_root / "Artist" / "preset.mp3"
    _write_audio(track_path)
    service.scan()
    indexed = tracks.get_local_by_relative_path("Artist/preset.mp3")
    assert indexed is not None
    assert indexed.id is not None
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Tester"))
    RatingRepository(database).set_rating(
        Rating(
            guild_id=123,
            user_id=42,
            track_id=indexed.id,
            rating="like",
        )
    )
    TrackVolumeOverrideRepository(database).save(123, indexed.id, 135)

    track_path.unlink()
    service.scan()

    stale = tracks.get_local_by_relative_path("Artist/preset.mp3")
    assert stale is not None
    assert stale.id == indexed.id
    assert stale.is_available is False
    assert RatingRepository(database).get_rating(123, 42, indexed.id) is not None
    assert TrackVolumeOverrideRepository(database).get(123, indexed.id) is not None


def test_scan_reactivates_previously_unavailable_track_when_file_returns(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, tracks = library
    track_path = music_root / "returning.opus"
    _write_audio(track_path)
    service.scan()
    indexed = tracks.get_local_by_relative_path("returning.opus")
    assert indexed is not None
    assert indexed.id is not None

    track_path.unlink()
    service.scan()
    unavailable = tracks.get_local_by_relative_path("returning.opus")
    assert unavailable is not None
    assert unavailable.is_available is False

    _write_audio(track_path, content=b"back")
    result = service.scan()
    reactivated = tracks.get_local_by_relative_path("returning.opus")

    assert result.found == 1
    assert result.marked_unavailable == 0
    assert reactivated is not None
    assert reactivated.id == indexed.id
    assert reactivated.is_available is True
    assert reactivated.size_bytes == len(b"back")


def test_scan_does_not_reactivate_track_with_active_quarantine(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, _, tracks = library
    database = tracks.database
    quarantine = QuarantineRepository(database)
    service = LocalLibraryService(music_root=music_root, tracks=tracks, quarantine=quarantine)
    track_path = music_root / "quarantined-returned.mp3"
    _write_audio(track_path)
    service.scan()
    indexed = tracks.get_local_by_relative_path("quarantined-returned.mp3")
    assert indexed is not None
    assert indexed.id is not None
    UserRepository(database).upsert(UserRecord(user_id=42, display_name="Tester"))
    tracks.set_available(indexed.id, False)
    quarantine.create(
        QuarantineRecord(
            track_id=indexed.id,
            guild_id=123,
            requested_by_user_id=42,
            reason="superdislike",
            original_relative_path="quarantined-returned.mp3",
            quarantine_relative_path="superdislike/quarantined-returned.mp3",
        )
    )

    result = service.scan()
    still_quarantined = tracks.get_local_by_relative_path("quarantined-returned.mp3")

    assert result.found == 1
    assert result.upserted == 1
    assert result.marked_unavailable == 0
    assert still_quarantined is not None
    assert still_quarantined.id == indexed.id
    assert still_quarantined.is_available is False


def test_scan_does_not_remark_already_unavailable_missing_tracks(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, tracks = library
    missing_path = music_root / "quarantined.mp3"
    _write_audio(missing_path)
    service.scan()
    indexed = tracks.get_local_by_relative_path("quarantined.mp3")
    assert indexed is not None
    assert indexed.id is not None
    tracks.set_available(indexed.id, False)
    missing_path.unlink()

    result = service.scan()

    assert result.marked_unavailable == 0
    still_unavailable = tracks.get_local_by_relative_path("quarantined.mp3")
    assert still_unavailable is not None
    assert still_unavailable.is_available is False


def test_play_all_eligible_tracks_exclude_stale_unavailable_tracks(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, _ = library
    kept_path = music_root / "kept.opus"
    stale_path = music_root / "stale.mp3"
    _write_audio(kept_path)
    _write_audio(stale_path)
    service.scan()

    stale_path.unlink()
    service.scan()

    assert [track.relative_path for track in service.list_play_all_eligible_tracks()] == [
        "kept.opus"
    ]


def test_list_play_all_eligible_tracks_includes_mp3_and_opus_only(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, _ = library
    _write_audio(music_root / "one.mp3")
    _write_audio(music_root / "two.flac")
    _write_audio(music_root / "three.MP3")
    _write_audio(music_root / "four.opus")
    service.scan()

    play_all_tracks = service.list_play_all_eligible_tracks()

    assert [track.relative_path for track in play_all_tracks] == [
        "four.opus",
        "one.mp3",
        "three.MP3",
    ]


def test_select_play_all_eligible_tracks_filters_by_extension_only() -> None:
    tracks = [
        _track("one.mp3", ".mp3"),
        _track("two.flac", ".flac"),
        _track("three.MP3", ".MP3"),
        _track("four.opus", ".opus"),
        _track("missing-extension", None),
    ]

    assert [track.relative_path for track in select_play_all_eligible_tracks(tracks)] == [
        "one.mp3",
        "three.MP3",
        "four.opus",
    ]


def test_safe_relative_path_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        safe_relative_path("../outside.mp3")

    with pytest.raises(ValueError):
        safe_relative_path("/music/song.mp3")


def _write_audio(path: Path, *, content: bytes = b"audio") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _track(relative_path: str, extension: str | None) -> Track:
    return Track(
        source="local",
        source_id=relative_path,
        relative_path=relative_path,
        file_name=relative_path,
        display_title=relative_path,
        extension=extension,
    )
