# Weasel Bot V2 - Roadmap

## Project direction

Weasel Bot V2 is a free, self-hosted Discord bot focused on music, interaction, personality, and autonomous party modes.

The project must start cleanly as a new public repository. It must not reuse secrets, private infrastructure notes, or unstable legacy structure from V1.

Core principles:

* Free and self-hostable.
* Public-repository safe.
* Docker-first.
* Lavalink-first for audio.
* Discord slash commands first.
* Rich Discord UI with buttons, select menus, embeds, and later modals.
* SQLite-first for persistent bot data.
* Local music library support.
* Existing JSON playlist/history compatibility through import or adapter layers.
* AI is optional and not part of the core build.
* The bot must work without any paid API.

---

## Phase 0 - Project foundation

Goal: define the project before coding.

Deliverables:

* `README.md`
* `AGENTS.md`
* `ROADMAP.md`
* `PROJECT_VISION.md`
* `SECURITY.md`
* `docs/architecture.md`
* `docs/decisions.md`
* `.gitignore`
* `.env.example`
* `config.example.yaml`
* `compose.example.yml`

Decisions to record:

* Project name.
* Public repository rules.
* Docker/Lavalink architecture.
* Python version.
* Discord library.
* Lavalink Python client choice.
* Data storage strategy.
* Music library mount strategy.
* Secrets strategy.
* Initial feature scope.

Exit criteria:

* Codex has clear operating rules.
* No secrets can accidentally enter Git.
* The project vision is written.
* The technical direction is stable enough to start the skeleton.

---

## Phase 1 - Minimal Docker/Lavalink stack

Goal: prove that the base infrastructure works before building features.

Deliverables:

* Dockerfile for the bot.
* Docker Compose example with:

  * bot service
  * Lavalink service
  * internal Docker network
  * persistent data volume
  * read-only music library mount
* Lavalink `application.yml` example.
* Local development instructions.
* Health-check or startup validation.

Features:

* Start Lavalink in Docker.
* Start the bot container.
* Bot can connect to Discord.
* Bot can connect to Lavalink.
* `/ping` works.
* `/audio_status` shows Lavalink connection status.

Exit criteria:

* `docker compose up` starts the stack.
* The Discord bot logs in successfully.
* The bot detects Lavalink.
* No music playback required yet.

---

## Phase 2 - Core bot architecture

Goal: build the internal skeleton cleanly.

Core modules:

* `bot`
* `config`
* `logging`
* `database`
* `discord_ui`
* `audio`
* `library`
* `playlists`
* `users`
* `personality`
* `chaos`

Deliverables:

* Python package under `src/`.
* Clean config loader.
* SQLite initialization.
* Migration system or simple schema bootstrap.
* Structured logging.
* Typed models.
* Tests for config, queue, and storage.
* Basic cogs:

  * admin
  * music
  * playlists
  * users
  * debug

Exit criteria:

* Tests pass.
* Bot starts locally.
* Slash commands sync in a test guild.
* SQLite database is created safely.
* No hard-coded private paths.

---

## Phase 3 - Local music MVP

Goal: play local music reliably through Lavalink.

Features:

* Index local music library.
* Search local tracks.
* Play local track.
* Queue local tracks.
* Skip, stop, pause, resume.
* Now-playing embed.
* Buttons:

  * pause/resume
  * skip
  * stop
  * like
  * dislike
  * show queue

Data:

* `tracks`
* `play_history`
* `ratings`
* `guild_settings`

Exit criteria:

* A user can join a voice channel and play a local MP3.
* Queue works per guild.
* Buttons work.
* History records plays.
* Likes/dislikes are stored.

---

## Phase 4 - Playlists and library management

Goal: make the bot useful for real listening sessions.

Features:

* Import existing JSON playlists.
* List playlists.
* Show playlist contents.
* Play playlist.
* Shuffle playlist.
* Create/edit/delete V2 playlists.
* Add/remove tracks.
* Playlist ownership and permissions.
* Favorite playlists.

Data:

* `playlists`
* `playlist_items`
* `playlist_permissions`

Exit criteria:

* Existing V1 playlist data can be imported or read.
* V2 playlists work from Discord.
* Playlist commands use buttons/select menus where useful.

---

## Phase 5 - Users, stats, and preferences

Goal: make the bot remember people.

Features:

* User profiles.
* User listening history.
* Favorite tracks.
* Disliked tracks.
* Personal stats.
* Server stats.
* Taste profile:

  * favorite artists
  * favorite folders/categories
  * skipped tracks
  * repeated tracks
* Optional privacy controls.

Exit criteria:

* `/profile` works.
* `/stats` works.
* Recommendations can use user data later.
* The bot can distinguish guild-wide and user-specific preferences.

---

## Phase 6 - Web playback

Goal: add internet playback without making the bot fragile.

Features:

* Search web track.
* Play web track.
* Queue web track.
* Save web track reference to playlist.
* Error handling for unavailable sources.
* Feature flag to disable web playback.

Rules:

* Web playback must be isolated behind a resolver layer.
* If web playback breaks, local playback must still work.
* No cookies or secrets may be committed.

Exit criteria:

* `/play_web` works.
* Web errors are clean.
* Local playback remains independent.

---

## Phase 7 - Radio and autoplay

Goal: make the bot able to continue a session automatically.

Features:

* Radio from current track.
* Radio from playlist.
* Radio from user taste.
* Radio from guild taste.
* Radio intensity:

  * calm
  * normal
  * energetic
  * chaotic
* Auto-fill queue when it becomes low.
* Stop conditions and admin controls.

Exit criteria:

* `/radio start` works.
* `/radio stop` works.
* The bot can keep playing without manual queueing.
* Users can see why a track was selected.

---

## Phase 8 - Personality engine

Goal: give the bot a recognizable identity without requiring AI.

Features:

* Scripted messages.
* Mood system.
* Contextual reactions.
* Track announcements.
* User teasing, but configurable and safe.
* Server-specific personality settings.
* Message packs.

Examples:

* Launching a shameful track.
* Reacting to repeated skips.
* Announcing chaos mode.
* Celebrating a liked track.
* Mocking overplayed songs.

Exit criteria:

* The bot feels alive.
* Personality can be disabled.
* Messages are not hard-coded inside audio logic.

---

## Phase 9 - Chaos Mode / Mad DJ Mode

Goal: create the signature feature.

Chaos Mode is an autonomous DJ session where the bot takes partial control of music selection and server interaction.

Features:

* Start a chaos session.
* Choose duration.
* Choose intensity.
* Choose source pool:

  * local library
  * playlists
  * favorites
  * web
  * mixed
* Rules engine:

  * avoid repeats
  * avoid disliked tracks
  * alternate energy
  * increase intensity over time
  * surprise drops
* Discord interactions:

  * vote next mood
  * vote skip
  * choose between 3 tracks
  * panic stop
* Announcements:

  * dramatic intros
  * fake DJ commentary
  * shame messages
  * session recap

Exit criteria:

* Chaos Mode can run a short session safely.
* Admin can stop it instantly.
* Queue remains consistent.
* The bot records what happened.

---

## Phase 10 - Deployment and production hardening

Goal: make the bot reliable on Arcadia.

Deliverables:

* Production Docker Compose file template.
* Backup notes.
* Logs strategy.
* Restart policy.
* Database backup procedure.
* Lavalink maintenance notes.
* Arcadia service documentation template.

Features:

* Clean shutdown.
* Reconnect to Lavalink.
* Reconnect to Discord.
* Persistent data volume.
* Health checks.
* No root requirement at runtime.

Exit criteria:

* Bot can run for long sessions.
* Restart does not corrupt data.
* Logs are readable.
* Deployment is documented.

---

## Phase 11 - Optional AI module

Goal: add AI features without making the bot depend on AI.

Possible features:

* Local Ollama integration.
* AI-generated announcements.
* AI-generated session recap.
* AI-assisted recommendations.
* AI personality variants.
* Natural-language commands.

Rules:

* AI must be optional.
* Bot must work when AI is disabled.
* No paid API required.
* No private Discord data should be sent to external APIs by default.

Exit criteria:

* AI can be enabled as a plugin.
* Core music features work without it.

---

## Phase 12 - Optional web dashboard

Goal: manage the bot outside Discord.

Possible features:

* View current queue.
* Manage playlists.
* View stats.
* Edit personality packs.
* Configure Chaos Mode presets.
* View logs.

Exit criteria:

* Dashboard is optional.
* Discord bot does not depend on it.

---

## Long-term vision

Weasel Bot V2 should become a complete self-hosted Discord music companion:

* reliable as a music bot,
* fun as a server mascot,
* interactive as a Discord app,
* autonomous as a chaotic DJ,
* extensible as a long-term personal project.

The project should grow in layers. Every phase must leave the bot working better than before.
