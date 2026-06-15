#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import discord

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from weasel_bot_v2.services.application_emojis import (  # noqa: E402
    APPLICATION_EMOJI_NAMES,
    EmojiSyncResult,
    sync_application_emojis,
)

LOGGER = logging.getLogger("weasel_bot_v2.sync_application_emojis")
DEFAULT_ASSET_ROOT = ROOT / "assets" / "emojis" / "weasel_galaxy" / "v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Weasel Galaxy application emojis.")
    parser.add_argument(
        "--asset-root",
        type=Path,
        default=DEFAULT_ASSET_ROOT,
        help="Path to the emoji PNG directory.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Inspect without mutating Discord.")
    mode.add_argument("--apply", action="store_true", help="Create missing application emojis.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    dry_run = not args.apply
    try:
        result = asyncio.run(_sync(args.asset_root, dry_run=dry_run))
    except KeyboardInterrupt:
        return 130
    except SystemExit as exc:
        raise exc
    except Exception as exc:  # noqa: BLE001 - utility should fail clearly.
        LOGGER.error("Emoji sync failed: %s", exc.__class__.__name__)
        return 1

    _print_result(result, dry_run=dry_run)
    if result.invalid_count or result.failed_count:
        return 1
    return 0


async def _sync(asset_root: Path, *, dry_run: bool) -> EmojiSyncResult:
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit(
            "DISCORD_TOKEN must be provided in the environment. "
            "This utility does not read .env files."
        )

    client = discord.Client(intents=discord.Intents.none())
    try:
        await client.login(token)
        return await sync_application_emojis(
            client,
            asset_root=asset_root,
            dry_run=dry_run,
        )
    finally:
        await client.close()


def _print_result(result: EmojiSyncResult, *, dry_run: bool) -> None:
    mode = "dry-run" if dry_run else "apply"
    print(f"Mode: {mode}")
    print(f"Expected application emojis: {len(APPLICATION_EMOJI_NAMES)}")
    print(
        "Counts: "
        f"created={result.created_count} "
        f"existing={result.existing_count} "
        f"skipped={result.skipped_count} "
        f"invalid={result.invalid_count} "
        f"failed={result.failed_count}"
    )
    for entry in result.created:
        print(f"created {entry.stable_name} id={entry.emoji_id}")
    for entry in result.existing:
        suffix = f" id={entry.emoji_id}" if entry.emoji_id is not None else ""
        note = f" ({entry.note})" if entry.note else ""
        print(f"existing {entry.stable_name}{suffix}{note}")
    for entry in result.skipped:
        note = f" ({entry.note})" if entry.note else ""
        print(f"skipped {entry.stable_name}{note}")
    for check in result.invalid:
        print(f"invalid {check.stable_name}: {check.reason}")
    for entry in result.failed:
        note = f" ({entry.note})" if entry.note else ""
        print(f"failed {entry.stable_name}{note}")


if __name__ == "__main__":
    raise SystemExit(main())
