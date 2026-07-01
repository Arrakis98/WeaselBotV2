from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from weasel_bot_v2.models import Track
from weasel_bot_v2.repositories import QuarantineRepository, TrackRepository

AUDIO_EXTENSIONS = frozenset({".mp3", ".flac", ".wav", ".ogg", ".m4a", ".opus"})
PLAY_ALL_AUDIO_EXTENSIONS = frozenset({".mp3", ".opus"})


@dataclass(frozen=True)
class LibraryScanResult:
    found: int
    upserted: int
    marked_unavailable: int
    skipped: int


class LocalLibraryService:
    """Indexes and searches local audio files by path relative to the music root."""

    def __init__(
        self,
        music_root: Path,
        tracks: TrackRepository,
        quarantine: QuarantineRepository | None = None,
    ) -> None:
        self.music_root = music_root
        self.tracks = tracks
        self.quarantine = quarantine

    def scan(self) -> LibraryScanResult:
        found = 0
        upserted = 0
        skipped = 0
        root = self.music_root.resolve()

        if not root.exists() or not root.is_dir():
            return LibraryScanResult(found=0, upserted=0, marked_unavailable=0, skipped=0)

        found_relative_paths: set[str] = set()
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue

            track = self.track_from_path(path)
            if track is None:
                skipped += 1
                continue

            found += 1
            if track.relative_path is None:
                skipped += 1
                continue
            found_relative_paths.add(track.relative_path)
            if self._has_active_quarantine(track.relative_path):
                track = replace(track, is_available=False)
            self.tracks.upsert_local(track)
            upserted += 1

        marked_unavailable = self._mark_missing_available_tracks_unavailable(found_relative_paths)
        return LibraryScanResult(
            found=found,
            upserted=upserted,
            marked_unavailable=marked_unavailable,
            skipped=skipped,
        )

    def track_from_path(self, path: Path) -> Track | None:
        root = self.music_root.resolve()
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            return None

        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            return None

        relative_path = _to_stored_relative_path(relative)
        if relative_path is None:
            return None

        stat = resolved.stat()
        category_guess, artist_guess = infer_path_metadata(relative_path)
        file_name = PurePosixPath(relative_path).name
        display_title = PurePosixPath(relative_path).stem
        indexed_at = datetime.now(UTC).isoformat()

        return Track(
            source="local",
            source_id=relative_path,
            relative_path=relative_path,
            file_name=file_name,
            display_title=display_title,
            category_guess=category_guess,
            artist_guess=artist_guess,
            extension=path.suffix.lower(),
            size_bytes=stat.st_size,
            modified_at=stat.st_mtime,
            indexed_at=indexed_at,
            title=display_title,
            artist=artist_guess,
        )

    def search(self, query: str, *, limit: int = 10) -> list[Track]:
        normalized_query = normalize_search_text(query)
        if not normalized_query:
            return []

        matches: list[tuple[int, str, int, Track]] = []
        for track in self.tracks.list_local(available_only=True):
            haystacks = _track_search_fields(track)
            best_score = _best_score(normalized_query, haystacks)
            if best_score is None:
                continue
            matches.append((best_score, track.relative_path or "", track.id or 0, track))

        matches.sort(key=lambda match: (match[0], match[1].casefold(), match[2]))
        return [track for _, _, _, track in matches[:limit]]

    def stats(self) -> int:
        return self.tracks.count_local()

    def list_play_all_eligible_tracks(self) -> list[Track]:
        return select_play_all_eligible_tracks(self.tracks.list_local(available_only=True))

    def playback_path(self, track: Track) -> Path:
        if not track.relative_path:
            raise ValueError("Track does not have a local relative path.")
        relative = safe_relative_path(track.relative_path)
        return self.music_root / Path(*relative.parts)

    def _mark_missing_available_tracks_unavailable(self, found_relative_paths: set[str]) -> int:
        marked_unavailable = 0
        for track in self.tracks.list_local(available_only=True):
            if track.relative_path in found_relative_paths:
                continue
            if track.id is None:
                continue
            self.tracks.set_available(track.id, False)
            marked_unavailable += 1
        return marked_unavailable

    def _has_active_quarantine(self, relative_path: str) -> bool:
        if self.quarantine is None:
            return False
        existing = self.tracks.get_local_by_relative_path(relative_path)
        if existing is None or existing.id is None:
            return False
        return self.quarantine.active_for_track(existing.id) is not None


def infer_path_metadata(relative_path: str) -> tuple[str | None, str | None]:
    parts = PurePosixPath(relative_path).parts
    if len(parts) == 2:
        return None, parts[0]
    if len(parts) >= 3:
        return parts[0], parts[1]
    return None, None


def safe_relative_path(relative_path: str) -> PurePosixPath:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Local track path must stay inside the music root.")
    return path


def normalize_search_text(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_accents.casefold().split())


def select_play_all_eligible_tracks(tracks: list[Track]) -> list[Track]:
    return [
        track for track in tracks if (track.extension or "").casefold() in PLAY_ALL_AUDIO_EXTENSIONS
    ]


def _to_stored_relative_path(relative: Path) -> str | None:
    posix_path = PurePosixPath(*relative.parts)
    try:
        safe_relative_path(posix_path.as_posix())
    except ValueError:
        return None
    return posix_path.as_posix()


def _track_search_fields(track: Track) -> list[str]:
    return [
        normalize_search_text(track.file_name),
        normalize_search_text(track.display_title),
        normalize_search_text(track.artist_guess),
        normalize_search_text(track.category_guess),
        normalize_search_text(track.relative_path),
    ]


def _best_score(query: str, fields: list[str]) -> int | None:
    best: int | None = None
    for index, field in enumerate(fields):
        if not field or query not in field:
            continue
        score = index * 100
        if field == query:
            score -= 50
        elif field.startswith(query):
            score -= 25
        if best is None or score < best:
            best = score
    return best
