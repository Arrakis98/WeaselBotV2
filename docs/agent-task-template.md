# Agent Task Template

Copy this structure into `CODEX_TASK.md` when preparing a new implementation
mission. Keep exactly one active task in that file.

```markdown
# Codex Task - <short task name>

## Outcome

<One observable result.>

## Context

<Why the task exists and how it fits the current milestone.>

## Preconditions

- <Required PRs or commits are merged.>
- <Required files, services, or APIs exist.>
- <The base branch and baseline tests are healthy.>

## Repository and branches

Base branch:

`<base-branch>`

Working branch:

`<working-branch>`

Do not push directly to the base branch.

## Required reading

- `README.md`
- `ROADMAP.md`
- `PROJECT_VISION.md`
- `SECURITY.md`
- `AGENTS.md`
- `AGENT_HANDOFF.md`
- `PROJECT_STATE.md`
- `CODEX_TASK.md`
- `<focused implementation and documentation files>`

## In scope

- <Deliverable 1>
- <Deliverable 2>
- <Focused tests>
- <Focused documentation update>

## Out of scope

- <Adjacent feature>
- <Production deployment or restart>
- <Other repository>
- <Destructive or irreversible behavior>

## Acceptance criteria

- <Behavioral result that can be reviewed or tested>
- <Safety property>
- <API, command, UI, or persistence requirement when relevant>
- <No regression requirement>

## Validation

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
pyright
```

Add focused Docker or migration checks only when the task explicitly requires
them and they are safe in the current environment.

## Delivery

The task is complete only when:

- a remote working branch exists;
- commits are pushed;
- a PR is open toward the base branch;
- CI is running, queued, or complete;
- the final report includes the PR URL and commit SHA.

## Stop conditions

Stop before broadening the task when:

- a precondition is false;
- the repository is unexpectedly dirty;
- baseline tests fail;
- the requested behavior conflicts with `AGENTS.md` or `SECURITY.md`;
- a secret, production path, real user data, or another repository is required;
- the task cannot be delivered as a branch and PR.

## Final report

Include:

- repository and initial base branch;
- remote working branch;
- commit SHA;
- PR URL and target branch;
- files changed;
- behavior implemented;
- safety boundaries preserved;
- exact validation results;
- CI state;
- remaining limitations;
- next recommended small task.
```
