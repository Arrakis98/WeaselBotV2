# Architecture

Weasel Bot V2 is intended to run as a small self-hosted Docker stack with a Python 3.12 Discord bot container and a separate Lavalink container.

## Containers

### Discord Bot Container

The bot container will run the Python application using `discord.py` for Discord interactions. It owns Discord interaction handling, bot configuration, persistence access, playlist logic, user settings, personality behavior, and orchestration of audio playback through Lavalink.

### Lavalink Container

Lavalink runs as a separate Docker service. The bot connects to it through an internal Docker network using `LAVALINK_HOST`, `LAVALINK_PORT`, and `LAVALINK_PASSWORD`.

Lavalink should not be exposed publicly by default. It should remain reachable by
the bot on the internal Docker network, while also having outbound egress network
access for Discord voice connections.

## Storage

### SQLite

SQLite is the first persistent storage target. It should store bot data such as:

- guild settings
- user preferences
- playlists
- playback history
- local library metadata
- legacy import records

Database files are local runtime data and must not be committed.

Phase 2 uses a small project-owned SQLite layer under `weasel_bot_v2.database`.
The database path comes from configuration and defaults to `data/weasel.db` for
local development. Tests must use temporary SQLite files only.

Initial schema bootstrap creates:

- `guild_settings`
- `users`
- `tracks`
- `play_history`
- `ratings`
- `playlists`
- `playlist_items`

### Read-Only Music Mount

The local music library should be mounted read-only into the bot and Lavalink containers. The bot may index and play the library, but it must not modify original music files.

Phase 3 stores local tracks by path relative to the configured music root. For
Docker runtime the root is normally `/music`, and both the bot and Lavalink
containers must mount the same host library at that same container path. The
database stores values such as `France/Renaud/Mistral gagnant.mp3`, not host
paths.

The local scanner supports mixed recursive layouts:

- files directly under `/music`
- `/music/<artist>/<file>`
- `/music/<category>/<artist>/<file>`
- deeper paths, preserving the full relative path

It does not require ID3 tags. Initial metadata guesses come from the relative
path only: depth 1 has no artist/category, depth 2 guesses the first folder as
artist, and depth 3 or greater guesses the first folder as category and the
second as artist.

## Application Layers

Phase 2 package boundaries:

- `core`: application wiring helpers.
- `database`: SQLite connection factory and schema bootstrap.
- `models`: typed records shared by services and repositories.
- `repositories`: persistence operations for guild settings, users, tracks,
  playlists, history, and ratings.
- `services`: workflow-facing wrappers over repositories.
- `cogs`: Discord slash command modules.
- `utils`: small shared utilities.

### Discord Interactions Layer

Handles slash commands first, with buttons, select menus, embeds, and later modals. This layer should validate user permissions and provide clear Discord-native responses.

### Audio Service

Owns playback state, Lavalink connection handling, queue operations, and audio errors. The preferred initial Lavalink Python client is Mafic, wrapped behind project-owned audio interfaces so the rest of the bot is not coupled directly to client internals. This choice remains reversible until Phase 1 validates an actual Docker/Lavalink connection and minimal playback test.

Phase 3 local playback is intentionally minimal: `/play_local` searches indexed
local tracks, joins the requester's voice channel, and asks Mafic/Lavalink to
play a single local path visible inside the Lavalink container. If local file
resolution fails at runtime, the command reports a clear error instead of
pretending playback succeeded.

Phase 3.5 adds basic player controls and a Discord Now Playing control panel for
the active local track. Phase 4 extends the in-memory per-guild player state with
an upcoming queue and recently played history for local tracks. `/play_local`
starts playback when idle and enqueues while active. Skip/back controls and
natural track-end auto-advance operate on this in-memory queue.

The Phase 4 queue is not persisted to SQLite yet. Ratings, recommendations, web
playback, autoplay radio, playlist workflows, and same-artist actions remain
planned for later phases.

`/play_all` feeds the in-memory queue from already indexed local library rows. It
filters to tracks whose indexed extension is `.mp3`, shuffles them, starts the
first track when idle, and appends the remaining tracks to the upcoming queue.
Non-MP3 indexed files are intentionally ignored by `/play_all` for now.

Phase 5.0 stores one active user rating per local track and guild. Users can set
Like, SuperLike, Dislike, or SuperDislike from slash commands or the Now Playing
panel; setting the same rating again confirms it and refreshes the row, while
setting a different rating replaces the previous one. Ratings are
persisted in SQLite for future personalization, but recommendation logic is not
implemented yet.

Phase 5.1 stores a per-guild default volume in `guild_settings`. Volume is
clamped from 0 to 200, defaults to 100 when unset, is applied when local playback
starts, and is saved whenever `/volume` or the Now Playing volume buttons change
it. This preference is independent from the in-memory queue and from user
ratings. Loop stability, long pause behavior, and occasional panel sync issues
remain intentionally deferred.

Phase 5.2 moves the Discord Now Playing panel behind an in-memory authoritative
panel registry. Each guild has at most one active tracked panel record containing
the guild ID, channel ID, message ID, current view reference, and a per-guild
`asyncio.Lock`. Slash commands and button callbacks use the same lock when they
mutate playback, queue, volume, loop, or rating state and then refresh the
panel. This prevents duplicate panel creation and reduces stale updates from
simultaneous interactions.

Panel rendering is centralized in `NowPlayingPanelService`. A refresh builds a
new snapshot from the current source of truth: active track metadata, paused
state, volume, loop state, queue length, next track preview, previous-track
availability, rating totals, Lavalink availability, and voice connection state.
The service edits the tracked Discord message whenever possible. If that message
was deleted, expired, or cannot be fetched, the service clears the old reference
and recreates the panel in the current interaction channel when a track is
active. Missing channel or permission failures are logged with safe guild,
channel, message, and error-class details and must not crash playback.

The panel view uses `timeout=None` and stable component `custom_id` values so the
buttons remain usable during long listening sessions while the bot process is
running. The project does not yet register persistent views on startup, so panel
button persistence across a full bot restart is not guaranteed. Loop behavior is
still marked experimental, and the known long-pause and loop instability issues
remain deferred outside Phase 5.2.

### Playlist Service

Manages saved playlists, playlist import, playlist editing, and compatibility with old JSON playlist data.

### User Service

Manages user profiles, preferences, listening history, and personalization inputs.

### Personality Service

Adds optional bot personality behavior without making AI a requirement.

### Chaos Service

Provides the future opt-in Chaos / Mad DJ mode. It must be disabled by default and controlled by permissions, cooldowns, and explicit guild settings.

### Optional AI Module

AI and Ollama integration may be explored later. The module must remain optional and must not be required for music playback, playlists, local library support, or normal bot operation.
