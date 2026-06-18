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

Phase 5.0 provides the Docker/Lavalink stack, core SQLite architecture, local
library indexing, local search, local `/play_local` playback, `/play_all` for
shuffled indexed MP3 queues, basic player controls, a Discord Now Playing
control panel, an in-memory per-guild local playback queue, and persisted user
ratings for local tracks. Phase 5.1 adds persistent per-guild volume defaults,
and Phase 5.4 adds per-guild, per-track volume presets so quiet tracks can be
raised without forcing every later track to use the same volume. Phase 5.2 makes
the Now Playing panel authoritative per guild during the current bot process:
commands and buttons refresh one tracked panel instead of creating a new
permanent panel for every action. Phase 5.3B adds the Weasel Galaxy Components
V2 player panel with a legacy embed fallback. Phase 6.4 connects approved Arcadia
Music Tools quarantine reports to the existing reversible moderation service.

## Selected Stack

- Python 3.12.
- `discord.py` for Discord interactions.
- Mafic for initial Lavalink client integration.
- `src/` package layout with `pyproject.toml`.
- `pytest`, `ruff`, and `pyright` for tests, linting/formatting, and type checking.

## Repository and package names

The usual self-hosted checkout directory is `~/weasel-bot-v2`. The Python
package and module name is `weasel_bot_v2`, so the container starts it with
`python -m weasel_bot_v2`. Both names are intentional.

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
- Arcadia Music Tools reports and validation output

## Documentation

- [Project Vision](PROJECT_VISION.md)
- [Roadmap](ROADMAP.md)
- [Security](SECURITY.md)
- [Architecture](docs/architecture.md)
- [Architecture Decisions](docs/decisions.md)
- [UI Design](docs/ui-design.md)
- [User Flows](docs/user-flows.md)
- [Deployment Notes](docs/deployment.md)
- [Arcadia Quarantine Manifest](docs/arcadia-quarantine-manifest.md)
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
- `/like`
- `/superlike`
- `/dislike`
- `/superdislike`
- `/my_rating`
- `/my_ratings`
- `/volume`
- `/reset_track_volume`
- `/controls`
- `/purge_superdisliked`
- `/purge_quarantine`
- `/quarantine_layout`
- `/quarantine_list`
- `/restore_quarantined`
- `/quarantine_manifest`
- `/playall_exception`

The Now Playing panel also exposes active Like, SuperLike, Dislike, and
SuperDislike buttons. Ratings are stored for later personalization work, but they
do not drive recommendations yet. Queue state and ratings remain separate from
volume settings.

Dislike and SuperDislike save or replace the user's current-track rating before
invoking the shared skip action exactly once. Like and SuperLike save the rating
without skipping.

Volume is per track. A local track can have a guild-specific preset changed with
`/volume percent:<value>` while that track is playing, or with the Now Playing
volume buttons. Tracks without a preset always play at exactly 100%. Effective
volume is resolved as track preset first, otherwise 100. Use
`/reset_track_volume` to remove the current track preset and return it to 100%.
Values are clamped from 0 to 200; values above 100 are allowed but may amplify
already loud tracks enough to clip. No automatic ReplayGain or loudness
normalization is implemented yet. The old `/default_volume` command is
deprecated and no longer affects playback; the old schema column remains only
for backward-compatible database safety.

The active Now Playing panel is tracked in memory by guild. Playback commands,
queue-changing commands, volume changes, rating actions, button callbacks, and
natural track advance rebuild the panel from current player state, queue state,
effective volume, loop state, and rating counts. If the tracked message was
deleted or is no longer accessible, the bot attempts to recreate it in the
current interaction channel and update the stored reference.

Phase 6 adds a personal ephemeral `/controls` center, a structured personal More
Actions view, compact public playback activity acknowledgements with an
`Open Control Panel` launcher, and best-effort Discord voice-channel status
updates for the current track.

`/stop` and `/leave` are hard session resets: they stop playback, suppress the
manual-stop track-end auto-advance, clear the current track, queue, back history,
paused state, and loop state, then disconnect from voice. `/clear_queue` only
clears upcoming tracks and keeps the current track playing.

Panel controls use long-lived Discord views for the lifetime of the running bot,
but full restart persistence is not guaranteed because persistent view
registration is not implemented yet. Loop behavior remains experimental, and the
known long-pause and loop instability issues remain intentionally deferred.

The Phase 5.3B Weasel Galaxy panel uses the `#C026D3` magenta/violet accent,
English copy, compact Components V2 layout, emoji-only controls, `Divers` as the
unknown-artist fallback, and private ephemeral queue / more-actions flows. The
main player panel does not display raw local paths or Lavalink technical status.
No mascot GIF or spritesheet is integrated yet; optional artwork support remains
a documented extension point for a later live-tested phase. If Components V2
rendering fails, the bot falls back to the existing embed-based panel.

The bot owns one writable quarantine root at `/library_admin/quarantine`.
SuperDislike records are stored below `superdislike/`; approved Arcadia Music
Tools records are stored below `mediatool/`. SQLite is the shared audit and
restore journal.

`/purge_superdisliked` handles SuperDislikes only and `/quarantine_manifest`
handles the approved MediaTool report only. `/purge_quarantine` previews or
applies both sources in one operation. Purge means a reversible move into
quarantine, never permanent deletion.

Upgrades from the legacy `super_disliked` mount use `/quarantine_layout` first in
preview mode and then with `execute:true`. `/quarantine_list` and
`/restore_quarantined` work across both source buckets.

`/my_ratings` shows the invoking user's saved ratings for the current server
only, with an optional rating filter and page number. The output is ephemeral and
uses safe track titles plus artist/category context; it never shows local paths
or another user's ratings.

`/play_all` supports invocation-only artist exclusions with optional persistent
track exceptions. For example:
`/play_all exclusions:"GIMS, Michel Sardou" use_exceptions:true` excludes both
artists for that run only while allowing valid stored exception tracks back in.
Use `use_exceptions:false` to strictly exclude every track by those artists for
that one invocation. The exclusions string accepts multiple comma-separated
artists, resolves names case-insensitively and accent-insensitively against
currently indexed available artists, and fails without queue mutation when an
artist is unknown or ambiguous. Stored exceptions remain persistent per guild
and can be managed with the current-track More Actions toggle or
the main control grid's current-track exception button, or
`/playall_exception track:<search> enabled:true|false`. Quarantined,
unavailable, missing, invalid, and non-MP3 tracks remain ineligible regardless
of exception records. `/play_local`, `/search_local`, current playback, existing
queue contents, ratings, quarantine administration, restoration, and future
playlists are unchanged.

Lavalink is only reachable on the internal Docker network by default. The example
compose file mounts the active music library read-only at `/music` for both bot
and Lavalink. The bot also receives a least-privilege writable admin view at
`/library_admin/music` plus a writable quarantine destination at
`/library_admin/quarantine/super_disliked`; Lavalink does not receive those
writable mounts. Approved Arcadia reports are mounted read-only for the bot only.
