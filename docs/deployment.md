# Deployment Notes

These notes are early guidance only. The bot is not implemented yet.

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
- SQLite database stored in a local runtime data directory.
- Local music library mounted read-only.

Do not expose Lavalink publicly by default.

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
