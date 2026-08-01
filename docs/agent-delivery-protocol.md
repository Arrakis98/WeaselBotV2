# Agent Delivery Protocol

This protocol defines what counts as delivered work for Weasel Bot V2. It
applies to ChatGPT Work, Codex, and any future coding assistant.

## Core rule

```text
No remote branch + no PR + no observable CI = not delivered.
```

A local report, unpushed diff, or claimed implementation is not project state
until it exists on GitHub in a reviewable form.

## Required delivery checklist

A code or documentation task is complete only when all of the following are
true:

1. A remote branch exists on GitHub.
2. Commits are pushed to that branch.
3. A pull request is open toward the task's declared base branch.
4. CI has run, is running, or has an observable queued state.
5. The final report includes the PR URL and commit SHA.

If an item is missing, report the work as incomplete.

## Startup requirements

Before editing, verify the real repository context:

```bash
git status --short --branch
git log --oneline -5
git remote -v
git branch --show-current
```

If the environment has no real checkout, the agent must have a GitHub connector
or API capable of creating branches, writing commits, and opening a PR. If
neither exists, stop before coding.

## Branch rules

- Never work directly on `main`.
- Use the base and working branch declared in `CODEX_TASK.md`.
- Do not rewrite published history.
- Do not force-push unless the owner explicitly approves the reason.
- Do not merge, close, or delete a branch unless the owner explicitly asks.

## Pull request requirements

The PR body must include:

- summary of changes;
- reason for the change;
- safety boundaries preserved;
- validation performed;
- CI state;
- commit SHA;
- remaining limitations;
- next recommended small task.

Use a draft PR by default unless the owner explicitly asks for a ready review.

## Stop conditions

Stop before coding or broadening scope when:

- no real checkout and no write-capable GitHub connector exists;
- a remote branch or PR cannot be created;
- the repository is unexpectedly dirty;
- baseline tests fail;
- a task requires secrets, private runtime data, or private infrastructure;
- a task requires production deployment or restart without explicit approval;
- a task requires writes to the real music library or production database;
- a task silently crosses into Arcadia Music Tools or another repository;
- a destructive operation lacks explicit approval and a rollback plan.

When stopped, report the exact blocker. Do not substitute a local-only completion
report.

## Public repository safety

Never commit:

- Discord tokens, cookies, passwords, API keys, or private keys;
- `.env`, private compose files, or local Lavalink credentials;
- real user data, runtime databases, or production logs;
- private Arcadia paths, manifests, reports, or infrastructure details;
- copied state from older private bot installations.

Examples and fixtures must be synthetic and safe for a public repository.
