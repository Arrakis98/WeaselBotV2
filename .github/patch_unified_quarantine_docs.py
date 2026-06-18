from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"Patch target not found in {path}: {old[:80]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: str, marker: str, content: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if marker in text:
        return
    file.write_text(text.rstrip() + "\n\n" + content.strip() + "\n", encoding="utf-8")


replace_once(
    "README.md",
    "## Repository Safety\n",
    """## Repository and package names

The usual self-hosted checkout directory is `~/weasel-bot-v2`. The Python
package and module name is `weasel_bot_v2`, so the container starts it with
`python -m weasel_bot_v2`. Both names are intentional.

## Repository Safety
""",
)
replace_once(
    "README.md",
    "- `/purge_superdisliked`\n",
    "- `/purge_superdisliked`\n- `/purge_quarantine`\n- `/quarantine_layout`\n",
)
replace_once(
    "README.md",
    """SuperDislike library moderation is available as a reversible MVP. It is disabled
for automatic rating actions by default. When enabled with
`WEASEL_AUTO_QUARANTINE_SUPERDISLIKE=true` or
`library_moderation.auto_quarantine_superdislike: true`, SuperDislike saves the
rating, skips through the existing playback action, then moves the captured
previous local file from the writable admin library mount to the configured
quarantine mount. Administrative `/purge_superdisliked execute:false` previews
eligible SuperDisliked local tracks without filesystem changes, and
`execute:true` moves them instead of deleting them. `/quarantine_list` and
`/restore_quarantined` provide the minimal reversible audit workflow. Discord
output uses container-relative paths only and never host paths.

`/quarantine_manifest execute:false` loads one approved Arcadia Music Tools
manifest and its matching successful validation report from a private read-only
runtime mount. It rejects stale paths, changed hashes, unavailable references,
currently playing tracks, inconsistent reports, and unsafe report families before
any move starts. `execute:true` rechecks each SHA-256 immediately before using the
same reversible quarantine journal. Repeated execution is idempotent, and every
moved file remains restorable through `/restore_quarantined`.
""",
    """The bot owns one writable quarantine root at `/library_admin/quarantine`.
SuperDislike records are stored below `superdislike/`; approved Arcadia Music
Tools records are stored below `mediatool/`. SQLite is the shared audit and
restore journal.

`/purge_superdisliked` handles SuperDislikes only and `/quarantine_manifest`
handles the approved MediaTool report only. `/purge_quarantine` previews or
applies both sources in one operation. Purge means a reversible move into
quarantine, never permanent deletion.

Upgrades from the legacy `super_disliked` mount use `/quarantine_layout` first in
preview mode and then with `execute:true`. `/quarantine_list` and
`/restore_quarantined` work across both source buckets.
""",
)
replace_once(
    "README.md",
    "/library_admin/quarantine/super_disliked",
    "/library_admin/quarantine",
)

for path in ("docs/deployment.md", "docs/architecture.md", "docs/decisions.md"):
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    text = text.replace(
        "/library_admin/quarantine/super_disliked",
        "/library_admin/quarantine",
    ).replace("./quarantine/super_disliked", "./quarantine")
    file.write_text(text, encoding="utf-8")

append_once(
    "docs/arcadia-quarantine-manifest.md",
    "## Unified quarantine root",
    """## Unified quarantine root

The bot owns `/library_admin/quarantine` and separates new files into
`superdislike/` and `mediatool/`. Both use the same SQLite audit journal and
restoration commands.

After changing an old deployment from the `super_disliked` mount to the whole
quarantine root, run `/quarantine_layout execute:false` and then
`/quarantine_layout execute:true`. This migrates active legacy files and their
stored SQLite paths safely.

`/purge_quarantine execute:false|true` covers both SuperDislike and approved
MediaTool candidates. Purge always means reversible quarantine, never permanent
deletion.""",
)
append_once(
    "docs/deployment.md",
    "## Unified quarantine deployment",
    """## Unified quarantine deployment

Mount the whole private host quarantine directory at
`/library_admin/quarantine:rw` for the bot only. New files are routed into
`superdislike/` or `mediatool/`.

When upgrading from the old inner `super_disliked` mount, expose its parent at
the new root, rebuild the bot, preview `/quarantine_layout`, and apply it only
when no item is blocked. Then preview `/purge_quarantine` before any execution.""",
)
append_once(
    "docs/decisions.md",
    "## Unified quarantine root with source buckets",
    """## Unified quarantine root with source buckets

- Use one writable root: `/library_admin/quarantine`.
- Route bot ratings to `superdislike/` and MediaTool decisions to `mediatool/`.
- Keep SQLite authoritative for audit and restoration.
- Migrate legacy active records explicitly with `/quarantine_layout`.
- Let `/purge_quarantine` process both current candidate sources.
- Never interpret purge as permanent deletion.""",
)

# Keep validation expectations aligned with the new source-specific layout.
replace_once(
    "tests/test_rating_skip_actions.py",
    '    assert (quarantine_root / "Artist/current.mp3").exists()\n',
    '    assert (quarantine_root / "superdislike/Artist/current.mp3").exists()\n',
)

# safe_relative_path() returns PurePosixPath, not a filesystem Path.
replace_once(
    "src/weasel_bot_v2/services/quarantine.py",
    "from pathlib import Path\n",
    "from pathlib import Path, PurePosixPath\n",
)
replace_once(
    "src/weasel_bot_v2/services/quarantine.py",
    "    def _quarantine_source(self, relative: Path) -> Path:\n",
    "    def _quarantine_source(self, relative: PurePosixPath) -> Path:\n",
)
replace_once(
    "src/weasel_bot_v2/services/quarantine_layout.py",
    "from pathlib import Path\n",
    "from pathlib import Path, PurePosixPath\n",
)
replace_once(
    "src/weasel_bot_v2/services/quarantine_layout.py",
    "    def _legacy_source_relative(self, stored_relative: Path) -> Path | None:\n",
    "    def _legacy_source_relative(\n"
    "        self,\n"
    "        stored_relative: PurePosixPath,\n"
    "    ) -> PurePosixPath | None:\n",
)
