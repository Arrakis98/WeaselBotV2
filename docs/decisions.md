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

## ADR-0012: Weasel Galaxy Components V2 With Legacy Fallback

- Status: Accepted
- Date: 2026-06-14

The Now Playing panel will render with the Weasel Galaxy Components V2 interface
when the installed `discord.py` exposes the required Components V2 APIs. The
primary accent is `#C026D3`, the interface language is English, and public
player controls use emoji-only buttons with stable custom IDs.

The panel service keeps a legacy embed renderer as a fallback until the
Components V2 interface is validated live. Components V2 render failures are
logged with safe guild/channel/message/error-class context and retried with the
legacy embed renderer. Playback, queue state, ratings, and volume persistence
must not depend on panel rendering success.

The public panel does not show raw file paths or Lavalink technical status.
Unknown artists display as `Divers`. Queue and More Actions controls use private
ephemeral Discord interactions. Future custom emoji and optional mascot artwork
are extension points only; no GIF, spritesheet, playlist, recommendation, radio,
Chaos Mode, AI, or web playback behavior is added by this decision.

## ADR-0013: Guild-Specific Track Volume Presets

- Status: Accepted
- Date: 2026-06-14

Volume now has one playback-affecting persistent level: optional per-guild,
per-local-track presets stored in `track_volume_overrides`. The old
`guild_settings.default_volume` column remains for backward-compatible schema
safety, but playback ignores it.

The effective playback volume resolves as:

1. `track_volume_overrides` row for `guild_id + track_id`
2. 100

Track presets are not stored on `tracks` because the same local track may need a
different volume in different guilds. `/volume` and the Now Playing volume
buttons save the currently playing track preset. `/reset_track_volume` removes
the current track preset and reapplies 100. `/default_volume` is deprecated
because a configurable guild fallback conflicts with the per-track-only design.

The audio service still applies volume through the single existing
Mafic/Lavalink `set_volume` path. Values remain clamped from 0 to 200, and values
above 100 are allowed with a clipping warning. ReplayGain, normalization filters,
or automatic loudness analysis are intentionally not implemented by this
decision.

## ADR-0014: Personal Control Center And Compact Activity Messages

- Status: Accepted
- Date: 2026-06-14

The public Now Playing panel remains the authoritative public panel per guild,
while `/controls` and the `Open Control Panel` button render personal ephemeral
control centers. Personal controls call the same application services as slash
commands and public Components V2 buttons, then refresh the personal view and
the public panel when relevant.

More Actions is structured as an ephemeral advanced-actions view, not a second
public panel. Destructive session actions such as clearing the future queue or
leaving voice require confirmation. Unsupported future features are omitted
rather than exposed as fake working actions.

Successful playback actions may emit one compact public acknowledgement with an
`Open Control Panel` launcher. Automated track-end advancement should refresh
state without creating uncontrolled channel messages.

## ADR-0015: Reversible SuperDislike Quarantine

- Status: Accepted
- Date: 2026-06-14

SuperDislike library moderation must move files to a reversible quarantine; it
must never permanently delete music files. The active library stays read-only at
`/music` for both bot and Lavalink. The bot alone may receive configurable
writable moderation mounts at `/library_admin/music` and
`/library_admin/quarantine/super_disliked`.

The database stores quarantine audit rows in `track_quarantine` and marks moved
tracks unavailable through `tracks.is_available`. Local playback and `/play_all`
filter unavailable tracks out, while ratings and metadata remain intact for
audit and restoration.

Automatic SuperDislike quarantine is disabled by default. When enabled, the
sequence is: capture current indexed track, save SuperDislike, invoke the shared
skip action exactly once, then quarantine the captured previous track. If the
move fails, the rating and skip remain completed. Administrative purge,
inspection, and restoration commands use record IDs and indexed tracks only;
they never accept raw filesystem paths.

## ADR-0016: Invocation-Scoped `/play_all` Artist Exclusions

- Status: Accepted
- Date: 2026-06-15

`/play_all` artist exclusions are chosen directly on each command invocation
through an optional comma-separated `exclusions` string. They are not persisted
as a guild-wide policy and do not affect another user's later `/play_all`.

Artist names use the same case-insensitive and accent-insensitive normalization
as local-library search. Exclusions are resolved once against currently indexed
available artists. Unknown or ambiguous artists reject the command before
playback starts and before the queue is mutated. Commands never accept
filesystem paths for artist or exception management input.

Track exceptions remain persistent per guild in `play_all_track_exceptions` and
store stable indexed track IDs. The `use_exceptions` slash option is
invocation-only: when true, valid stored exceptions can re-allow tracks by the
artists named in the current `exclusions` option; when false, all tracks by
those artists remain excluded for that run. Unavailable, quarantined, missing,
invalid, and non-MP3 tracks remain ineligible even when an exception record
exists.

Exception management is exposed through the main control grid current-track
button, the personal More Actions current-track toggle, and
`/playall_exception track:<search> enabled:true|false`; all mutation paths are
administrator/owner restricted. The legacy `play_all_artist_exclusions` and
`play_all_policy` tables remain in SQLite for backward compatibility and
possible future presets, but their old Discord policy-management commands are no
longer registered.
