# Architecture

Weasel Bot V2 is intended to run as a small self-hosted Docker stack with a Python 3.12 Discord bot container and a separate Lavalink container.

## Containers

### Discord Bot Container

The bot container will run the Python application using `discord.py` for Discord interactions. It owns Discord interaction handling, bot configuration, persistence access, playlist logic, user settings, personality behavior, and orchestration of audio playback through Lavalink.

### Lavalink Container

Lavalink runs as a separate Docker service. The bot connects to it through an internal Docker network using `LAVALINK_HOST`, `LAVALINK_PORT`, and `LAVALINK_PASSWORD`.

Lavalink should not be exposed publicly by default.

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

### Read-Only Music Mount

The local music library should be mounted read-only into the bot and Lavalink containers. The bot may index and play the library, but it must not modify original music files.

## Application Layers

### Discord Interactions Layer

Handles slash commands first, with buttons, select menus, embeds, and later modals. This layer should validate user permissions and provide clear Discord-native responses.

### Audio Service

Owns playback state, Lavalink connection handling, queue operations, and audio errors. The preferred initial Lavalink Python client is Mafic, wrapped behind project-owned audio interfaces so the rest of the bot is not coupled directly to client internals. This choice remains reversible until Phase 1 validates an actual Docker/Lavalink connection and minimal playback test.

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
