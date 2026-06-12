from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from weasel_bot_v2.services.audio import (
    LocalTrackLoadError,
    build_lavalink_local_identifier,
    normalize_lavalink_track_load,
)


def test_local_identifier_builder_for_simple_file() -> None:
    identifier = build_lavalink_local_identifier(
        music_root=Path("/music"),
        relative_path="song.mp3",
    )

    assert identifier == "/music/song.mp3"


def test_local_identifier_builder_for_nested_relative_path() -> None:
    identifier = build_lavalink_local_identifier(
        music_root=Path("/music"),
        relative_path="France/Renaud/Mistral gagnant.mp3",
    )

    assert identifier == "/music/France/Renaud/Mistral gagnant.mp3"


def test_local_identifier_builder_preserves_spaces_and_accents() -> None:
    identifier = build_lavalink_local_identifier(
        music_root=Path("/music"),
        relative_path="Québec/Les Cowboys Fringants/Les étoiles filantes.mp3",
    )

    assert identifier == "/music/Québec/Les Cowboys Fringants/Les étoiles filantes.mp3"


def test_local_identifier_builder_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        build_lavalink_local_identifier(
            music_root=Path("/music"),
            relative_path="../outside.mp3",
        )


def test_local_identifier_builder_rejects_absolute_host_path() -> None:
    with pytest.raises(ValueError):
        build_lavalink_local_identifier(
            music_root=Path("/music"),
            relative_path="/media/arrakis/sda1/bot_musique/musiques/song.mp3",
        )


def test_local_identifier_builder_does_not_leak_host_path_when_root_is_container_path() -> None:
    identifier = build_lavalink_local_identifier(
        music_root=Path("/music"),
        relative_path="Artist/song.mp3",
    )

    assert identifier == "/music/Artist/song.mp3"
    assert "/media/" not in identifier


def test_normalize_lavalink_track_load_handles_v4_track_dict_payload() -> None:
    track_data = {
        "encoded": "encoded-track",
        "info": {
            "identifier": "/music/song.mp3",
            "isSeekable": True,
            "author": "Unknown",
            "length": 123,
            "isStream": False,
            "position": 0,
            "title": "song",
            "uri": None,
            "sourceName": "local",
        },
        "pluginInfo": {},
        "userData": {},
    }
    fake_mafic = SimpleNamespace(
        Track=SimpleNamespace(from_data_with_info=lambda data: ("track", data))
    )

    normalized = normalize_lavalink_track_load(
        {"loadType": "track", "data": track_data},
        mafic_module=fake_mafic,
    )

    assert normalized == ("track", track_data)


@pytest.mark.parametrize(
    "payload",
    [
        {"loadType": "empty", "data": None},
        {"loadType": "NO_MATCHES", "data": None},
        {"loadType": "error", "data": {"message": "failed"}},
        {"loadType": "playlist", "data": {"tracks": []}},
        {"loadType": "search", "data": []},
        {"loadType": "track", "data": []},
        [],
    ],
)
def test_normalize_lavalink_track_load_rejects_unsupported_or_empty_responses(
    payload: object,
) -> None:
    fake_mafic = SimpleNamespace(Track=SimpleNamespace(from_data_with_info=lambda data: data))

    with pytest.raises(LocalTrackLoadError):
        normalize_lavalink_track_load(payload, mafic_module=fake_mafic)
