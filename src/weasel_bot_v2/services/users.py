from __future__ import annotations

from weasel_bot_v2.models import UserRecord
from weasel_bot_v2.repositories import UserRepository


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository

    def remember_user(self, user_id: int, display_name: str | None = None) -> UserRecord:
        return self.repository.upsert(UserRecord(user_id=user_id, display_name=display_name))
