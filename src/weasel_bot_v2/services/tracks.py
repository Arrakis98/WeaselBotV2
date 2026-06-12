from __future__ import annotations

from weasel_bot_v2.models import Track
from weasel_bot_v2.repositories import TrackRepository


class TrackService:
    def __init__(self, repository: TrackRepository) -> None:
        self.repository = repository

    def remember_track(self, track: Track) -> Track:
        return self.repository.upsert(track)

    def remember_local_track(self, track: Track) -> Track:
        return self.repository.upsert_local(track)
