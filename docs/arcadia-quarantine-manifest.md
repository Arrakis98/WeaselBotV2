# Arcadia Quarantine Manifest Integration

Weasel Bot V2 can preview and apply an approved quarantine report family produced by Arcadia Music Tools.

## Private runtime inputs

The reports are private runtime data. Never commit them to this public repository.

Provide exactly two files to the bot container:

- the approved `music_quarantine_manifest_*.json` report;
- the matching `music_project_validation_*.json` report.

The default container paths are:

```text
/library_admin/manifests/music_quarantine_manifest.json
/library_admin/manifests/music_project_validation.json
```

A deployment can either copy the approved timestamped files to those stable names or set:

```text
WEASEL_QUARANTINE_MANIFEST_PATH
WEASEL_PROJECT_VALIDATION_PATH
```

Mount the containing host directory read-only. For example:

```yaml
volumes:
  - /private/path/to/approved-reports:/library_admin/manifests:ro
```

The existing writable music and quarantine mounts remain unchanged. Lavalink must not receive the report mount or any writable library-management mount.

## Discord workflow

Administrators or the bot owner can run:

```text
/quarantine_manifest execute:false
```

Preview mode performs every report, database, path, reference, and SHA-256 check without moving files. The response includes the report digest, operation count, eligible count, already-quarantined count, reasons, and any blocked items.

Only after a clean preview should an administrator run:

```text
/quarantine_manifest execute:true
```

The command is all-or-nothing at preflight time: if one operation is stale, missing, currently playing, unindexed, unsafe, or has a changed SHA-256, no operation starts.

## Validation policy

The integration rejects a report family unless all of these conditions hold:

- supported manifest and validation schema versions;
- manifest kind `arcadia_quarantine_manifest`;
- reviewed dry-run manifest;
- canonical originality reference policy;
- validation status `pass`;
- every validation check passes with no warnings or failures;
- operation and reason counts agree across both reports;
- verification paths exactly match manifest paths;
- every duplicate is verified as safe and keeps an active reference;
- duplicate confidence meets the manifest threshold;
- every source path is relative and confined to the configured library root;
- every source SHA-256 still matches immediately before its move.

Duplicate reference files are checked again against the live index and filesystem. A reference that is unavailable, missing, already quarantined, or selected by the same manifest blocks the operation.

## Reversibility

Every successful move uses the existing quarantine journal and remains visible through `/quarantine_list`. It can be restored with `/restore_quarantined`.

The quarantine service rolls a file back to its original location if the database record cannot be written after the move. Applied records include the manifest digest prefix and reason, which keeps repeated executions idempotent and auditable.

Permanent deletion is deliberately outside this workflow.

## Unified quarantine root

The bot owns `/library_admin/quarantine` and separates new files into
`superdislike/` and `mediatool/`. Both use the same SQLite audit journal and
restoration commands.

After changing an old deployment from the `super_disliked` mount to the whole
quarantine root, run `/quarantine_layout execute:false` and then
`/quarantine_layout execute:true`. This migrates active legacy files and their
stored SQLite paths safely.

`/purge_quarantine execute:false|true` covers both SuperDislike and approved
MediaTool candidates. Purge always means reversible quarantine, never permanent
deletion.
