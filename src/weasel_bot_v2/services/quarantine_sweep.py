from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from weasel_bot_v2.services.arcadia_quarantine import (
    ArcadiaQuarantinePreview,
    ArcadiaQuarantineResult,
    ArcadiaQuarantineService,
)
from weasel_bot_v2.services.quarantine import (
    PurgePreview,
    QuarantineMoveResult,
    QuarantineService,
)


@dataclass(frozen=True)
class QuarantineSweepPreview:
    superdisliked: PurgePreview
    mediatool: ArcadiaQuarantinePreview

    @property
    def blocked(self) -> tuple[str, ...]:
        return tuple(self.superdisliked.cannot_move) + tuple(self.mediatool.blocked)

    @property
    def eligible(self) -> int:
        return len(self.superdisliked.eligible) + self.mediatool.eligible

    @property
    def already_quarantined(self) -> int:
        return self.superdisliked.already_quarantined + self.mediatool.already_quarantined

    @property
    def ok(self) -> bool:
        return not self.blocked


@dataclass(frozen=True)
class QuarantineSweepResult:
    superdisliked: QuarantineMoveResult
    mediatool: ArcadiaQuarantineResult
    blocked: tuple[str, ...] = ()

    @property
    def moved(self) -> int:
        return self.superdisliked.moved + self.mediatool.moved

    @property
    def already_quarantined(self) -> int:
        return self.superdisliked.already_quarantined + self.mediatool.already_quarantined

    @property
    def failed(self) -> int:
        return self.superdisliked.failed + self.mediatool.failed + len(self.blocked)

    @property
    def removed_from_queue(self) -> int:
        return self.superdisliked.removed_from_queue + self.mediatool.removed_from_queue

    @property
    def failures(self) -> tuple[str, ...]:
        return (
            tuple(self.blocked)
            + tuple(self.superdisliked.failures)
            + tuple(self.mediatool.failures)
        )

    @property
    def ok(self) -> bool:
        return self.failed == 0


class QuarantineSweepService:
    """Preview or apply every current quarantine source in one operation."""

    def __init__(
        self,
        bot: Any,
        *,
        manifest_path: Path,
        validation_path: Path,
    ) -> None:
        self.bot = bot
        self.superdisliked = QuarantineService(bot)
        self.mediatool = ArcadiaQuarantineService(
            bot,
            manifest_path=manifest_path,
            validation_path=validation_path,
        )

    def preview(
        self,
        *,
        guild_id: int,
        current_track_id: int | None = None,
    ) -> QuarantineSweepPreview:
        return QuarantineSweepPreview(
            superdisliked=self.superdisliked.preview_superdisliked(
                guild_id,
                current_track_id=current_track_id,
            ),
            mediatool=self.mediatool.preview(current_track_id=current_track_id),
        )

    def apply(
        self,
        *,
        guild_id: int,
        requested_by_user_id: int,
        current_track_id: int | None = None,
    ) -> QuarantineSweepResult:
        preview = self.preview(
            guild_id=guild_id,
            current_track_id=current_track_id,
        )
        if preview.blocked:
            return QuarantineSweepResult(
                superdisliked=QuarantineMoveResult(
                    already_quarantined=preview.superdisliked.already_quarantined
                ),
                mediatool=ArcadiaQuarantineResult(
                    digest=preview.mediatool.digest,
                    already_quarantined=preview.mediatool.already_quarantined,
                ),
                blocked=preview.blocked,
            )

        mediatool_result = self.mediatool.apply(
            guild_id=guild_id,
            requested_by_user_id=requested_by_user_id,
            current_track_id=current_track_id,
        )
        if not mediatool_result.ok:
            return QuarantineSweepResult(
                superdisliked=QuarantineMoveResult(
                    already_quarantined=preview.superdisliked.already_quarantined
                ),
                mediatool=mediatool_result,
            )

        superdisliked_result = self.superdisliked.purge_superdisliked(
            guild_id=guild_id,
            requested_by_user_id=requested_by_user_id,
        )
        return QuarantineSweepResult(
            superdisliked=superdisliked_result,
            mediatool=mediatool_result,
        )
