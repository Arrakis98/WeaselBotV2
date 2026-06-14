from __future__ import annotations

from types import SimpleNamespace

import pytest

from weasel_bot_v2.models import Track
from weasel_bot_v2.services.voice_status import VoiceChannelStatusService, format_voice_status


@pytest.mark.asyncio
async def test_voice_status_set_update_clear_and_deduplicate() -> None:
    channel = _FakeVoiceChannel()
    guild = SimpleNamespace(id=123, voice_client=SimpleNamespace(channel=channel))
    bot = SimpleNamespace()
    first = _track("First")
    second = _track("Second")

    service = VoiceChannelStatusService(bot)
    await service.set_for_track(guild, first)  # type: ignore[arg-type]
    await service.set_for_track(guild, first)  # type: ignore[arg-type]
    await service.set_for_track(guild, second)  # type: ignore[arg-type]
    await service.clear(guild)  # type: ignore[arg-type]

    assert channel.statuses == [
        "🎵 First — Artist",
        "🎵 Second — Artist",
        None,
    ]


@pytest.mark.asyncio
async def test_voice_status_failure_does_not_raise() -> None:
    channel = _FakeVoiceChannel(fail=True)
    guild = SimpleNamespace(id=123, voice_client=SimpleNamespace(channel=channel))

    await VoiceChannelStatusService(SimpleNamespace()).set_for_track(  # type: ignore[arg-type]
        guild,  # type: ignore[arg-type]
        _track("Song"),
    )

    assert channel.statuses == []


def test_voice_status_sanitizes_and_truncates() -> None:
    status = format_voice_status(_track("A\n" * 200))

    assert "\n" not in status
    assert len(status) <= 120


class _FakeVoiceChannel:
    def __init__(self, *, fail: bool = False) -> None:
        self.id = 10
        self.fail = fail
        self.statuses: list[str | None] = []

    async def edit(self, *, status: str | None = None) -> None:
        if self.fail:
            raise RuntimeError("nope")
        self.statuses.append(status)


def _track(title: str) -> Track:
    return Track(
        source="local",
        source_id=f"{title}.mp3",
        relative_path=f"Artist/{title}.mp3",
        file_name=f"{title}.mp3",
        display_title=title,
        artist_guess="Artist",
    )
