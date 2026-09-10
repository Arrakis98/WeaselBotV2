# Agent Handoff - Weasel Bot V2

This is the first file future ChatGPT Work / Agent / Codex sessions should read
after `AGENTS.md`.

## Short version

Repository:

```text
Arrakis98/WeaselBotV2
```

Base branch:

```text
main
```

Current state:

```text
A mature local-music Discord bot foundation is documented.
One bounded interactive SuperDislike quarantine correction is active on
agent/fix-superdislike-quarantine.
```

Implementation agents must follow the exact scope and stop conditions in
`CODEX_TASK.md`. Do not extend this task into Arcadia Music Tools, administrative
purge layout, deployment, or production data.

## Orchestration model

The repository is the durable project memory.

Read:

```text
docs/agent-orchestration.md
docs/agent-task-template.md
docs/agent-delivery-protocol.md
```

In short:

```text
project owner defines goals and approvals
Work / project lead maintains the broad view and prepares one bounded task
Codex implements that task on one branch and opens one PR
GitHub branches, commits, PRs, and CI define delivered work
```

Do not give Codex an entire roadmap phase as one unbounded mission.

## Required startup checks

With a real checkout, run:

```bash
git status --short --branch
git log --oneline -5
git remote -v
git branch --show-current
```

If there is no real checkout, stop before coding unless a GitHub connector/API
can create branches, commits, and pull requests.

## Required reading

Read before editing:

```text
README.md
ROADMAP.md
PROJECT_VISION.md
SECURITY.md
AGENTS.md
AGENT_HANDOFF.md
PROJECT_STATE.md
CODEX_TASK.md
docs/agent-orchestration.md
docs/agent-task-template.md
docs/agent-delivery-protocol.md
docs/architecture.md
docs/decisions.md
docs/deployment.md
```

Then read the focused source, tests, migration, UI, or integration documents
named by the active task.

## Durable state responsibilities

```text
ROADMAP.md        future direction
PROJECT_STATE.md  verified state and known blockers
AGENT_HANDOFF.md  startup briefing
CODEX_TASK.md     exactly one active bounded task or explicit stop state
```

Do not mark work delivered from a local report. A remote branch, commit, PR, and
observable CI state are required. Prefer updating merged-state claims after the
PR is merged.

## Repository safety

This is a public repository. Never commit:

```text
Discord tokens
cookies or passwords
API keys or private keys
.env files
private compose or Lavalink configuration
real user data or runtime databases
private Arcadia paths, reports, manifests, or infrastructure details
copied runtime state from older private bot versions
```

Synthetic public-safe fixtures only.

## Cross-repository boundary

Arcadia Music Tools, Weasel Bot V2, and private infrastructure remain separate
repositories. A task in this repository must not silently modify another one.
Any integration mission must define the interface and delivery expected from
each repository and use separate branches and pull requests.

## Delivery protocol

A mission is complete only when:

```text
- a remote working branch exists
- commits are pushed
- a PR exists toward the declared base branch
- CI is running, queued, or complete
- the final report includes the PR URL and commit SHA
```

Do not push directly to `main`. Do not merge, deploy, restart production,
force-push, or change secrets without explicit owner approval.

## Stop immediately if

```text
- CODEX_TASK.md says no task is active
- a task precondition is false
- the repository is unexpectedly dirty
- baseline tests fail
- the task requires a secret or private runtime data
- the task requires production deployment or restart
- the task requires writes to the real music library or production database
- the task crosses repositories without explicit scope
- the work cannot be delivered as a branch and PR
```
