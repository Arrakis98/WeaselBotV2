from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuildSettings:
    guild_id: int
    command_prefix: str | None = None
    locale: str | None = None
    dj_role_id: int | None = None


@dataclass(frozen=True)
class UserRecord:
    user_id: int
    display_name: str | None = None


@dataclass(frozen=True)
class Track:
    source: str
    source_id: str
    id: int | None = None
    relative_path: str | None = None
    file_name: str | None = None
    display_title: str | None = None
    category_guess: str | None = None
    artist_guess: str | None = None
    extension: str | None = None
    size_bytes: int | None = None
    modified_at: float | None = None
    indexed_at: str | None = None
    title: str | None = None
    artist: str | None = None
    duration_ms: int | None = None


@dataclass(frozen=True)
class PlayHistoryEntry:
    guild_id: int
    user_id: int | None = None
    track_id: int | None = None
    context: str | None = None
    id: int | None = None


@dataclass(frozen=True)
class Rating:
    guild_id: int
    user_id: int
    track_id: int
    rating: str


@dataclass(frozen=True)
class RatingCounts:
    like: int = 0
    superlike: int = 0
    dislike: int = 0
    superdislike: int = 0


@dataclass(frozen=True)
class Playlist:
    owner_user_id: int
    name: str
    id: int | None = None
    guild_id: int | None = None
    description: str | None = None


@dataclass(frozen=True)
class PlaylistItem:
    playlist_id: int
    position: int
    track_id: int
    added_by_user_id: int | None = None
