# Weasel Bot V2 - Project State

Last reviewed from repository documentation: 2026-08-02.

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

## Documented current capabilities

The current README documents a mature Phase 5 / Phase 6 foundation including:

- Docker and Lavalink deployment;
- SQLite persistence;
- local library indexing, search, and playback;
- per-guild playback queues and player controls;
- authoritative Now Playing panels and Components V2 fallback behavior;
- user ratings and per-track volume presets;
- Play All exclusions and exceptions;
- reversible SuperDislike and approved Arcadia quarantine workflows;
- identity-preserving library reorganization migration support.

These are documentation-derived claims. Verify the current implementation and
tests before using them as prerequisites for a new task.

## Roadmap direction

The roadmap continues through profiles and preferences, playlists, advanced
library management, effects, unified playback sources, recommendations, Chaos
Mode, production hardening, a web control center, and optional local AI.

A roadmap phase is context, not an active Codex mission.

## Active task

```text
Interactive SuperDislike quarantine correction is active on
agent/fix-superdislike-quarantine.
```

`CODEX_TASK.md` defines the bounded mission: remove the opt-in gate from
interactive SuperDislike quarantine, move the successfully skipped captured file
directly into the quarantine root with collision-safe naming, and preserve audit
and restoration behavior. Arcadia Music Tools, administrative purge layout, and
production operations are explicitly outside the task.

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
