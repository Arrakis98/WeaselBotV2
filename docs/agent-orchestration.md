# Work / Codex Orchestration

This document defines how long-running project direction and bounded coding work
are coordinated in Weasel Bot V2.

The repository, not a chat transcript, is the durable project memory.

## Roles

### Project owner

The project owner defines goals, priorities, acceptable trade-offs, and approval
boundaries. Only the owner may authorize merging, production deployment,
credential changes, or destructive operations.

### Work / project-lead agent

The project-lead agent keeps the broad view. It may:

- read the roadmap, architecture, decisions, state, issues, pull requests, and CI;
- turn one roadmap item into one bounded implementation task;
- maintain `PROJECT_STATE.md`, `AGENT_HANDOFF.md`, and `CODEX_TASK.md`;
- review a delivered diff against the task and the wider architecture;
- select the next small milestone after the current one is actually delivered.

It must not treat conversational memory as source of truth when repository state
is available.

### Codex / implementation agent

The implementation agent executes one bounded task at a time. It must:

- read `AGENTS.md`, `AGENT_HANDOFF.md`, `PROJECT_STATE.md`, and `CODEX_TASK.md`;
- stop when `CODEX_TASK.md` says no task is active;
- verify the base branch, repository state, prerequisites, and baseline tests;
- stay inside the stated scope and stop conditions;
- use one dedicated branch and one pull request;
- run the required validation;
- report the remote branch, commit SHA, PR, CI state, and limitations.

Codex must not infer or implement the rest of a roadmap phase merely because it
can see it.

### GitHub

GitHub is the execution record and delivery boundary:

- branches isolate work;
- commits show what changed;
- pull requests provide review;
- CI provides validation;
- merged history defines delivered state.

No remote branch + no PR + no observable CI means the work is not delivered.

## Durable project-memory files

Use each file for one purpose:

- `ROADMAP.md`: future direction and ordering;
- `PROJECT_STATE.md`: verified repository state, known blockers, and current focus;
- `AGENT_HANDOFF.md`: short startup briefing for a new agent session;
- `CODEX_TASK.md`: exactly one active bounded implementation mission, or an
  explicit no-active-task state;
- `AGENTS.md`: invariant repository, safety, and engineering rules;
- `docs/agent-delivery-protocol.md`: branch, PR, CI, and reporting requirements;
- pull requests and CI: live implementation evidence.

Do not mark an implementation delivered from a local report. Prefer updating
merged-state claims after its PR is merged.

## Control loop

1. The project-lead agent reads the required project-memory files and verifies
   current GitHub state.
2. It refreshes stale state or handoff claims only from observable evidence.
3. It writes one task with a single outcome, explicit scope, acceptance criteria,
   validation commands, delivery requirements, and stop conditions.
4. Codex verifies prerequisites. A mismatch is a stop condition, not an invitation
   to improvise.
5. Codex implements only that task on a dedicated branch and opens a PR.
6. The project-lead agent reviews the diff, CI, comments, safety boundaries, and
   architectural consistency.
7. The owner decides whether to request changes, merge, defer, or abandon the PR.
8. Only after delivery is verified does the project lead update project state and
   prepare the next task.

## Task-sizing rules

A Codex task should normally have:

- one repository;
- one primary outcome;
- one working branch;
- one pull request;
- explicit acceptance criteria;
- tests that demonstrate the result;
- no hidden dependency on a later task.

Split work when it combines unrelated subsystems, requires several independent
architecture decisions, spans repositories, or cannot be reviewed safely as one
PR.

A roadmap phase is context, not automatically a Codex task.

## Cross-repository work

Weasel Bot V2, Arcadia Music Tools, and private infrastructure remain separate
repositories and security boundaries.

A cross-repository feature must be split into separate tasks, branches, commits,
and PRs unless the owner explicitly approves a coordinated integration mission.
Each task must state the interface expected from the other repository. Public
repository work must never expose private Arcadia configuration or runtime data.

## SSH and local execution

An SSH-connected implementation environment does not weaken repository rules.
The development account should have access to checkouts, build tools, tests,
Docker development commands, and approved staging commands, but not unrestricted
production secrets or arbitrary root access.

The production bot service should run under its own system user. Development and
service identities must not be conflated merely for convenience.

## Approval boundaries

Explicit owner approval is required before:

- merging a pull request;
- deploying or restarting production;
- changing secrets, tokens, or credentials;
- changing production Docker configuration;
- writing to the real music library or production database;
- performing destructive or difficult-to-reverse operations;
- broadening a task into another repository or roadmap phase.

These checkpoints let agents work independently up to the point where an action
changes production state or becomes difficult to reverse.
