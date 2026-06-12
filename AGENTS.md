# Agent Instructions

These instructions apply to all automated agents and coding assistants working in this repository.

## Required Reading

Always read these files before making changes:

- `README.md`
- `ROADMAP.md`
- `PROJECT_VISION.md`
- `SECURITY.md`
- `docs/architecture.md`
- `docs/decisions.md`

## Safety Rules

- Never commit secrets.
- Never add `.env`, tokens, cookies, passwords, API keys, private SSH keys, or private infrastructure files.
- Never copy secrets or private runtime data from older bot repositories.
- Never add `config.json`, save files, `.env`, cookies, tokens, or private data from V1.
- Never add private Arcadia infrastructure files to this public repository.
- Never modify files outside this repository unless explicitly requested.
- Never perform destructive commands without explicit user approval.

## Engineering Rules

- Before coding a feature, propose a short plan.
- Keep changes small and testable.
- Prefer documented decisions over assumptions.
- Update `docs/decisions.md` when making an architecture decision.
- Keep the project free and self-hostable.
- AI features must remain optional.
- Do not introduce required paid services.
- Docker and Lavalink are core architecture choices.
