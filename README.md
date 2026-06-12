# Weasel Bot V2

Weasel Bot V2 is a free, self-hosted Discord music bot foundation focused on reliable audio, slash commands, rich Discord interactions, local music libraries, playlists, user profiles, and a future optional Chaos / Mad DJ mode.

This repository is designed to be public-repository safe. It must not contain Discord tokens, cookies, passwords, API keys, private infrastructure details, private deployment files, real user data, or copied runtime state from older bot versions.

## Direction

- Python Discord bot.
- Discord slash commands first.
- Docker-first deployment model.
- Lavalink-first audio architecture.
- SQLite for persistent bot data.
- Local music library support through a read-only mount.
- JSON playlist and history import compatibility with the old bot.
- Rich Discord UI planned: buttons, select menus, embeds, and later modals.
- Optional AI / Ollama features later, never required for the core bot.
- No paid API requirement.

## Current Status

Phase 4 provides the Docker/Lavalink stack, core SQLite architecture, local
library indexing, local search, local `/play_local` playback, `/play_all` for
shuffled indexed MP3 queues, basic player controls, a Discord Now Playing
control panel, and an in-memory per-guild local playback queue.

## Selected Stack

- Python 3.12.
- `discord.py` for Discord interactions.
- Mafic for initial Lavalink client integration.
- `src/` package layout with `pyproject.toml`.
- `pytest`, `ruff`, and `pyright` for tests, linting/formatting, and type checking.

## Repository Safety

Use example files as templates:

- `.env.example`
- `config.example.yaml`
- `compose.example.yml`

Create local private files when needed, but do not commit them:

- `.env`
- `config.yaml`
- `compose.yml`
- `docker-compose.yml`
- Lavalink local config files such as `application.local.yml`

## Documentation

- [Project Vision](PROJECT_VISION.md)
- [Roadmap](ROADMAP.md)
- [Security](SECURITY.md)
- [Architecture](docs/architecture.md)
- [Architecture Decisions](docs/decisions.md)
- [Deployment Notes](docs/deployment.md)
- [Chaos Mode](docs/chaos-mode.md)

## Phase 1 Local Development

Create private local files from the safe examples:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
cp compose.example.yml compose.yml
```

Edit `.env` locally and set `DISCORD_TOKEN` and `LAVALINK_PASSWORD`. Do not commit
`.env`, `config.yaml`, or `compose.yml`.

Start the local stack:

```bash
docker compose up --build
```

Expected Discord slash commands after the bot logs in:

- `/ping`
- `/audio_status`
- `/bot_status`
- `/library_scan`
- `/library_stats`
- `/search_local`
- `/play_local`
- `/play_all`
- `/pause`
- `/resume`
- `/stop`
- `/leave`
- `/now_playing`
- `/queue`
- `/skip`
- `/back`
- `/clear_queue`
- `/remove_from_queue`

Lavalink is only reachable on the internal Docker network by default. The example
compose file mounts `./music` as read-only example storage and does not expose
Lavalink ports publicly.
