from __future__ import annotations

from weasel_bot_v2.models import Playlist
from weasel_bot_v2.repositories import PlaylistRepository


class PlaylistService:
    def __init__(self, repository: PlaylistRepository) -> None:
        self.repository = repository

    def create_playlist(
        self,
        *,
        owner_user_id: int,
        name: str,
        guild_id: int | None = None,
        description: str | None = None,
    ) -> Playlist:
        return self.repository.create(
            Playlist(
                guild_id=guild_id,
                owner_user_id=owner_user_id,
                name=name,
                description=description,
            )
        )
