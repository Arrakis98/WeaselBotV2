# Organization Index Migration

Weasel Bot uses a local track's relative path as both `tracks.source_id` and
`tracks.relative_path`. After Arcadia Music Tools reorganizes the library, keep
the bot and Docker services stopped. Do not run `/library_scan`: scanning first
would insert new rows and leave user data attached to obsolete track IDs.

## Preview

Run the module against the offline database and the exact Arcadia apply
artifacts:

```bash
python -m weasel_bot_v2.organization_index_migration \
  --database /path/to/weasel.db \
  --manifest /path/to/music_organization_apply.json \
  --journal /path/to/music_organization_apply_journal.json \
  --music-root /path/to/musiques
```

Preview opens SQLite read-only and does not create locks, journals, backups,
reports, directories, or temporary files. It reports document identity and
state, operation classifications, conflicts, blockers, dependent row counts,
and whether IDs and foreign keys can be preserved. Any blocker must be resolved
before execution.

## Execution

Hash the database only after the bot and every database writer are stopped:

```bash
sha256sum /path/to/weasel.db /path/to/music_organization_apply.json
```

Then execute with both exact lowercase 64-character digests:

```bash
python -m weasel_bot_v2.organization_index_migration \
  --database /path/to/weasel.db \
  --manifest /path/to/music_organization_apply.json \
  --journal /path/to/music_organization_apply_journal.json \
  --music-root /path/to/musiques \
  --execute \
  --confirm-manifest-sha256 FULL_64_CHARACTER_SHA256 \
  --confirm-database-sha256 FULL_64_CHARACTER_SHA256 \
  --report /path/outside/music-root/organization-remap-result.json
```

Execution fails closed on malformed or mismatched Arcadia documents, a
non-applied or recovery journal, unsafe paths or symlinks, changed or missing
audio, schema or foreign-key problems, unavailable or quarantined source rows,
destination conflicts, mixed state, SQLite sidecars, lock contention, or changed
database identity.

Before any row update, execution acquires an offline lock, rechecks the database
digest, and creates a byte-for-byte verified backup beside the database. It then
updates all existing rows by `tracks.id` in one exclusive transaction. A failure
rolls the complete transaction back. The result report is written separately
outside the music root. Neither preview nor execution moves, links, deletes,
rewrites, chmods, or chowns an audio file.

## Verification and restart

After execution:

1. Keep the bot stopped and rerun preview. Every operation must report as
   already remapped with zero blockers.
2. Review the result report and retain the verified backup.
3. Confirm the normal project checks and deployment paths are correct.
4. Only then restart the bot. A subsequent `/library_scan` should update the
   same IDs and create no duplicate tracks.

Exit codes are `0` for a clean preview, completed migration, or already-remapped
no-op; `1` for a safety/policy block; `2` for malformed input or ordinary I/O;
and `3` for a critical verification or recovery condition requiring manual
attention.
