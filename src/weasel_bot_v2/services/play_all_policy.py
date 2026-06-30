from __future__ import annotations

from dataclasses import dataclass

from weasel_bot_v2.models import (
    PlayAllArtistExclusion,
    PlayAllPolicy,
    PlayAllTrackException,
    Track,
    UserRecord,
)
from weasel_bot_v2.repositories import (
    PlayAllPolicyRepository,
    TrackRepository,
    UserRepository,
)
from weasel_bot_v2.services.local_library import (
    PLAY_ALL_AUDIO_EXTENSIONS,
    LocalLibraryService,
    normalize_search_text,
)

UNKNOWN_ARTIST = "Divers"


@dataclass(frozen=True)
class ArtistExclusionResult:
    ok: bool
    message: str
    created: bool = False


@dataclass(frozen=True)
class TrackExceptionResult:
    ok: bool
    message: str
    created: bool = False


@dataclass(frozen=True)
class PlayAllPolicySummary:
    policy: PlayAllPolicy
    exclusions: tuple[PlayAllArtistExclusion, ...]
    exceptions: tuple[tuple[PlayAllTrackException, Track | None, str], ...]
    effective_exception_count: int


@dataclass(frozen=True)
class PlayAllEligiblePool:
    total_indexed_play_all: int
    eligible_tracks: tuple[Track, ...]
    excluded_artists: tuple[str, ...] = ()


@dataclass(frozen=True)
class InvocationArtistResolution:
    ok: bool
    excluded_artist_keys: frozenset[str] = frozenset()
    display_artists: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    ambiguous: tuple[str, ...] = ()
    message: str = ""


class PlayAllPolicyService:
    def __init__(
        self,
        *,
        policy: PlayAllPolicyRepository,
        tracks: TrackRepository,
        users: UserRepository,
        library: LocalLibraryService,
    ) -> None:
        self.policy = policy
        self.tracks = tracks
        self.users = users
        self.library = library

    def eligible_tracks_for_play_all(self, guild_id: int) -> list[Track]:
        tracks = self.library.list_play_all_eligible_tracks()
        return list(self.filter_tracks_for_play_all(guild_id, tracks).eligible_tracks)

    def filter_tracks_for_play_all(
        self,
        guild_id: int,
        tracks: list[Track],
        *,
        excluded_artist_keys: set[str] | frozenset[str] | None = None,
        use_exceptions: bool | None = None,
    ) -> PlayAllEligiblePool:
        if excluded_artist_keys is None:
            exclusions = {
                exclusion.normalized_artist
                for exclusion in self.policy.list_artist_exclusions(guild_id)
            }
            policy = self.policy.get_policy(guild_id)
            exceptions_enabled = not policy.strict_exclusions
        else:
            exclusions = set(excluded_artist_keys)
            exceptions_enabled = use_exceptions is not False
        if not exclusions:
            eligible = [
                track for track in tracks if track.is_available and _is_play_all_extension(track)
            ]
            return PlayAllEligiblePool(
                total_indexed_play_all=len(tracks),
                eligible_tracks=tuple(eligible),
            )

        exception_ids = set()
        if exceptions_enabled:
            exception_ids = {
                exception.track_id for exception in self.policy.list_track_exceptions(guild_id)
            }

        eligible: list[Track] = []
        for track in tracks:
            if not track.is_available or not _is_play_all_extension(track):
                continue
            normalized_artist = normalized_artist_for_track(track)
            if normalized_artist not in exclusions:
                eligible.append(track)
                continue
            if track.id is not None and track.id in exception_ids:
                eligible.append(track)
        return PlayAllEligiblePool(
            total_indexed_play_all=len(tracks),
            eligible_tracks=tuple(eligible),
            excluded_artists=tuple(sorted(exclusions)),
        )

    def resolve_invocation_exclusions(self, exclusions: str | None) -> InvocationArtistResolution:
        requested = _parse_exclusion_items(exclusions)
        if not requested:
            return InvocationArtistResolution(ok=True)

        groups = _artist_groups(self.library.list_play_all_eligible_tracks())
        normalized_seen: set[str] = set()
        keys: list[str] = []
        displays: list[str] = []
        unresolved: list[str] = []
        ambiguous: list[str] = []
        for requested_artist in requested:
            resolution = _resolve_artist_from_groups(requested_artist, groups)
            if resolution.ok:
                if resolution.normalized_artist not in normalized_seen:
                    normalized_seen.add(resolution.normalized_artist)
                    keys.append(resolution.normalized_artist)
                    displays.append(resolution.display_artist)
                continue
            if "ambiguous" in resolution.message.casefold():
                ambiguous.append(requested_artist)
            else:
                unresolved.append(requested_artist)

        if unresolved or ambiguous:
            parts = []
            if unresolved:
                parts.append(f"unknown: {', '.join(unresolved)}")
            if ambiguous:
                parts.append(f"ambiguous: {', '.join(ambiguous)}")
            return InvocationArtistResolution(
                ok=False,
                unresolved=tuple(unresolved),
                ambiguous=tuple(ambiguous),
                message="Could not resolve /play_all exclusions (" + "; ".join(parts) + ").",
            )
        return InvocationArtistResolution(
            ok=True,
            excluded_artist_keys=frozenset(keys),
            display_artists=tuple(displays),
        )

    def add_artist_exclusion(
        self,
        *,
        guild_id: int,
        user_id: int,
        display_name: str | None,
        artist_query: str,
    ) -> ArtistExclusionResult:
        resolution = self.resolve_artist(artist_query)
        if not resolution.ok:
            return ArtistExclusionResult(ok=False, message=resolution.message)
        self._ensure_user(user_id, display_name)
        created = self.policy.add_artist_exclusion(
            guild_id=guild_id,
            normalized_artist=resolution.normalized_artist,
            display_artist=resolution.display_artist,
            created_by_user_id=user_id,
        )
        exception_count = self._exception_count_for_artist(guild_id, resolution.normalized_artist)
        state = "Excluded" if created else "Already excluded"
        return ArtistExclusionResult(
            ok=True,
            created=created,
            message=(
                f"{state}: {resolution.display_artist}\n"
                f"Currently affected /play_all tracks: {resolution.available_track_count}\n"
                f"Stored exceptions for this artist: {exception_count}"
            ),
        )

    def remove_artist_exclusion(self, *, guild_id: int, artist_query: str) -> ArtistExclusionResult:
        resolution = self.resolve_artist(artist_query)
        if not resolution.ok:
            return ArtistExclusionResult(ok=False, message=resolution.message)
        removed = self.policy.remove_artist_exclusion(
            guild_id=guild_id,
            normalized_artist=resolution.normalized_artist,
        )
        state = "Removed exclusion" if removed else "Artist was not excluded"
        return ArtistExclusionResult(
            ok=True,
            created=False,
            message=f"{state}: {resolution.display_artist}\nStored exceptions were kept.",
        )

    def add_track_exception(
        self,
        *,
        guild_id: int,
        user_id: int,
        display_name: str | None,
        track_query: str,
    ) -> TrackExceptionResult:
        resolution = self.resolve_available_track(track_query)
        if not resolution.ok or resolution.track is None:
            return TrackExceptionResult(ok=False, message=resolution.message)
        track = resolution.track
        if track.id is None:
            return TrackExceptionResult(ok=False, message="That track is not indexed.")
        self._ensure_user(user_id, display_name)
        created = self.policy.add_track_exception(
            guild_id=guild_id,
            track_id=track.id,
            created_by_user_id=user_id,
        )
        strict = self.policy.get_policy(guild_id).strict_exclusions
        excluded = normalized_artist_for_track(track) in self._excluded_artists(guild_id)
        status = _exception_status_text(excluded=excluded, strict=strict, available=True)
        state = "Added exception" if created else "Exception already stored"
        return TrackExceptionResult(
            ok=True,
            created=created,
            message=f"{state}: {_track_label(track)}\n{status}",
        )

    def add_track_exception_by_track(
        self,
        *,
        guild_id: int,
        user_id: int,
        display_name: str | None,
        track: Track,
    ) -> TrackExceptionResult:
        if track.id is None:
            return TrackExceptionResult(ok=False, message="That track is not indexed.")
        if not track.is_available:
            return TrackExceptionResult(
                ok=False,
                message="Unavailable tracks cannot be added as /play_all exceptions.",
            )
        self._ensure_user(user_id, display_name)
        created = self.policy.add_track_exception(
            guild_id=guild_id,
            track_id=track.id,
            created_by_user_id=user_id,
        )
        state = "Added exception" if created else "Exception already stored"
        return TrackExceptionResult(
            ok=True,
            created=created,
            message=f"{state}: {_track_label(track)}",
        )

    def remove_track_exception(self, *, guild_id: int, track_query: str) -> TrackExceptionResult:
        resolution = self.resolve_stored_exception(guild_id, track_query)
        if not resolution.ok or resolution.track is None:
            return TrackExceptionResult(ok=False, message=resolution.message)
        track = resolution.track
        if track.id is None:
            return TrackExceptionResult(ok=False, message="That exception has no indexed track.")
        removed = self.policy.remove_track_exception(guild_id=guild_id, track_id=track.id)
        if not removed:
            return TrackExceptionResult(ok=False, message="No stored exception matched that track.")
        return TrackExceptionResult(ok=True, message=f"Removed exception: {_track_label(track)}")

    def remove_track_exception_by_track(
        self,
        *,
        guild_id: int,
        track: Track,
    ) -> TrackExceptionResult:
        if track.id is None:
            return TrackExceptionResult(ok=False, message="That track is not indexed.")
        removed = self.policy.remove_track_exception(guild_id=guild_id, track_id=track.id)
        state = "Removed exception" if removed else "No exception was stored"
        return TrackExceptionResult(
            ok=True,
            created=False,
            message=f"{state}: {_track_label(track)}",
        )

    def has_track_exception(self, *, guild_id: int, track: Track | None) -> bool:
        if track is None or track.id is None:
            return False
        return self.policy.has_track_exception(guild_id=guild_id, track_id=track.id)

    def toggle_current_track_exception(
        self,
        *,
        guild_id: int,
        user_id: int,
        display_name: str | None,
        track: Track | None,
    ) -> TrackExceptionResult:
        if track is None:
            return TrackExceptionResult(ok=False, message="No current track is available.")
        if track.id is None:
            return TrackExceptionResult(ok=False, message="The current track is not indexed.")
        if not track.is_available:
            return TrackExceptionResult(
                ok=False,
                message="Unavailable tracks cannot be managed as /play_all exceptions.",
            )
        if self.has_track_exception(guild_id=guild_id, track=track):
            return self.remove_track_exception_by_track(guild_id=guild_id, track=track)
        return self.add_track_exception_by_track(
            guild_id=guild_id,
            user_id=user_id,
            display_name=display_name,
            track=track,
        )

    def set_strict(
        self,
        *,
        guild_id: int,
        user_id: int,
        display_name: str | None,
        enabled: bool,
    ) -> PlayAllPolicy:
        self._ensure_user(user_id, display_name)
        return self.policy.set_strict(
            guild_id=guild_id,
            enabled=enabled,
            updated_by_user_id=user_id,
        )

    def summary(self, guild_id: int) -> PlayAllPolicySummary:
        policy = self.policy.get_policy(guild_id)
        exclusions = tuple(self.policy.list_artist_exclusions(guild_id))
        excluded_artists = {exclusion.normalized_artist for exclusion in exclusions}
        exception_rows: list[tuple[PlayAllTrackException, Track | None, str]] = []
        effective = 0
        for exception, track in self.policy.list_exception_tracks(guild_id):
            status = exception_status(
                track,
                excluded_artists=excluded_artists,
                strict=policy.strict_exclusions,
            )
            if status == "active":
                effective += 1
            exception_rows.append((exception, track, status))
        return PlayAllPolicySummary(
            policy=policy,
            exclusions=exclusions,
            exceptions=tuple(exception_rows),
            effective_exception_count=effective,
        )

    def resolve_artist(self, artist_query: str) -> _ArtistResolution:
        if _looks_like_path(artist_query):
            return _ArtistResolution(ok=False, message="Artist names must not be filesystem paths.")
        normalized_query = normalize_search_text(artist_query)
        if not normalized_query:
            return _ArtistResolution(ok=False, message="Provide an artist name.")

        return _resolve_artist_from_groups(
            artist_query,
            _artist_groups(self.library.list_play_all_eligible_tracks()),
        )

    def resolve_available_track(self, track_query: str) -> _TrackResolution:
        if _looks_like_path(track_query):
            return _TrackResolution(
                ok=False,
                message="Track searches must not be filesystem paths.",
            )
        matches = self.library.search(track_query, limit=5)
        return _resolve_track_from_matches(track_query, matches)

    def resolve_stored_exception(self, guild_id: int, track_query: str) -> _TrackResolution:
        if _looks_like_path(track_query):
            return _TrackResolution(
                ok=False,
                message="Track searches must not be filesystem paths.",
            )
        candidates = [
            track for _, track in self.policy.list_exception_tracks(guild_id) if track is not None
        ]
        return _resolve_track_from_matches(track_query, candidates)

    def _excluded_artists(self, guild_id: int) -> set[str]:
        return {
            exclusion.normalized_artist
            for exclusion in self.policy.list_artist_exclusions(guild_id)
        }

    def _exception_count_for_artist(self, guild_id: int, normalized_artist: str) -> int:
        count = 0
        for _, track in self.policy.list_exception_tracks(guild_id):
            if track is not None and normalized_artist_for_track(track) == normalized_artist:
                count += 1
        return count

    def _ensure_user(self, user_id: int, display_name: str | None) -> None:
        self.users.upsert(UserRecord(user_id=user_id, display_name=display_name))


@dataclass(frozen=True)
class _ArtistResolution:
    ok: bool
    message: str = ""
    normalized_artist: str = ""
    display_artist: str = ""
    available_track_count: int = 0


@dataclass(frozen=True)
class _TrackResolution:
    ok: bool
    message: str = ""
    track: Track | None = None


def normalized_artist_for_track(track: Track) -> str:
    return normalize_search_text(display_artist_for_track(track))


def display_artist_for_track(track: Track) -> str:
    return _clean(track.artist) or _clean(track.artist_guess) or UNKNOWN_ARTIST


def exception_status(
    track: Track | None,
    *,
    excluded_artists: set[str],
    strict: bool,
) -> str:
    if track is None or not track.is_available:
        return "unavailable"
    if strict:
        return "ignored by strict mode"
    if normalized_artist_for_track(track) not in excluded_artists:
        return "inactive; artist is not excluded"
    return "active"


def _artist_groups(tracks: list[Track]) -> dict[str, _ArtistResolution]:
    groups: dict[str, _ArtistResolution] = {}
    counts: dict[str, int] = {}
    displays: dict[str, str] = {}
    for track in tracks:
        normalized = normalized_artist_for_track(track)
        if not normalized:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
        displays.setdefault(normalized, display_artist_for_track(track))
    for normalized, count in counts.items():
        groups[normalized] = _ArtistResolution(
            ok=True,
            normalized_artist=normalized,
            display_artist=displays[normalized],
            available_track_count=count,
        )
    return groups


def _parse_exclusion_items(exclusions: str | None) -> tuple[str, ...]:
    if not exclusions:
        return ()
    items: list[str] = []
    seen: set[str] = set()
    for raw_item in exclusions.split(","):
        item = raw_item.strip()
        normalized = normalize_search_text(item)
        if not normalized or normalized in seen:
            continue
        if _looks_like_path(item):
            items.append(item)
            seen.add(normalized)
            continue
        items.append(item)
        seen.add(normalized)
    return tuple(items)


def _resolve_artist_from_groups(
    artist_query: str,
    groups: dict[str, _ArtistResolution],
) -> _ArtistResolution:
    if _looks_like_path(artist_query):
        return _ArtistResolution(ok=False, message="Artist names must not be filesystem paths.")
    normalized_query = normalize_search_text(artist_query)
    if not normalized_query:
        return _ArtistResolution(ok=False, message="Provide an artist name.")
    exact = [group for group in groups.values() if group.normalized_artist == normalized_query]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return _ambiguous_artist(exact)
    partial = [group for group in groups.values() if normalized_query in group.normalized_artist]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        return _ambiguous_artist(partial)
    return _ArtistResolution(ok=False, message="No indexed /play_all artist matched.")


def _resolve_track_from_matches(query: str, matches: list[Track]) -> _TrackResolution:
    normalized_query = normalize_search_text(query)
    if not normalized_query:
        return _TrackResolution(ok=False, message="Provide a track search.")
    exact = [track for track in matches if normalized_query in _exact_track_keys(track)]
    if len(exact) == 1:
        return _TrackResolution(ok=True, track=exact[0])
    if len(exact) > 1:
        return _ambiguous_track(exact)
    if len(matches) == 1:
        return _TrackResolution(ok=True, track=matches[0])
    if len(matches) > 1:
        return _ambiguous_track(matches)
    return _TrackResolution(ok=False, message="No indexed available track matched.")


def _exact_track_keys(track: Track) -> set[str]:
    return {
        normalize_search_text(track.display_title),
        normalize_search_text(track.title),
        normalize_search_text(_filename_stem(track.file_name)),
    }


def _is_play_all_extension(track: Track) -> bool:
    return (track.extension or "").casefold() in PLAY_ALL_AUDIO_EXTENSIONS


def _filename_stem(file_name: str | None) -> str | None:
    if not file_name:
        return None
    suffix = file_name.rsplit(".", maxsplit=1)
    if len(suffix) == 2:
        return suffix[0]
    return file_name


def _ambiguous_artist(matches: list[_ArtistResolution]) -> _ArtistResolution:
    sample = ", ".join(match.display_artist for match in matches[:5])
    return _ArtistResolution(
        ok=False,
        message=f"Artist search is ambiguous. Matches: {sample}",
    )


def _ambiguous_track(matches: list[Track]) -> _TrackResolution:
    sample = ", ".join(_track_label(track) for track in matches[:5])
    return _TrackResolution(
        ok=False,
        message=f"Track search is ambiguous. Matches: {sample}",
    )


def _exception_status_text(*, excluded: bool, strict: bool, available: bool) -> str:
    if not available:
        return "Status: unavailable."
    if strict:
        return "Status: stored, but ignored while strict mode is enabled."
    if not excluded:
        return "Status: stored, but its artist is not currently excluded."
    return "Status: active for /play_all."


def _track_label(track: Track) -> str:
    title = (
        _clean(track.display_title) or _clean(track.title) or _clean(track.file_name) or "Untitled"
    )
    return f"{display_artist_for_track(track)} — {title}"


def _looks_like_path(value: str) -> bool:
    return "/" in value or "\\" in value


def _clean(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
