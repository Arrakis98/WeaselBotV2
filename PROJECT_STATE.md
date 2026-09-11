# Weasel Bot V2 - Project State

Last reviewed against the checkout and GitHub: 2026-09-11.

This file records durable project state for future ChatGPT Work, Codex, and
agent sessions. Verify claims against the actual branch, commits, pull requests,
and tests before changing code.

## Repository

```text
Arrakis98/WeaselBotV2
```

Default development base:

```text
main
```

Never work directly on `main`. Every implementation task needs a dedicated
working branch and pull request.

## Project purpose

Weasel Bot V2 is a free, self-hosted Discord music bot built around Python,
Discord slash commands, Docker, Lavalink, SQLite, a local music library, rich
Discord interactions, user preferences, and later optional local AI features.

The public repository must remain safe to publish. Private tokens,
configuration, infrastructure details, runtime state, and user data do not
belong here.

## Current merged capabilities

The merged project state includes:

- Docker and Lavalink deployment;
- SQLite persistence;
- local library indexing, search, and playback;
- per-guild playback queues and player controls;
- authoritative Now Playing panels and Components V2 fallback behavior;
- user ratings and per-track volume presets;
- Play All exclusions and exceptions;
- reversible SuperDislike and approved Arcadia quarantine workflows;
- identity-preserving library reorganization migration support;
- personalized rating-aware ordering for `/play_all` and explicit future-queue
  shuffle.

Verify the current implementation and tests before using these as prerequisites
for a new task.

## Roadmap direction

The roadmap continues through profiles and preferences, playlists, advanced
library management, effects, unified playback sources, recommendations, Chaos
Mode, production hardening, a web control center, and optional local AI.

A roadmap phase is context, not an active Codex mission.

## Current merged state

PR #8 (`agent/fix-superdislike-quarantine`), PR #9
(`agent/favorites-first-shuffle`), and PR #10 (`chore/close-favorites-mission`)
are merged into `main`.

The current development base for the active correction is:

```text
22f0cb1c22b9a47232b69eb857a696327a8ca9cb
```

The combined validation immediately after PR #9 reported:

```text
pytest: 287 passed, 1 known third-party warning
ruff check: passed
ruff format check: 8 modified Python files compliant
pyright: 0 errors, 0 warnings
git diff --check: passed
```

## Active task

```text
Replace the overly stacked favorites-first sequence with a weighted rating mix.
```

The active branch is `fix/weighted-rating-shuffle`. The ordering policy uses
three playlist zones: favorites have higher probability early, neutral/unrated
tracks remain prominent throughout, and Dislike/SuperDislike tracks are pushed
toward the end. Consecutive favorites are avoided while a neutral track remains.
No playback-history schema or separate never-heard category is part of this task.

See `CODEX_TASK.md` for the exact table, acceptance criteria, and boundaries.

## Safety boundaries

- Never commit secrets or private runtime configuration.
- Never expose private Arcadia infrastructure in this public repository.
- Never use real user data or production databases as fixtures.
- Do not write to the real music library during development or tests.
- Production deployment, restart, credential changes, and destructive actions
  require explicit owner approval.
- Cross-repository Arcadia integration must be an explicit coordinated task with
  separate branches and PRs.
- AI features must remain optional and must not become required for core music
  playback.

## Durable workflow

Use:

```text
ROADMAP.md        future direction
PROJECT_STATE.md  verified state and blockers
AGENT_HANDOFF.md  startup briefing
CODEX_TASK.md     exactly one active bounded task, or explicit stop state
AGENTS.md         invariant rules
docs/agent-orchestration.md
docs/agent-delivery-protocol.md
```

## Delivery rule

A task is not delivered unless:

1. a remote working branch exists;
2. commits are pushed;
3. a PR is open toward the declared base branch;
4. CI is running, queued, or complete;
5. the final report includes the PR URL and commit SHA.

Do not mark a feature delivered from a local report alone. Prefer updating
merged-state claims after the PR is merged.
