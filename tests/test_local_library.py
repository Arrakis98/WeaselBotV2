from __future__ import annotations

from pathlib import Path

import pytest

from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.models import Track
from weasel_bot_v2.repositories import TrackRepository
from weasel_bot_v2.services.local_library import (
    LocalLibraryService,
    safe_relative_path,
    select_mp3_tracks,
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
    for extension in (".mp3", ".flac", ".wav", ".ogg", ".m4a"):
        _write_audio(music_root / f"track{extension}")

    result = service.scan()

    assert result.found == 5
    assert tracks.count_local() == 5


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


def test_list_indexed_mp3_tracks_ignores_non_mp3_extensions(
    library: tuple[Path, LocalLibraryService, TrackRepository],
) -> None:
    music_root, service, _ = library
    _write_audio(music_root / "one.mp3")
    _write_audio(music_root / "two.flac")
    _write_audio(music_root / "three.MP3")
    service.scan()

    mp3_tracks = service.list_indexed_mp3_tracks()

    assert [track.relative_path for track in mp3_tracks] == ["one.mp3", "three.MP3"]


def test_select_mp3_tracks_filters_by_extension_only() -> None:
    tracks = [
        _track("one.mp3", ".mp3"),
        _track("two.flac", ".flac"),
        _track("three.MP3", ".MP3"),
        _track("missing-extension", None),
    ]

    assert [track.relative_path for track in select_mp3_tracks(tracks)] == [
        "one.mp3",
        "three.MP3",
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
