from __future__ import annotations

import logging
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import discord

LOGGER = logging.getLogger(__name__)

APPLICATION_EMOJI_NAMES: tuple[str, ...] = (
    "wg_back",
    "wg_dislike",
    "wg_superdislike",
    "wg_like",
    "wg_superlike",
    "wg_more",
    "wg_loop_off",
    "wg_loop_on",
    "wg_play_pause",
    "wg_queue",
    "wg_shuffle",
    "wg_stop",
    "wg_skip",
    "wg_volume_up",
    "wg_volume_down",
)

APPLICATION_EMOJI_ASSETS: dict[str, str] = {
    "wg_back": "wg_back.png",
    "wg_dislike": "wg_dislike.png",
    "wg_superdislike": "wg_superdislike.png",
    "wg_like": "wg_like.png",
    "wg_superlike": "wg_superlike.png",
    "wg_more": "wg_more.png",
    "wg_loop_off": "wg_loop_off.png",
    "wg_loop_on": "wg_loop_on.png",
    "wg_play_pause": "wg_play_pause.png",
    "wg_queue": "wg_queue.png",
    "wg_shuffle": "wg_shuffle.png",
    "wg_stop": "wg_stop.png",
    "wg_skip": "wg_skip.png",
    "wg_volume_up": "wg_volume_up.png",
    "wg_volume_down": "wg_volume_down.png",
}

BUTTON_EMOJI_MAP: dict[str, tuple[str | None, str | None]] = {
    "previous": ("wg_back", "⏮️"),
    "pause_resume": ("wg_play_pause", "⏯️"),
    "next": ("wg_skip", "⏭️"),
    "stop": ("wg_stop", "⏹️"),
    "volume_down": ("wg_volume_down", "🔉"),
    "volume_up": ("wg_volume_up", "🔊"),
    "queue": ("wg_queue", "📜"),
    "more": ("wg_more", "⋯"),
    "like": ("wg_like", "❤️"),
    "superlike": ("wg_superlike", "💎"),
    "dislike": ("wg_dislike", "👎"),
    "superdislike": ("wg_superdislike", "💀"),
}

LOOP_BUTTON_EMOJIS: dict[bool, tuple[str, str]] = {
    True: ("wg_loop_on", "🔁"),
    False: ("wg_loop_off", "🔁"),
}

ADVANCED_ACTION_EMOJI_MAP: dict[str, tuple[str | None, str | None]] = {
    "queue_details": ("wg_queue", "📜"),
    "now_playing_details": (None, "ℹ️"),
    "shuffle_queue": ("wg_shuffle", "🔀"),
    "reset_volume": (None, "↩️"),
    "clear_queue": (None, "🧹"),
    "leave": (None, "👋"),
    "back_to_controls": (None, "↩️"),
}

MORE_ACTION_OPTION_EMOJI_MAP: dict[str, tuple[str | None, str | None]] = {
    "show_queue": ("wg_queue", "📜"),
    "track_info": (None, "ℹ️"),
    "same_artist_disabled": (None, "🎙️"),
    "same_category_disabled": (None, "🗂️"),
    "add_to_playlist_disabled": (None, "➕"),
    "similar_radio_disabled": (None, "📡"),
}


@dataclass(frozen=True)
class EmojiAssetCheck:
    stable_name: str
    path: Path
    valid: bool
    reason: str | None = None
    width: int | None = None
    height: int | None = None
    has_alpha: bool | None = None


@dataclass(frozen=True)
class EmojiAssetValidationResult:
    checks: tuple[EmojiAssetCheck, ...]

    @property
    def valid_count(self) -> int:
        return sum(1 for check in self.checks if check.valid)

    @property
    def invalid_count(self) -> int:
        return sum(1 for check in self.checks if not check.valid)

    @property
    def invalid_checks(self) -> tuple[EmojiAssetCheck, ...]:
        return tuple(check for check in self.checks if not check.valid)


@dataclass(frozen=True)
class EmojiSyncEntry:
    stable_name: str
    path: Path
    emoji_id: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class EmojiSyncResult:
    created: tuple[EmojiSyncEntry, ...]
    existing: tuple[EmojiSyncEntry, ...]
    skipped: tuple[EmojiSyncEntry, ...]
    invalid: tuple[EmojiAssetCheck, ...]
    failed: tuple[EmojiSyncEntry, ...]

    @property
    def created_count(self) -> int:
        return len(self.created)

    @property
    def existing_count(self) -> int:
        return len(self.existing)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def invalid_count(self) -> int:
        return len(self.invalid)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    @property
    def total_count(self) -> int:
        return (
            self.created_count
            + self.existing_count
            + self.skipped_count
            + self.invalid_count
            + self.failed_count
        )


async def sync_application_emojis(
    client: Any,
    *,
    asset_root: Path,
    dry_run: bool,
) -> EmojiSyncResult:
    validation = validate_application_emoji_assets(asset_root)
    checks_by_name = {check.stable_name: check for check in validation.checks}
    remote_emojis = await client.fetch_application_emojis()
    remote_by_name: dict[str, discord.PartialEmoji] = {}
    duplicates: set[str] = set()

    for emoji in remote_emojis:
        name = getattr(emoji, "name", None)
        if name not in APPLICATION_EMOJI_NAMES:
            continue
        if name in remote_by_name:
            duplicates.add(name)
            continue
        remote_by_name[name] = emoji._to_partial()

    created: list[EmojiSyncEntry] = []
    existing: list[EmojiSyncEntry] = []
    skipped: list[EmojiSyncEntry] = []
    failed: list[EmojiSyncEntry] = []

    for stable_name in APPLICATION_EMOJI_NAMES:
        check = checks_by_name[stable_name]
        if not check.valid:
            continue

        remote = remote_by_name.get(stable_name)
        if remote is not None:
            note = "duplicate remote emoji ignored" if stable_name in duplicates else None
            existing.append(
                EmojiSyncEntry(
                    stable_name=stable_name,
                    path=check.path,
                    emoji_id=remote.id,
                    note=note,
                )
            )
            continue

        if dry_run:
            skipped.append(
                EmojiSyncEntry(
                    stable_name=stable_name,
                    path=check.path,
                    note="dry-run",
                )
            )
            continue

        try:
            created_emoji = await client.create_application_emoji(
                name=stable_name,
                image=check.path.read_bytes(),
            )
        except Exception as exc:  # noqa: BLE001 - sync should continue per emoji.
            failed.append(
                EmojiSyncEntry(
                    stable_name=stable_name,
                    path=check.path,
                    note=exc.__class__.__name__,
                )
            )
            continue

        created.append(
            EmojiSyncEntry(
                stable_name=stable_name,
                path=check.path,
                emoji_id=created_emoji.id,
            )
        )

    invalid = validation.invalid_checks
    if duplicates:
        LOGGER.warning(
            "Application emoji registry contains duplicate remote names: %s",
            ", ".join(sorted(duplicates)),
        )
    return EmojiSyncResult(
        created=tuple(created),
        existing=tuple(existing),
        skipped=tuple(skipped),
        invalid=invalid,
        failed=tuple(failed),
    )


class ApplicationEmojiRegistry:
    def __init__(self, emojis: dict[str, discord.PartialEmoji] | None = None) -> None:
        self._emojis = emojis or {}

    @classmethod
    def empty(cls) -> ApplicationEmojiRegistry:
        return cls({})

    @classmethod
    async def load(cls, client: Any) -> ApplicationEmojiRegistry:
        if client.application_id is None:
            LOGGER.warning("Application emoji registry unavailable: missing application_id.")
            return cls.empty()
        try:
            emojis = await client.fetch_application_emojis()
        except Exception as exc:  # noqa: BLE001 - startup should continue with fallbacks.
            LOGGER.warning(
                "Application emoji registry load failed: %s",
                exc.__class__.__name__,
            )
            return cls.empty()

        mapping: dict[str, discord.PartialEmoji] = {}
        for emoji in emojis:
            name = getattr(emoji, "name", None)
            if name in APPLICATION_EMOJI_NAMES:
                mapping[name] = emoji._to_partial()
        missing = sorted(set(APPLICATION_EMOJI_NAMES) - set(mapping))
        if missing:
            LOGGER.warning("Application emoji registry missing names: %s", ", ".join(missing))
        return cls(mapping)

    def resolve(
        self,
        stable_name: str,
        fallback: discord.PartialEmoji | str | None = None,
    ) -> discord.PartialEmoji | str | None:
        return self._emojis.get(stable_name, fallback)

    def resolve_button(
        self,
        button_key: str,
        fallback: discord.PartialEmoji | str | None,
        *,
        loop_enabled: bool | None = None,
    ) -> discord.PartialEmoji | str | None:
        if button_key == "loop" and loop_enabled is not None:
            stable_name, loop_fallback = LOOP_BUTTON_EMOJIS[loop_enabled]
            return self.resolve(stable_name, loop_fallback)
        if button_key == "shuffle":
            return self.resolve("wg_shuffle", fallback)
        stable_name, mapped_fallback = BUTTON_EMOJI_MAP.get(button_key, (None, fallback))
        if stable_name is None:
            return mapped_fallback
        return self.resolve(stable_name, mapped_fallback)

    def resolve_advanced_action(
        self,
        action_key: str,
        fallback: discord.PartialEmoji | str | None,
    ) -> discord.PartialEmoji | str | None:
        stable_name, mapped_fallback = ADVANCED_ACTION_EMOJI_MAP.get(action_key, (None, fallback))
        if stable_name is None:
            return mapped_fallback
        return self.resolve(stable_name, mapped_fallback)

    def resolve_more_action_option(
        self,
        option_value: str,
        fallback: discord.PartialEmoji | str | None,
    ) -> discord.PartialEmoji | str | None:
        stable_name, mapped_fallback = MORE_ACTION_OPTION_EMOJI_MAP.get(
            option_value,
            (None, fallback),
        )
        if stable_name is None:
            return mapped_fallback
        return self.resolve(stable_name, mapped_fallback)


def validate_application_emoji_assets(root: Path) -> EmojiAssetValidationResult:
    checks = []
    seen_paths: set[Path] = set()
    for stable_name, filename in APPLICATION_EMOJI_ASSETS.items():
        path = root / filename
        seen_paths.add(path)
        checks.append(_validate_png_asset(stable_name, path))
    missing = sorted(path.name for path in root.glob("*.png") if path not in seen_paths)
    if missing:
        LOGGER.warning("Unexpected extra emoji assets present: %s", ", ".join(missing))
    return EmojiAssetValidationResult(checks=tuple(checks))


def _validate_png_asset(stable_name: str, path: Path) -> EmojiAssetCheck:
    if not path.exists():
        return EmojiAssetCheck(stable_name=stable_name, path=path, valid=False, reason="missing")
    data = path.read_bytes()
    if len(data) >= 256 * 1024:
        return EmojiAssetCheck(
            stable_name=stable_name,
            path=path,
            valid=False,
            reason="file is at or above the 256 KiB limit",
        )
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return EmojiAssetCheck(stable_name=stable_name, path=path, valid=False, reason="not png")

    try:
        width, height, has_alpha = _inspect_png_bytes(data)
    except Exception as exc:  # noqa: BLE001 - validation should report per-file failures.
        return EmojiAssetCheck(
            stable_name=stable_name,
            path=path,
            valid=False,
            reason=exc.__class__.__name__,
        )

    valid = width == 128 and height == 128 and has_alpha
    reason = None
    if width != 128 or height != 128:
        reason = "must be 128x128"
    elif not has_alpha:
        reason = "missing real alpha transparency"
    return EmojiAssetCheck(
        stable_name=stable_name,
        path=path,
        valid=valid,
        reason=reason,
        width=width,
        height=height,
        has_alpha=has_alpha,
    )


def _inspect_png_bytes(data: bytes) -> tuple[int, int, bool]:
    pos = 8
    width = height = None
    bit_depth = None
    color_type = None
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        pos += 4
        chunk_type = data[pos : pos + 4]
        pos += 4
        chunk = data[pos : pos + length]
        pos += length + 4  # skip crc
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack_from(">IIBB", chunk)
            # skip compression/filter/interlace bytes via remaining 3 bytes
        elif chunk_type == b"IDAT":
            idat.extend(chunk)
        elif chunk_type == b"IEND":
            break

    if width is None or height is None or bit_depth is None or color_type is None:
        raise ValueError("missing PNG header")
    if bit_depth != 8:
        raise ValueError("unsupported bit depth")

    has_alpha = False
    if color_type in {4, 6}:
        has_alpha = _scan_png_alpha(bytes(idat), width, height, color_type)
    return width, height, has_alpha


def _scan_png_alpha(idat: bytes, width: int, height: int, color_type: int) -> bool:
    raw = zlib.decompress(idat)
    channels = {4: 2, 6: 4}[color_type]
    bytes_per_pixel = channels
    row_bytes = width * bytes_per_pixel
    pos = 0
    previous = bytearray(row_bytes)
    for _ in range(height):
        filter_type = raw[pos]
        pos += 1
        scanline = bytearray(raw[pos : pos + row_bytes])
        pos += row_bytes
        recon = _unfilter_png_scanline(filter_type, scanline, previous, bytes_per_pixel)
        previous = recon
        alpha_index = 1 if color_type == 4 else 3
        for alpha in recon[alpha_index::bytes_per_pixel]:
            if alpha < 255:
                return True
    return False


def _unfilter_png_scanline(
    filter_type: int,
    current: bytearray,
    previous: bytearray,
    bytes_per_pixel: int,
) -> bytearray:
    if filter_type == 0:
        return current
    if filter_type == 1:
        for index in range(bytes_per_pixel, len(current)):
            current[index] = (current[index] + current[index - bytes_per_pixel]) & 0xFF
        return current
    if filter_type == 2:
        for index, value in enumerate(previous):
            current[index] = (current[index] + value) & 0xFF
        return current
    if filter_type == 3:
        for index in range(len(current)):
            left = current[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up = previous[index]
            current[index] = (current[index] + ((left + up) // 2)) & 0xFF
        return current
    if filter_type == 4:
        for index in range(len(current)):
            left = current[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up = previous[index]
            up_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            current[index] = (current[index] + _paeth_predictor(left, up, up_left)) & 0xFF
        return current
    raise ValueError("unsupported PNG filter")


def _paeth_predictor(left: int, up: int, up_left: int) -> int:
    p = left + up - up_left
    pa = abs(p - left)
    pb = abs(p - up)
    pc = abs(p - up_left)
    if pa <= pb and pa <= pc:
        return left
    if pb <= pc:
        return up
    return up_left
