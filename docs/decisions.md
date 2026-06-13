# Architecture Decisions

This file records architecture decisions for Weasel Bot V2. Add new decisions when implementation choices affect project structure, dependencies, deployment, persistence, or long-term maintenance.

## ADR-0001: Public Repository With No Secrets

- Status: Accepted
- Date: 2026-06-12

Weasel Bot V2 will be developed as a public-repository-safe project. Secrets, private runtime data, local infrastructure files, old V1 save files, cookies, tokens, and private Arcadia deployment details must not be committed.

## ADR-0002: Docker-First

- Status: Accepted
- Date: 2026-06-12

The project will be designed around Docker deployment from the start. Docker Compose examples may be provided, but local real compose files must stay ignored.

## ADR-0003: Lavalink-First

- Status: Accepted
- Date: 2026-06-12

Audio playback will be built around Lavalink as a separate service. The bot communicates with Lavalink through an internal Docker network.

## ADR-0004: SQLite-First

- Status: Accepted
- Date: 2026-06-12

SQLite will be the first persistent database. It keeps the bot self-hosted and simple without requiring a separate database service.

## ADR-0005: AI Is Optional

- Status: Accepted
- Date: 2026-06-12

AI and Ollama features may be added later, but they must remain optional. Core bot features must not require a paid API, external AI service, or local LLM.

## ADR-0006: Python Version

- Status: Accepted
- Date: 2026-06-12

The project will target Python 3.12 for implementation.

Python 3.12 is current enough for long-term dependency support while avoiding the extra churn of adopting the newest Python release immediately. The initial Dockerfile should use an official Python 3.12 image unless a dependency forces a documented change.

## ADR-0007: Discord Python Library

- Status: Accepted
- Date: 2026-06-12

The project will use `discord.py` as the Discord library.

`discord.py` fits the project direction because it is async-first, supports Discord application commands and interactions, is widely used, and is directly supported by the preferred Lavalink client choice. Slash commands should use the native `discord.app_commands` / interaction APIs rather than third-party slash-command adapters.

## ADR-0008: Lavalink Python Client

- Status: Accepted
- Date: 2026-06-12

The project will use Mafic as the preferred initial Python Lavalink client.

Lavalink remains the core audio backend. The audio layer must still wrap Mafic behind project-owned interfaces so queue management, playlist behavior, local-library handling, and Discord UI code do not depend directly on client internals.

This decision remains reversible until Phase 1 validates an actual Docker/Lavalink connection and minimal playback test.

### Client Comparison

Verified options from the Lavalink official client list and current package/project pages:

- Mafic: targets discord.py and related forks, is properly typehinted, has documentation, and covers node management, players, events, tracks, playlists, filters, errors, and utility APIs. It appears better suited for a maintainable new project than Wavelink. Risk: low to medium until Phase 1 validates the stack.
- lavalink.py: maintained releases and library-agnostic design. It is the strongest fallback if Mafic fails Phase 1 validation, though it may require more project-owned integration code than a discord.py-focused client. Risk: medium.
- Pomice: viable secondary alternative with discord.py focus and maintained releases, but weaker visible Python 3.12 packaging signal and GPL licensing are less attractive for this project. Risk: medium.
- Wavelink: rejected for new development because its own README states that Wavelink is no longer maintained, even though it still appears on Lavalink's client list and PyPI. Risk: high for new project adoption.
- SonoLink: promising modern Lavalink v4 wrapper with Python 3.12+ and multi-library support, but newer and less proven. Risk: medium.
- lavaplay.py: supports Lavalink v4 and Python 3.12, but documentation and API maturity appear weaker for a discord.py-first bot. Risk: medium to high.
- hikari-ongaku: relevant only if the project chooses Hikari instead of discord.py. Risk for this project: high due to Discord-library mismatch.

Decision: choose Mafic as the preferred initial Lavalink Python client.

Fallback order:

1. lavalink.py if Mafic fails Phase 1 validation.
2. Pomice if both Mafic and lavalink.py prove unsuitable.

Implementation notes:

- Verify local file playback behavior against the mounted read-only music library during the Lavalink stack phase.
- Keep Lavalink connection settings environment-driven.
- Avoid leaking Mafic-specific objects outside the audio module unless a later ADR explicitly accepts that coupling.

## ADR-0009: Python Packaging and Tooling

- Status: Accepted
- Date: 2026-06-12

The project will use a standard Python `src/` layout with project metadata and tooling in `pyproject.toml`.

Initial tooling:

- `pytest` for tests.
- `ruff` for linting and formatting.
- `pyright` for static type checking.
- Dockerfile added later during the minimal Docker/Lavalink stack phase.

The package should keep application code under `src/`, tests under `tests/`, and documentation under `docs/`. Tooling configuration should stay public-safe and must not reference private paths or infrastructure.

## ADR-0010: Local Tracks Stored By Relative Path

- Status: Accepted
- Date: 2026-06-12

Local music tracks are identified in SQLite by their path relative to the
configured music root.

The bot and Lavalink containers should both see the music library at the same
container path, normally `/music`, but the database must not store host paths
such as machine-specific mount locations. For example, a file visible in the
container as `/music/France/Renaud/Mistral gagnant.mp3` is stored as
`France/Renaud/Mistral gagnant.mp3`.

This keeps the repository public-safe, makes database backups portable across
hosts, and lets private host mount paths remain in ignored local deployment
configuration.

## ADR-0011: Authoritative In-Memory Now Playing Panel

- Status: Accepted
- Date: 2026-06-13

The Discord Now Playing panel is authoritative per guild during the lifetime of
the running bot process. The bot keeps an in-memory registry keyed by guild ID
with the channel ID, message ID, view reference, and per-guild `asyncio.Lock`.

Panel updates are centralized in `NowPlayingPanelService`. Commands and button
callbacks mutate playback, queue, volume, loop, or rating state and then ask the
service to rebuild the panel from current state. The service edits the tracked
message when possible and recreates it when the tracked message was deleted or
cannot be fetched.

This keeps Phase 5.2 small and self-hostable without adding a database table for
Discord message state. Restart persistence is intentionally not claimed because
persistent view registration and durable message references are not implemented
yet.
