# Deployment Notes

These notes describe the local Docker/Lavalink stack and Phase 3 local music
playback requirements.

## Local Development

Local development should use example files as templates:

- `.env.example` to create a private `.env`
- `config.example.yaml` to create a private `config.yaml`
- `compose.example.yml` to create a private `compose.yml`

Real local files must stay ignored by Git.

The intended local stack is:

- Python Discord bot container.
- Lavalink v4 container.
- Internal Docker network.
- Egress Docker network for both bot and Lavalink outbound traffic.
- SQLite database stored in a local runtime data directory. The public example
  config defaults to `data/weasel.db`; generated database files must remain
  ignored and outside Git.
- Local music library mounted read-only at `/music` in both the bot and
  Lavalink containers.

Do not expose Lavalink publicly by default. The bot should reach Lavalink on the
internal Docker network, and `compose.example.yml` must not publish Lavalink port
`2333` to the host. Lavalink still needs outbound egress network access so it can
communicate with Discord voice infrastructure.

For local music playback, keep the bot and Lavalink mounts consistent. The
public compose example uses `./music:/music:ro` as a safe placeholder. If your
real host library lives elsewhere, put that host path only in a private ignored
compose file and still mount it as `/music:ro` in both services.

## Phase 1 Local Docker Stack

Create private local files from the public-safe examples:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
cp compose.example.yml compose.yml
```

Edit `.env` locally:

```bash
DISCORD_TOKEN=your-local-discord-bot-token
DISCORD_TEST_GUILD_ID=
LAVALINK_PASSWORD=choose-a-local-password
LAVALINK_HOST=lavalink
LAVALINK_PORT=2333
```

Do not commit `.env`, `config.yaml`, `compose.yml`, Lavalink local overrides, data
directories, logs, or databases.

Start the stack:

```bash
docker compose up --build
```

The bot service builds from the repository `Dockerfile`. The Lavalink service uses
a Lavalink v4 container image. Both bot and Lavalink attach to the internal
network for bot-to-Lavalink traffic and to the egress network for outbound
Discord voice connectivity.

Expected commands after Discord sync completes:

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

`/audio_status` only reports whether the Phase 1 Mafic/Lavalink connection appears
available. It does not play music.

`/bot_status` reports safe bot, database, Lavalink, and feature-flag status. It
must not expose tokens, passwords, private paths, or runtime data.

`/play_local` is one-track local playback for Phase 3. It requires the requester
to be in a voice channel, Lavalink to be connected, and Lavalink to be able to
read the same `/music` path as the bot.

For Lavalink v4, local playback uses a plain absolute file path visible inside
the Lavalink container, such as `/music/Artist/song.mp3`. Do not use `file:`,
`file:///`, `local:`, or a host path for `/play_local`.

The example config sets `lavalink.timeout_seconds` to `30` so Mafic's REST calls
have enough time for Lavalink to resolve local files on slower disks.

Phase 4 adds local queue navigation on top of the Phase 3.5 controls. Queue state
is in memory per guild and is lost when the bot restarts. Like/superlike,
dislike/superdislike, same-artist actions, persisted playlists, web playback, and
autoplay radio are planned for later phases.

`/play_all` uses the SQLite index created by `/library_scan`; it does not scan the
filesystem at command time. It currently queues indexed `.mp3` files only and
intentionally ignores other indexed extensions.

## Troubleshooting

If `/library_scan` and `/search_local` work, but `/play_local` joins voice and
then times out, check that the Lavalink service is attached to the egress network.
Local file loading can succeed through the internal bot-to-Lavalink network while
audio playback still fails if Lavalink cannot reach Discord voice infrastructure.

## Future Arcadia Deployment

Future Arcadia deployment documentation should describe concepts and requirements without committing private hostnames, private paths, SSH details, credentials, or infrastructure files.

Acceptable public documentation:

- required environment variables
- expected mounted directories
- backup expectations
- service health checks
- upgrade process
- rollback considerations

Not acceptable in this repository:

- real server names
- private IP addresses
- private compose overrides
- private SSH commands
- production secrets
- private infrastructure scripts

## Operational Notes

- Rotate the Discord token immediately if it is exposed.
- Keep database backups outside Git.
- Keep music libraries mounted read-only.
- Review diffs before publishing changes.
