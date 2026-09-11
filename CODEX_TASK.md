# Codex Task - Weighted rating shuffle correction

## Outcome

Replace the stacked favorites-first ordering with a random weighted mix that keeps
Likes and SuperLikes visible near the start, keeps neutral/unrated tracks present
throughout, and pushes Dislikes toward the end without changing queue contents.

## Context

PR #9 introduced the shared personalized shuffle used by `/play_all` and explicit
future-queue shuffle. In live use, the result feels too mechanically front-loaded
with favorites. The integration is sound; this task changes only the ordering
policy and focused tests.

## Preconditions

- Base `main` is `22f0cb1c22b9a47232b69eb857a696327a8ca9cb` or a descendant.
- PR #8 and PR #9 behavior outside ordering remains intact.
- Ratings continue to be loaded in one guild/user-scoped batch.

## Repository and branches

Base branch: `main`

Working branch: `fix/weighted-rating-shuffle`

Do not push directly to `main`.

## Required reading

- All files required by `AGENTS.md`
- `src/weasel_bot_v2/services/favorites_shuffle.py`
- `tests/test_favorites_shuffle.py`
- focused `/play_all`, control-center, and Now Playing shuffle tests

## In scope

- Keep four effective shuffle groups: SuperLike, Like, neutral/unrated, and
  negative ratings.
- Treat both Dislike and SuperDislike as the negative group for ordering.
- Shuffle occurrences inside each group without replacement.
- Choose the next available group using these position-dependent weights:

| Playlist progress | SuperLike | Like | Neutral | Dislike |
| --- | ---: | ---: | ---: | ---: |
| 0-25% | 25% | 20% | 55% | 0% |
| 25-70% | 15% | 15% | 65% | 5% |
| 70-100% | 5% | 5% | 40% | 50% |

- Renormalize naturally across groups that still contain tracks.
- If every remaining available group has zero configured weight, choose among
  the remaining groups rather than dropping or duplicating an occurrence.
- After a Like or SuperLike, force one neutral track next when a neutral track is
  still available, preventing avoidable favorite stacking.
- Preserve every input occurrence exactly once and do not mutate the input.
- Keep deterministic behavior with an injected seeded RNG.

## Out of scope

- Playback-history tracking or a separate never-heard/new group.
- Schema changes, new dependencies, playlists, recommendations, or collective
  taste logic.
- Changes to eligibility, artist exclusions, exceptions, quarantine behavior,
  ratings semantics, volume, loop, history, or queue ownership.
- Deployment or production restart.

## Acceptance criteria

- The three weight zones match the table exactly.
- Dislikes cannot be selected in the first quarter while another positive-weight
  group remains available.
- Negative ratings are substantially concentrated toward the end when stock
  permits.
- Likes and SuperLikes remain favored early but are not mechanically stacked;
  consecutive favorites are avoided while neutral tracks remain.
- SuperDislike uses the same late-ordering bucket as Dislike.
- Same seed gives the same permutation; different seeds vary.
- Every occurrence is preserved exactly once and input sequences are unchanged.
- Guild/user rating isolation and batched lookup remain intact.

## Validation

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check <modified Python files>
.venv/bin/pyright
git diff --check
```

Use only synthetic test data and temporary databases.

## Delivery

Commit and push the bounded change and open a pull request toward `main`.
Do not merge, deploy, or restart without explicit owner approval.

## Stop conditions

Stop if the change requires schema work, production data, real audio files,
private infrastructure, destructive operations, or a broader queue/player
refactor.

## Final report

Include branch, pushed SHA, PR URL, files changed, implemented weight policy,
exact validation results available, CI state, and any validation that could not
be executed from the current environment.
