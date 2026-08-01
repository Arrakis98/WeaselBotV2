# Codex Task - No Active Task

## Status

```text
STOP: no implementation task is currently selected.
```

Do not infer a task from `ROADMAP.md`, `README.md`, open issues, or conversational
context. Do not start coding, create a feature branch, alter dependencies, run
production commands, or broaden an older task.

## What may be done safely

An implementation agent may only:

- read the required project-memory and repository instruction files;
- inspect the current branch, status, recent commits, and available tests;
- report that no active implementation mission exists.

## How this file becomes active

The Work / project-lead agent must replace this stop state with one bounded task
using:

```text
docs/agent-task-template.md
```

The active task must define:

- one observable outcome;
- context and verified prerequisites;
- base and working branches;
- required reading;
- in-scope and out-of-scope work;
- acceptance criteria;
- validation commands;
- delivery requirements;
- stop conditions;
- final report requirements.

## Delivery rule

A later active task is not complete until a remote branch, pushed commits, a
pull request, observable CI, a PR URL, and a commit SHA exist.
