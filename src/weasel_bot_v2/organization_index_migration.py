"""Offline, identity-preserving remap of local tracks after Arcadia organization."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from weasel_bot_v2.services.local_library import infer_path_metadata

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OPERATION_ID_RE = re.compile(r"^operation-[0-9]{6}$")
SENSITIVE_DETAIL_RE = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|api[_-]?key\s*[=:]|password\s*[=:]|token\s*[=:])",
    re.IGNORECASE,
)
DEPENDENT_TABLES = (
    "ratings",
    "track_volume_overrides",
    "playlist_items",
    "play_history",
    "track_quarantine",
    "play_all_track_exceptions",
)
REQUIRED_TRACK_COLUMNS = {
    "id",
    "source",
    "source_id",
    "relative_path",
    "file_name",
    "display_title",
    "category_guess",
    "artist_guess",
    "extension",
    "size_bytes",
    "modified_at",
    "indexed_at",
    "title",
    "artist",
    "duration_ms",
    "is_available",
    "created_at",
}
FailureHook = Callable[[str, int | None], None]


class InputError(ValueError):
    """Malformed input or ordinary I/O/configuration error."""


class SafetyBlock(RuntimeError):
    """A fail-closed safety or policy precondition was not met."""


class CriticalError(RuntimeError):
    """Post-write verification or recovery requires manual attention."""


@dataclass(frozen=True)
class Operation:
    operation_id: str
    source: PurePosixPath
    destination: PurePosixPath
    sha256: str


@dataclass(frozen=True)
class ApprovedDocuments:
    manifest_digest: str
    library_root: Path
    operations: tuple[Operation, ...]
    journal_state: str
    journal_revision: int


@dataclass(frozen=True)
class PreparedRow:
    operation: Operation
    track_id: int
    size_bytes: int
    modified_at: float


@dataclass(frozen=True)
class Preview:
    manifest_digest: str
    journal_state: str
    journal_revision: int
    operation_count: int
    ready: int
    already_remapped: int
    missing_source_rows: int
    destination_conflicts: int
    unavailable_rows: int
    active_quarantine_conflicts: int
    dependent_row_counts: dict[str, int]
    blockers: tuple[str, ...]
    preserves_track_ids_and_foreign_keys: bool
    prepared: tuple[PreparedRow, ...]

    @property
    def all_already_remapped(self) -> bool:
        return self.operation_count > 0 and self.already_remapped == self.operation_count


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    migrated: int
    backup: Path | None
    report: Path | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest()


def load_documents(manifest_path: Path, journal_path: Path) -> ApprovedDocuments:
    manifest_raw, manifest = _load_json(manifest_path, "manifest")
    digest = hashlib.sha256(manifest_raw).hexdigest()
    _exact_keys(
        manifest,
        {
            "schema_version",
            "kind",
            "manifest_version",
            "generated_at",
            "source_plan_sha256",
            "source_plan_generated_at",
            "library_root",
            "operation_count",
            "operations",
        },
        "manifest",
    )
    if manifest["schema_version"] != 1 or manifest["kind"] != "organization_apply":
        raise InputError("unsupported manifest schema or kind")
    if manifest["manifest_version"] != 1:
        raise InputError("unsupported manifest version")
    _timestamp(manifest["generated_at"], "manifest.generated_at")
    _timestamp(manifest["source_plan_generated_at"], "manifest.source_plan_generated_at")
    _digest(manifest["source_plan_sha256"], "manifest.source_plan_sha256")
    root = _absolute_resolved_path(manifest["library_root"], "manifest.library_root")
    raw_operations = manifest["operations"]
    if not isinstance(raw_operations, list):
        raise InputError("manifest.operations must be a list")
    if _integer(manifest["operation_count"], "manifest.operation_count") != len(raw_operations):
        raise InputError("manifest operation_count mismatch")
    operations = tuple(
        _manifest_operation(value, index) for index, value in enumerate(raw_operations)
    )
    _validate_operation_set(operations)

    _, journal = _load_json(journal_path, "journal")
    required_journal = {
        "schema_version",
        "kind",
        "journal_version",
        "created_at",
        "updated_at",
        "approved_apply_manifest_sha256",
        "library_root",
        "operation_count",
        "revision",
        "state",
        "started_at",
        "completed_at",
        "undo_started_at",
        "undo_completed_at",
        "undo_attempt_count",
        "detail",
        "operations",
        "created_directories",
    }
    _exact_keys(journal, required_journal, "journal")
    if journal["schema_version"] != 2 or journal["kind"] != "organization_apply_journal":
        raise InputError("unsupported journal schema or kind")
    if journal["journal_version"] != 2:
        raise InputError("unsupported journal version")
    if _digest(journal["approved_apply_manifest_sha256"], "journal manifest digest") != digest:
        raise InputError("journal does not link to the exact manifest")
    if _absolute_resolved_path(journal["library_root"], "journal.library_root") != root:
        raise InputError("manifest and journal roots differ")
    if journal["state"] != "applied":
        if "recovery_required" in str(journal["state"]):
            raise CriticalError("Arcadia journal requires recovery")
        raise SafetyBlock("Arcadia journal is not terminally applied")
    revision = _nonnegative_integer(journal["revision"], "journal.revision")
    _timestamp(journal["created_at"], "journal.created_at")
    _timestamp(journal["updated_at"], "journal.updated_at")
    _timestamp(journal["started_at"], "journal.started_at")
    _timestamp(journal["completed_at"], "journal.completed_at")
    if journal["undo_started_at"] is not None or journal["undo_completed_at"] is not None:
        raise SafetyBlock("applied journal contains undo state")
    if _nonnegative_integer(journal["undo_attempt_count"], "journal.undo_attempt_count") != 0:
        raise SafetyBlock("applied journal records an undo attempt")
    _safe_detail(journal["detail"], "journal.detail")
    journal_operations = journal["operations"]
    if not isinstance(journal_operations, list):
        raise InputError("journal.operations must be a list")
    if _integer(journal["operation_count"], "journal.operation_count") != len(operations):
        raise InputError("journal operation_count mismatch")
    if len(journal_operations) != len(operations):
        raise InputError("journal and manifest operation counts differ")
    for index, (raw, approved) in enumerate(zip(journal_operations, operations, strict=True), 1):
        _validate_journal_operation(raw, approved, index)
    created_directories = journal["created_directories"]
    if not isinstance(created_directories, list):
        raise InputError("journal.created_directories must be a list")
    _validate_created_directories(created_directories, operations)
    return ApprovedDocuments(digest, root, operations, "applied", revision)


def preview_migration(
    database: Path,
    manifest: Path,
    journal: Path,
    music_root: Path,
) -> Preview:
    documents = load_documents(manifest, journal)
    root = _validate_root(music_root, documents.library_root)
    database = _validate_database_path(database)
    if database.is_relative_to(root):
        raise SafetyBlock("database and backup must be outside the music root")
    _reject_sqlite_sidecars(database)
    filesystem = _filesystem_preflight(root, documents.operations)
    blockers = list(filesystem[0])
    prepared_stats = filesystem[1]
    lock_blocker = _database_lock_blocker(database)
    if lock_blocker is not None:
        blockers.append(lock_blocker)
    connection = _connect_read_only(database)
    try:
        _validate_schema(connection)
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            blockers.append(f"foreign_key_check returned {len(foreign_key_errors)} row(s)")
        result = _database_preflight(connection, documents, prepared_stats, blockers)
    finally:
        connection.close()
    return result


def execute_migration(
    database: Path,
    manifest: Path,
    journal: Path,
    music_root: Path,
    *,
    confirm_manifest_sha256: str,
    confirm_database_sha256: str,
    report_path: Path | None = None,
    failure_hook: FailureHook | None = None,
) -> ExecutionResult:
    _require_confirmation(confirm_manifest_sha256, "manifest")
    _require_confirmation(confirm_database_sha256, "database")
    database = _validate_database_path(database)
    initial = preview_migration(database, manifest, journal, music_root)
    if initial.manifest_digest != confirm_manifest_sha256:
        raise SafetyBlock("manifest confirmation SHA-256 does not match")
    if sha256_file(database) != confirm_database_sha256:
        raise SafetyBlock("database confirmation SHA-256 does not match")
    if initial.blockers:
        raise SafetyBlock("preflight blocked: " + "; ".join(initial.blockers))
    if initial.all_already_remapped:
        return ExecutionResult("already_remapped", 0, None, None)
    if initial.ready != initial.operation_count:
        raise SafetyBlock("mixed pre-migration and post-migration state")
    report = report_path or database.with_name(
        f"{database.name}.organization-remap-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    report = _validate_result_path(report, Path(music_root))

    database_fd = os.open(database, os.O_RDONLY | os.O_NOFOLLOW)
    backup: Path | None = None
    connection: sqlite3.Connection | None = None
    committed = False
    try:
        try:
            fcntl.flock(database_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SafetyBlock("database offline lock is busy") from exc
        _reject_sqlite_sidecars(database)
        locked_documents = load_documents(manifest, journal)
        locked_root = _validate_root(Path(music_root), locked_documents.library_root)
        if locked_documents.manifest_digest != confirm_manifest_sha256:
            raise SafetyBlock("manifest changed after preview")
        locked_blockers, locked_stats = _filesystem_preflight(
            locked_root, locked_documents.operations
        )
        if locked_blockers:
            raise SafetyBlock("filesystem changed after preview: " + "; ".join(locked_blockers))
        expected_stats = {
            row.operation.operation_id: (row.size_bytes, row.modified_at)
            for row in initial.prepared
        }
        if locked_stats != expected_stats:
            raise SafetyBlock("filesystem metadata changed after preview")
        connection = sqlite3.connect(database, timeout=0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            raise SafetyBlock(f"database is busy: {exc}") from exc
        if sha256_file(database) != confirm_database_sha256:
            raise SafetyBlock(
                "database confirmation SHA-256 does not match immediately before mutation"
            )
        backup = _create_verified_backup(database, confirm_database_sha256)
        before = _dependent_values(connection)
        ids_before = {row.track_id for row in initial.prepared}
        indexed_at = datetime.now(UTC).isoformat()
        for index, row in enumerate(initial.prepared):
            category, artist = infer_path_metadata(row.operation.destination.as_posix())
            cursor = connection.execute(
                """
                UPDATE tracks SET
                    source_id = ?, relative_path = ?, file_name = ?, display_title = ?,
                    category_guess = ?, artist_guess = ?, extension = ?, size_bytes = ?,
                    modified_at = ?, indexed_at = ?, is_available = 1
                WHERE id = ? AND source = 'local'
                """,
                (
                    row.operation.destination.as_posix(),
                    row.operation.destination.as_posix(),
                    row.operation.destination.name,
                    row.operation.destination.stem,
                    category,
                    artist,
                    row.operation.destination.suffix.lower(),
                    row.size_bytes,
                    row.modified_at,
                    indexed_at,
                    row.track_id,
                ),
            )
            if cursor.rowcount != 1:
                raise CriticalError(f"track {row.track_id} was not updated exactly once")
            if failure_hook is not None:
                failure_hook("after_update", index)
        _verify_transaction(connection, initial, ids_before, before)
        if failure_hook is not None:
            failure_hook("before_commit", None)
        connection.execute("COMMIT")
        committed = True
        _fsync_path(database)
        _fsync_directory(database.parent)
        _verify_committed_database(database, initial, ids_before, before)
        _write_report(report, database, Path(music_root), initial, backup)
        return ExecutionResult("completed", initial.ready, backup, report)
    except SafetyBlock as exc:
        if connection is not None and connection.in_transaction:
            connection.execute("ROLLBACK")
        if committed:
            raise CriticalError(
                f"failure after commit; inspect database and backup: {exc}"
            ) from exc
        raise
    except CriticalError:
        if connection is not None and connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    except (OSError, sqlite3.Error) as exc:
        if connection is not None and connection.in_transaction:
            connection.execute("ROLLBACK")
        if committed:
            raise CriticalError(
                f"failure after commit; inspect database and backup: {exc}"
            ) from exc
        raise InputError(str(exc)) from exc
    except Exception as exc:
        if connection is not None and connection.in_transaction:
            connection.execute("ROLLBACK")
        if committed:
            raise CriticalError(
                f"failure after commit; inspect database and backup: {exc}"
            ) from exc
        raise
    finally:
        if connection is not None:
            connection.close()
        os.close(database_fd)


def _load_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise InputError(f"{label} must be a JSON object")
    return raw, value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise InputError(f"{label} fields differ (missing={missing}, extra={extra})")


def _manifest_operation(value: object, index: int) -> Operation:
    if not isinstance(value, dict):
        raise InputError(f"manifest operation {index} must be an object")
    _exact_keys(
        value,
        {"operation_id", "source_relative_path", "destination_relative_path", "source_sha256"},
        f"manifest.operations[{index}]",
    )
    operation_id = str(value["operation_id"])
    if not OPERATION_ID_RE.fullmatch(operation_id):
        raise InputError(f"invalid operation ID at index {index}")
    return Operation(
        operation_id,
        _safe_relative(value["source_relative_path"], f"operation {index} source"),
        _safe_relative(value["destination_relative_path"], f"operation {index} destination"),
        _digest(value["source_sha256"], f"operation {index} SHA-256"),
    )


def _validate_operation_set(operations: tuple[Operation, ...]) -> None:
    if not operations:
        raise InputError("manifest contains no operations")
    ids: set[str] = set()
    sources: set[PurePosixPath] = set()
    destinations: set[PurePosixPath] = set()
    for index, operation in enumerate(operations, 1):
        if operation.operation_id != f"operation-{index:06d}":
            raise InputError("operation IDs are not complete and ordered")
        if operation.source == operation.destination:
            raise InputError(f"{operation.operation_id} does not change path")
        if (
            operation.operation_id in ids
            or operation.source in sources
            or operation.destination in destinations
        ):
            raise InputError("duplicate operation ID, source, or destination")
        ids.add(operation.operation_id)
        sources.add(operation.source)
        destinations.add(operation.destination)


def _validate_journal_operation(value: object, approved: Operation, index: int) -> None:
    if not isinstance(value, dict):
        raise InputError(f"journal operation {index} must be an object")
    expected = {
        "operation_id",
        "operation_index",
        "source_relative_path",
        "destination_relative_path",
        "source_sha256",
        "state",
        "intent_at",
        "linked_at",
        "moved_at",
        "rolled_back_at",
        "undo_intent_at",
        "undo_linked_at",
        "undone_at",
        "undo_rolled_back_at",
        "recovery_required_at",
        "detail",
    }
    _exact_keys(value, expected, f"journal.operations[{index - 1}]")
    actual = (
        value["operation_id"],
        _integer(value["operation_index"], "operation_index"),
        _safe_relative(value["source_relative_path"], "journal source"),
        _safe_relative(value["destination_relative_path"], "journal destination"),
        _digest(value["source_sha256"], "journal SHA-256"),
    )
    expected_values = (
        approved.operation_id,
        index,
        approved.source,
        approved.destination,
        approved.sha256,
    )
    if actual != expected_values:
        raise InputError(f"journal operation {index} differs from manifest")
    if value["state"] != "moved":
        if value["state"] == "apply_recovery_required":
            raise CriticalError(f"journal operation {index} requires recovery")
        raise SafetyBlock(f"journal operation {index} is not terminally applied")
    for field in ("intent_at", "linked_at", "moved_at"):
        _timestamp(value[field], f"journal operation {index}.{field}")
    for field in (
        "rolled_back_at",
        "undo_intent_at",
        "undo_linked_at",
        "undone_at",
        "undo_rolled_back_at",
        "recovery_required_at",
    ):
        if value[field] is not None:
            raise SafetyBlock(f"journal operation {index} contains {field}")
    _safe_detail(value["detail"], f"journal operation {index}.detail")


def _validate_created_directories(values: list[object], operations: tuple[Operation, ...]) -> None:
    allowed = {
        parent
        for operation in operations
        for parent in operation.destination.parents
        if parent != PurePosixPath(".")
    }
    source_parents = {operation.source.parent for operation in operations}
    seen: set[PurePosixPath] = set()
    expected = {
        "relative_path",
        "state",
        "intent_at",
        "device",
        "inode",
        "created_at",
        "removed_at",
    }
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise InputError(f"created_directories[{index}] must be an object")
        _exact_keys(value, expected, f"created_directories[{index}]")
        relative = _safe_relative(
            value["relative_path"], f"created_directories[{index}].relative_path"
        )
        if relative in seen:
            raise InputError("created_directories contains duplicates")
        if relative not in allowed or relative in source_parents:
            raise InputError("created directory is not a safe destination parent")
        seen.add(relative)
        if value["state"] not in {"created", "removed"}:
            if value["state"] == "recovery_required":
                raise CriticalError("created directory requires recovery")
            raise SafetyBlock("applied journal has a non-terminal created directory")
        _timestamp(value["intent_at"], f"created_directories[{index}].intent_at")
        _nonnegative_integer(value["device"], f"created_directories[{index}].device")
        _nonnegative_integer(value["inode"], f"created_directories[{index}].inode")
        _timestamp(value["created_at"], f"created_directories[{index}].created_at")
        if value["state"] == "created" and value["removed_at"] is not None:
            raise InputError("created directory unexpectedly has removed_at")
        if value["state"] == "removed":
            _timestamp(value["removed_at"], f"created_directories[{index}].removed_at")


def _safe_relative(value: object, label: str) -> PurePosixPath:
    raw = str(value or "")
    path = PurePosixPath(raw)
    if (
        not raw
        or raw.strip() != raw
        or "\\" in raw
        or "\x00" in raw
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise InputError(f"{label} is not a safe relative path")
    return path


def _digest(value: object, label: str) -> str:
    digest = str(value or "")
    if not SHA256_RE.fullmatch(digest):
        raise InputError(f"{label} must be a full lowercase SHA-256")
    return digest


def _timestamp(value: object, label: str) -> str:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise InputError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputError(f"{label} must include a timezone")
    return text


def _safe_detail(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputError(f"{label} must be a string or null")
    detail = value.strip()
    if not detail:
        return None
    if len(detail) > 300 or SENSITIVE_DETAIL_RE.search(detail):
        raise InputError(f"{label} is unsafe")
    return detail


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(f"{label} must be an integer")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    result = _integer(value, label)
    if result < 0:
        raise InputError(f"{label} must be non-negative")
    return result


def _absolute_resolved_path(value: object, label: str) -> Path:
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute() or path != path.resolve():
        raise InputError(f"{label} must be a resolved absolute path")
    return path


def _validate_root(requested: Path, approved: Path) -> Path:
    root = requested.expanduser()
    if not root.is_absolute() or root != root.resolve() or root != approved:
        raise SafetyBlock("music root must exactly match the approved resolved root")
    if not root.is_dir() or root.is_symlink():
        raise SafetyBlock("music root is missing, not a directory, or a symlink")
    return root


def _validate_database_path(database: Path) -> Path:
    database = database.expanduser().absolute()
    try:
        metadata = os.lstat(database)
    except OSError as exc:
        raise InputError(f"cannot inspect database: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SafetyBlock("database must be a regular non-symlink file")
    if database.resolve() != database:
        raise SafetyBlock("database path has a symlinked parent")
    return database


def _filesystem_preflight(
    root: Path, operations: tuple[Operation, ...]
) -> tuple[list[str], dict[str, tuple[int, float]]]:
    blockers: list[str] = []
    stats: dict[str, tuple[int, float]] = {}
    identities: set[tuple[int, int]] = set()
    for operation in operations:
        label = operation.operation_id
        source = root.joinpath(*operation.source.parts)
        destination = root.joinpath(*operation.destination.parts)
        if os.path.lexists(source):
            blockers.append(f"{label}: old source still exists")
        try:
            _reject_symlink_components(root, destination)
            resolved = destination.resolve(strict=True)
            resolved.relative_to(root)
            metadata = os.stat(destination, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                raise SafetyBlock("destination is not a regular file")
            identity = (metadata.st_dev, metadata.st_ino)
            if identity in identities:
                raise SafetyBlock("destination aliases another operation")
            identities.add(identity)
            if sha256_file(destination) != operation.sha256:
                raise SafetyBlock("destination SHA-256 changed")
            stats[label] = (metadata.st_size, metadata.st_mtime)
        except (OSError, ValueError, SafetyBlock, InputError) as exc:
            blockers.append(f"{label}: {exc}")
    return blockers, stats


def _reject_symlink_components(root: Path, destination: Path) -> None:
    current = root
    for part in destination.relative_to(root).parts:
        current /= part
        metadata = os.lstat(current)
        if stat.S_ISLNK(metadata.st_mode):
            raise SafetyBlock(f"symlink component: {current.name}")


def _connect_read_only(database: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(database), safe='/')}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection
    except sqlite3.Error as exc:
        raise InputError(f"cannot open database read-only: {exc}") from exc


def _database_lock_blocker(database: Path) -> str | None:
    descriptor = os.open(database, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return "database offline lock is busy"
        return None
    finally:
        os.close(descriptor)


def _validate_schema(connection: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
    }
    required = {"tracks", *DEPENDENT_TABLES}
    if not required.issubset(tables):
        raise SafetyBlock(f"unsupported schema; missing tables: {sorted(required - tables)}")
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(tracks)")}
    if not REQUIRED_TRACK_COLUMNS.issubset(columns):
        raise SafetyBlock("unsupported tracks schema")
    indexes = connection.execute("PRAGMA index_list(tracks)").fetchall()
    unique_columns = {
        tuple(
            str(column[2])
            for column in connection.execute(
                f"PRAGMA index_info({_quote_identifier(str(row[1]))})"
            ).fetchall()
        )
        for row in indexes
        if bool(row[2])
    }
    if ("source", "source_id") not in unique_columns or ("relative_path",) not in unique_columns:
        raise SafetyBlock("unsupported tracks uniqueness constraints")
    for table in DEPENDENT_TABLES:
        foreign_keys = connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        if not any(
            row[2] == "tracks" and row[3] == "track_id" and row[4] == "id" for row in foreign_keys
        ):
            raise SafetyBlock(f"unsupported {table} foreign key schema")


def _database_preflight(
    connection: sqlite3.Connection,
    documents: ApprovedDocuments,
    prepared_stats: dict[str, tuple[int, float]],
    blockers: list[str],
) -> Preview:
    ready = already = missing = conflicts = unavailable = quarantine = 0
    prepared: list[PreparedRow] = []
    for operation in documents.operations:
        old_rows = connection.execute(
            "SELECT id, source_id, relative_path, is_available FROM tracks "
            "WHERE source = 'local' AND (source_id = ? OR relative_path = ?)",
            (operation.source.as_posix(), operation.source.as_posix()),
        ).fetchall()
        new_rows = connection.execute(
            "SELECT id, source_id, relative_path, is_available FROM tracks "
            "WHERE source = 'local' AND (source_id = ? OR relative_path = ?)",
            (operation.destination.as_posix(), operation.destination.as_posix()),
        ).fetchall()
        exact_old = [
            row
            for row in old_rows
            if row["source_id"] == operation.source.as_posix()
            and row["relative_path"] == operation.source.as_posix()
        ]
        exact_new = [
            row
            for row in new_rows
            if row["source_id"] == operation.destination.as_posix()
            and row["relative_path"] == operation.destination.as_posix()
        ]
        if exact_new and not old_rows:
            if len(exact_new) == 1 and len(new_rows) == 1 and bool(exact_new[0]["is_available"]):
                already += 1
            else:
                conflicts += 1
                blockers.append(f"{operation.operation_id}: inconsistent destination row")
            continue
        if not exact_old:
            missing += 1
            blockers.append(f"{operation.operation_id}: source row missing or inconsistent")
            continue
        if len(exact_old) != 1 or len(old_rows) != 1:
            blockers.append(f"{operation.operation_id}: source row is ambiguous")
            continue
        row = exact_old[0]
        if new_rows and any(other["id"] != row["id"] for other in new_rows):
            conflicts += 1
            blockers.append(f"{operation.operation_id}: destination belongs to another track")
            continue
        if not bool(row["is_available"]):
            unavailable += 1
            blockers.append(f"{operation.operation_id}: source row is unavailable")
            continue
        active = connection.execute(
            "SELECT COUNT(*) FROM track_quarantine WHERE track_id = ? AND state = 'quarantined'",
            (row["id"],),
        ).fetchone()[0]
        if active:
            quarantine += 1
            blockers.append(f"{operation.operation_id}: source row has active quarantine")
            continue
        if operation.operation_id not in prepared_stats:
            continue
        size, modified = prepared_stats[operation.operation_id]
        ready += 1
        prepared.append(PreparedRow(operation, int(row["id"]), size, modified))
    active_local = int(
        connection.execute(
            "SELECT COUNT(*) FROM tracks WHERE source = 'local' AND is_available = 1"
        ).fetchone()[0]
    )
    if active_local != len(documents.operations):
        blockers.append(
            "active local track count does not equal manifest operation count "
            f"({active_local} != {len(documents.operations)})"
        )
    if ready and already:
        blockers.append("mixed pre-migration and post-migration state")
    counts = {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in DEPENDENT_TABLES
    }
    return Preview(
        documents.manifest_digest,
        documents.journal_state,
        documents.journal_revision,
        len(documents.operations),
        ready,
        already,
        missing,
        conflicts,
        unavailable,
        quarantine,
        counts,
        tuple(blockers),
        not blockers
        and (ready == len(documents.operations) or already == len(documents.operations)),
        tuple(prepared),
    )


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _dependent_values(connection: sqlite3.Connection) -> dict[str, tuple[tuple[Any, ...], ...]]:
    result: dict[str, tuple[tuple[Any, ...], ...]] = {}
    for table in DEPENDENT_TABLES:
        columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]
        rows = connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        result[table] = tuple(tuple(row[column] for column in columns) for row in rows)
    return result


def _verify_transaction(
    connection: sqlite3.Connection,
    preview: Preview,
    ids_before: set[int],
    dependent_before: dict[str, tuple[tuple[Any, ...], ...]],
) -> None:
    ids_after: set[int] = set()
    for prepared in preview.prepared:
        row = connection.execute(
            "SELECT id, source_id, relative_path FROM tracks WHERE id = ?",
            (prepared.track_id,),
        ).fetchone()
        if (
            row is None
            or row["source_id"] != prepared.operation.destination.as_posix()
            or row["relative_path"] != prepared.operation.destination.as_posix()
        ):
            raise CriticalError(f"track {prepared.track_id} failed destination verification")
        ids_after.add(int(row["id"]))
        old_count = connection.execute(
            "SELECT COUNT(*) FROM tracks WHERE source = 'local' AND "
            "(source_id = ? OR relative_path = ?)",
            (prepared.operation.source.as_posix(), prepared.operation.source.as_posix()),
        ).fetchone()[0]
        if old_count:
            raise CriticalError("an old path remains active")
    if ids_after != ids_before:
        raise CriticalError("track IDs changed")
    if _dependent_values(connection) != dependent_before:
        raise CriticalError("dependent data changed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise CriticalError("foreign key verification failed")
    integrity = connection.execute("PRAGMA integrity_check").fetchall()
    if [str(row[0]) for row in integrity] != ["ok"]:
        raise CriticalError("SQLite integrity or uniqueness verification failed")
    active_count = connection.execute(
        "SELECT COUNT(*) FROM tracks WHERE source = 'local' AND is_available = 1"
    ).fetchone()[0]
    if active_count != preview.operation_count:
        raise CriticalError("active local count does not equal manifest operation count")


def _verify_committed_database(
    database: Path,
    preview: Preview,
    ids_before: set[int],
    dependent_before: dict[str, tuple[tuple[Any, ...], ...]],
) -> None:
    connection = _connect_read_only(database)
    try:
        _verify_transaction(connection, preview, ids_before, dependent_before)
    finally:
        connection.close()


def _reject_sqlite_sidecars(database: Path) -> None:
    existing = [
        path.name
        for path in (
            Path(f"{database}-journal"),
            Path(f"{database}-wal"),
            Path(f"{database}-shm"),
        )
        if os.path.lexists(path)
    ]
    if existing:
        raise SafetyBlock(f"SQLite sidecars exist: {', '.join(existing)}")


def _create_verified_backup(database: Path, expected_digest: str) -> Path:
    backup = database.with_name(
        f"{database.name}.pre-organization-remap-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.bak"
    )
    if os.path.lexists(backup):
        raise SafetyBlock(f"backup path already exists: {backup}")
    try:
        with database.open("rb") as source, backup.open("xb") as destination:
            shutil.copyfileobj(source, destination, 1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
    except OSError as exc:
        backup.unlink(missing_ok=True)
        raise InputError(f"cannot create backup: {exc}") from exc
    if sha256_file(backup) != expected_digest:
        raise CriticalError("backup verification failed")
    _fsync_directory(backup.parent)
    return backup


def _write_report(
    path: Path, database: Path, music_root: Path, preview: Preview, backup: Path
) -> None:
    path = path.expanduser().absolute()
    if path.resolve().is_relative_to(music_root.resolve()):
        raise SafetyBlock("result report must be outside the music root")
    if os.path.lexists(path):
        raise SafetyBlock(f"report already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "weasel_organization_index_migration_result",
        "version": 1,
        "completed_at": datetime.now(UTC).isoformat(),
        "database": str(database),
        "database_sha256_after": sha256_file(database),
        "manifest_sha256": preview.manifest_digest,
        "operation_count": preview.operation_count,
        "migrated": preview.ready,
        "backup": str(backup),
        "dependent_row_counts": preview.dependent_row_counts,
        "track_ids_preserved": True,
        "foreign_keys_preserved": True,
        "audio_files_modified": False,
    }
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as destination:
        destination.write(content)
        destination.flush()
        os.fsync(destination.fileno())
    _fsync_directory(path.parent)


def _validate_result_path(path: Path, music_root: Path) -> Path:
    path = path.expanduser().absolute()
    if path.resolve().is_relative_to(music_root.resolve()):
        raise SafetyBlock("result report must be outside the music root")
    if os.path.lexists(path):
        raise SafetyBlock(f"report already exists: {path}")
    return path


def _fsync_path(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_confirmation(value: str, label: str) -> None:
    if not SHA256_RE.fullmatch(value):
        raise SafetyBlock(f"{label} confirmation must be a full lowercase SHA-256")


def _print_preview(preview: Preview) -> None:
    print("Weasel Bot organization index migration preview")
    print(f"Manifest SHA-256: {preview.manifest_digest}")
    print(f"Journal: {preview.journal_state} (revision {preview.journal_revision})")
    print(f"Operations: {preview.operation_count}")
    print(f"Source rows ready: {preview.ready}")
    print(f"Already remapped: {preview.already_remapped}")
    print(f"Missing source rows: {preview.missing_source_rows}")
    print(f"Destination row conflicts: {preview.destination_conflicts}")
    print(f"Unavailable rows: {preview.unavailable_rows}")
    print(f"Active quarantine conflicts: {preview.active_quarantine_conflicts}")
    print("Dependent rows:")
    for table, count in preview.dependent_row_counts.items():
        print(f"  {table}: {count}")
    print(f"Track IDs and foreign keys preserved: {preview.preserves_track_ids_and_foreign_keys}")
    print(f"Blockers: {len(preview.blockers)}")
    for blocker in preview.blockers:
        print(f"- {blocker}")
    print("No filesystem entry or audio file was changed.")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--music-root", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-manifest-sha256", default="")
    parser.add_argument("--confirm-database-sha256", default="")
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if not args.execute:
            preview = preview_migration(args.database, args.manifest, args.journal, args.music_root)
            _print_preview(preview)
            return 1 if preview.blockers else 0
        result = execute_migration(
            args.database,
            args.manifest,
            args.journal,
            args.music_root,
            confirm_manifest_sha256=args.confirm_manifest_sha256,
            confirm_database_sha256=args.confirm_database_sha256,
            report_path=args.report,
        )
        print(f"Migration status: {result.status}")
        print(f"Migrated tracks: {result.migrated}")
        if result.backup:
            print(f"Verified backup: {result.backup}")
        if result.report:
            print(f"Result report: {result.report}")
        print("No audio file was modified.")
        return 0
    except SafetyBlock as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        return 1
    except InputError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    except CriticalError as exc:
        print(f"[CRITICAL] {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
