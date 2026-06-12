# Deployment Notes

These notes describe the Phase 1 local Docker/Lavalink stack. Music playback is
not implemented yet.

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
- SQLite database stored in a local runtime data directory. The public example
  config defaults to `data/weasel.db`; generated database files must remain
  ignored and outside Git.
- Local music library mounted read-only.

Do not expose Lavalink publicly by default.

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
a Lavalink v4 container image and is attached only to the internal Docker network.
The bot can reach Discord through its egress network and Lavalink through the
internal network.

Expected commands after Discord sync completes:

- `/ping`
- `/audio_status`
- `/bot_status`

`/audio_status` only reports whether the Phase 1 Mafic/Lavalink connection appears
available. It does not play music.

`/bot_status` reports safe bot, database, Lavalink, and feature-flag status. It
must not expose tokens, passwords, private paths, or runtime data.

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
