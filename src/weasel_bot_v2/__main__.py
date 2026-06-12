from __future__ import annotations

import asyncio

from weasel_bot_v2.bot import run_bot


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()

