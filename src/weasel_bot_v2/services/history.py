from __future__ import annotations

from weasel_bot_v2.models import PlayHistoryEntry
from weasel_bot_v2.repositories import HistoryRepository


class HistoryService:
    def __init__(self, repository: HistoryRepository) -> None:
        self.repository = repository

    def record_play(self, entry: PlayHistoryEntry) -> PlayHistoryEntry:
        return self.repository.record_play(entry)
