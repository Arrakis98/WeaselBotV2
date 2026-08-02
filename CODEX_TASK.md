# Codex Task - Make interactive SuperDislike quarantine immediate

## Outcome

Every successful interactive SuperDislike skips the captured current local track
exactly once and immediately moves its file out of the playable library into the
root of the configured reversible quarantine.

## Context

The existing action saves the rating and skips, but file movement is guarded by
an opt-in setting that defaults to false. When enabled, it also preserves a
source bucket and library subdirectories instead of placing the file directly in
the quarantine root.

## Preconditions

- `main` is at `35c3ff91beba15dd651f1785235b3a1c5d6bbb57`.
- The existing reversible quarantine service, SQLite audit journal, and restore
  workflow are present.
- Baseline validation is healthy: 272 tests pass, Ruff passes, and Pyright passes
  when run with the repository's configured `.venv` path.

## Repository and branches

Base branch:

`main`

Working branch:

`agent/fix-superdislike-quarantine`

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
- `docs/agent-orchestration.md`
- `docs/agent-task-template.md`
- `docs/agent-delivery-protocol.md`
- `docs/architecture.md`
- `docs/decisions.md`
- `docs/deployment.md`
- `src/weasel_bot_v2/services/player_actions.py`
- `src/weasel_bot_v2/services/quarantine.py`
- `tests/test_rating_skip_actions.py`
- `tests/test_quarantine.py`

## In scope

- Remove the opt-in gate from interactive SuperDislike quarantine.
- Quarantine only after a successful shared skip.
- Move the captured file directly to the quarantine root with collision-safe
  naming.
- Keep SQLite audit, restoration, availability changes, and queue cleanup.
- Add focused tests and update public-safe documentation and examples.

## Out of scope

- Arcadia Music Tools behavior or files.
- MediaTool manifest quarantine layout.
- Administrative SuperDislike purge layout.
- Production deployment, restart, private configuration, real music files, or a
  production database.
- Permanent deletion.

## Acceptance criteria

- Slash-command and panel SuperDislike actions share the corrected behavior.
- The rating is saved and the captured track is skipped exactly once.
- After a successful skip, a nested source file is absent from the active music
  root and present as a file directly under the quarantine root.
- A filename collision never overwrites an existing quarantine file.
- The track is unavailable in SQLite, removed from future queues, audited, and
  restorable.
- A failed skip does not move the current file.
- Dislike, Like, SuperLike, administrative purge, and MediaTool behavior do not
  change.

## Validation

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
pyright
```

## Delivery

The task is complete only when:

- the remote working branch exists;
- commits are pushed;
- a draft PR is open toward `main`;
- CI is running, queued, complete, or its absence is reported explicitly;
- the final report includes the PR URL and commit SHA.

## Stop conditions

Stop before broadening the task when:

- a precondition is false;
- baseline or final validation reveals an unrelated repository failure;
- a secret, private runtime path, real audio file, production database, or
  another repository is required;
- the task would require deployment, restart, permanent deletion, merge, or
  force-push;
- the work cannot be delivered as a branch and PR.

## Final report

Include the repository, base and working branches, commit SHA, PR URL, files
changed, implemented behavior, safety boundaries, exact validation results, CI
state, remaining limitations, and next recommended small task.
