# Agent Instructions

These instructions apply to all automated agents and coding assistants working
in this repository.

## Required reading

Always read these files before making changes:

- `README.md`
- `ROADMAP.md`
- `PROJECT_VISION.md`
- `SECURITY.md`
- `AGENTS.md`
- `AGENT_HANDOFF.md`
- `PROJECT_STATE.md`
- `CODEX_TASK.md`
- `docs/agent-orchestration.md`
- `docs/agent-task-template.md`
- `docs/agent-delivery-protocol.md`
- `docs/architecture.md`
- `docs/decisions.md`
- `docs/deployment.md`

Then read every focused source, test, migration, UI, or integration file named by
the active task.

## Task gate

- `CODEX_TASK.md` defines the only active implementation mission.
- If it says no task is active, stop before coding.
- Do not infer work from the roadmap, README, issues, or chat context.
- A roadmap phase is context, not automatically one Codex task.
- Keep one repository, one primary outcome, one branch, and one PR per task.
- Do not broaden a task into an adjacent phase or another repository.

## Durable project memory

The repository is the source of truth, not conversational memory.

Use:

- `ROADMAP.md` for future direction;
- `PROJECT_STATE.md` for verified repository state and blockers;
- `AGENT_HANDOFF.md` for the startup briefing;
- `CODEX_TASK.md` for one bounded active mission;
- pull requests and CI for live implementation evidence.

Do not mark work delivered from a local report. Delivery requires a remote
branch, pushed commits, a pull request, observable CI, a PR URL, and a commit
SHA. Prefer updating merged-state claims after the PR is merged.

## Safety rules

- Never commit secrets.
- Never add `.env`, tokens, cookies, passwords, API keys, private SSH keys, or
  private infrastructure files.
- Never copy secrets or private runtime data from older bot repositories.
- Never add `config.json`, save files, cookies, tokens, or private data from V1.
- Never add private Arcadia infrastructure files to this public repository.
- Never commit real user data, runtime databases, production logs, or private
  Arcadia reports and manifests.
- Never modify files outside this repository unless explicitly requested.
- Never perform destructive commands without explicit user approval and a
  rollback plan.
- Never write to the real music library or production database during normal
  development or tests.
- Production deployment, restart, credential changes, and private configuration
  changes require explicit owner approval.
- Use synthetic, public-safe fixtures only.

## Cross-repository rules

- Weasel Bot V2, Arcadia Music Tools, and private infrastructure are separate
  repositories and security boundaries.
- Do not modify another repository unless the owner explicitly starts a
  coordinated integration task.
- Cross-repository work must define the interface expected from each repository
  and use separate branches and pull requests.
- Never expose private Arcadia paths, credentials, runtime data, or deployment
  details in this public repository.

## Engineering rules

- Before coding, verify repository status, current branch, recent commits, and
  baseline tests relevant to the task.
- Follow the active task's scope, acceptance criteria, validation, and stop
  conditions.
- Keep changes small, reviewable, tested, and reversible.
- Prefer documented decisions over assumptions.
- Update `docs/decisions.md` when making an architecture decision.
- Keep the project free and self-hostable.
- AI features must remain optional.
- Do not introduce required paid services.
- Docker and Lavalink are core architecture choices.
- Preserve existing public behavior unless the active task explicitly changes
  it.

## Git and delivery rules

- Never work directly on `main`.
- Use the base and working branch declared in `CODEX_TASK.md`.
- Do not rewrite published history.
- Do not force-push, merge, close pull requests, delete branches, deploy, or
  restart production unless the owner explicitly asks.
- Open a draft PR by default.
- The final report must include the remote branch, commit SHA, PR URL, target
  branch, validation results, CI state, remaining limitations, and next small
  recommended task.

## Stop conditions

Stop before coding or broadening scope when:

- `CODEX_TASK.md` says no task is active;
- a task precondition is false;
- the repository is unexpectedly dirty;
- baseline tests fail;
- the task conflicts with `SECURITY.md` or these instructions;
- a secret, private runtime file, real user data, production path, or another
  repository is required;
- the task requires production deployment or restart without explicit approval;
- the work cannot be delivered as a remote branch and pull request.

Report the exact blocker instead of improvising around it.
