# Codex Task - Favorites-first shuffle

## Outcome

`/play_all` and explicit future-queue shuffle favor the invoking user's Likes
and SuperLikes near the start without changing eligibility or queue contents.

## Context

Short sessions should reach personally appreciated tracks quickly while
remaining random. PR #8 is a separate open SuperDislike fix and must not be
merged, cherry-picked, or copied into this task.

## Preconditions

- `origin/main` remains at or descends from verified base `35c3ff9`.
- The checkout is clean before task setup.
- Baseline pytest, Ruff lint, and Pyright pass. The existing repository-wide
  Ruff format drift is recorded separately and is not part of this task.

## Repository and branches

Base branch: `main`

Working branch: `agent/favorites-first-shuffle`

Do not push directly to `main`.

## Required reading

- All files required by `AGENTS.md`
- `src/weasel_bot_v2/cogs/music.py`
- `src/weasel_bot_v2/repositories/ratings.py`
- `src/weasel_bot_v2/services/now_playing_panel.py`
- `src/weasel_bot_v2/services/control_center.py`
- `src/weasel_bot_v2/services/play_all_policy.py`
- focused tests for ratings, Play All, queues, panels, and the control center

## In scope

- A pure, testable favorites-first shuffle with injectable randomness.
- Batched lookup of the invoking user's guild-scoped ratings.
- Use for each newly generated `/play_all` batch.
- Use for explicit shuffle of the existing future queue from Components V2 and
  the personal control center.
- Focused tests and documentation.

## Out of scope

- Special Dislike ordering, collective recommendations, profiles, playlists,
  Activity, effects, schema changes, or new dependencies.
- Changes to rating semantics, quarantine, AMT, Arcadia Infra, production data,
  deployment, rebuild, or restart.
- PR #8 changes or merge.

## Acceptance criteria

- Eligible occurrences are divided into SuperLikes, Likes, and Other for the
  invoking user and guild.
- Favorite slots choose SuperLike with probability 2/3 and Like with 1/3 while
  both groups remain, with random initial and inter-favorite Other intervals.
- Inputs are not mutated and every occurrence is returned exactly once.
- `/play_all` preserves all existing eligibility/exclusion/exception rules and
  only reorders the newly selected batch.
- Explicit shuffle changes only the existing future queue and preserves current
  playback, volume, loop, and back history.
- Rating lookup is batched rather than queried once per track.
- Existing per-guild mutation locks remain in use.

## Validation

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check <modified Python files>
.venv/bin/pyright
```

## Delivery

Push the working branch and open a draft PR to `main`. Do not merge or deploy.

## Stop conditions

Stop if repository state diverges unexpectedly, tests expose an unrelated gate
failure that cannot be isolated, secrets or real data are required, or the
mission would need PR #8, production changes, or another repository.

## Final report

Include the machine and checkout, PR #8 state, synchronization performed, base,
remote branch, commit SHA, draft PR URL and target, exact validations, CI state,
limitations, and next small task.
