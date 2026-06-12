# Security

This repository is intended to be public. Treat every committed file as public information.

## Secrets

Never commit:

- Discord bot tokens.
- Lavalink passwords.
- Cookies.
- API keys.
- Passwords.
- Private SSH keys.
- Real `.env` files.
- Private infrastructure files.
- Runtime databases.
- Save files or private exports from older bot versions.

Use `.env.example` as a template and create a private local `.env` file for real values.

## If a Token Leaks

If a Discord token, Lavalink password, cookie, API key, or other secret is committed or exposed:

1. Revoke or rotate it immediately at the provider.
2. Replace the local secret with a new value.
3. Audit recent activity for misuse.
4. Remove the secret from Git history before publishing if the repository has not been shared yet.
5. Assume a secret is compromised once it has been committed.

Deleting a file in a later commit is not enough for a public repository because the secret remains in history.

## Local Configuration

Real local files must stay ignored by Git:

- `.env`
- `.env.*`
- `config.yaml`
- `compose.yml`
- `docker-compose.yml`
- `application.local.yml`
- runtime data directories
- SQLite databases
- logs

The example files are safe placeholders only.

## Docker Cautions

Docker Compose examples must not include real private paths, tokens, or passwords. For local use, prefer environment variables and local ignored configuration files.

Do not expose Lavalink publicly by default. The bot should talk to Lavalink through an internal Docker network.

Mount the local music library read-only so the bot and Lavalink cannot modify original media files.

## Public Repository Safety

Before committing, review `git status` and the diff. If a file contains machine-specific infrastructure, private hostnames, secrets, tokens, or personal data, do not commit it.
