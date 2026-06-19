from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from weasel_bot_v2.config import DatabaseConfig
from weasel_bot_v2.database import SQLiteDatabase
from weasel_bot_v2.organization_index_migration import (
    CriticalError,
    InputError,
    SafetyBlock,
    execute_migration,
    main,
    preview_migration,
    sha256_file,
)
from weasel_bot_v2.repositories import TrackRepository
from weasel_bot_v2.services.local_library import LocalLibraryService

NOW = "2026-06-19T00:00:00+00:00"


@dataclass
class MigrationCase:
    root: Path
    database: Path
    manifest: Path
    journal: Path
    report: Path
    old_paths: list[str]
    new_paths: list[str]
    track_ids: list[int]
    audio_before: dict[str, bytes]

    @property
    def manifest_digest(self) -> str:
        return sha256_file(self.manifest)

    @property
    def database_digest(self) -> str:
        return sha256_file(self.database)

    def preview(self):
        return preview_migration(self.database, self.manifest, self.journal, self.root)

    def execute(self, **kwargs):
        return execute_migration(
            self.database,
            self.manifest,
            self.journal,
            self.root,
            confirm_manifest_sha256=self.manifest_digest,
            confirm_database_sha256=self.database_digest,
            report_path=self.report,
            **kwargs,
        )


@pytest.fixture
def migration_case(tmp_path: Path) -> MigrationCase:
    return _build_case(tmp_path, count=2)


def test_clean_preview_is_side_effect_free(migration_case: MigrationCase) -> None:
    before = _tree(migration_case.root.parent)

    preview = migration_case.preview()

    assert preview.ready == 2
    assert preview.blockers == ()
    assert preview.preserves_track_ids_and_foreign_keys is True
    assert preview.dependent_row_counts == {
        "ratings": 2,
        "track_volume_overrides": 2,
        "playlist_items": 2,
        "play_history": 2,
        "track_quarantine": 2,
        "play_all_track_exceptions": 2,
    }
    assert _tree(migration_case.root.parent) == before


def test_success_preserves_ids_dependencies_curated_fields_and_audio(
    migration_case: MigrationCase,
) -> None:
    dependencies_before = _dependent_rows(migration_case.database)
    audio_before = _audio_state(migration_case.root)

    result = migration_case.execute()

    assert result.status == "completed"
    assert result.migrated == 2
    assert result.backup is not None and result.backup.exists()
    assert result.report == migration_case.report and migration_case.report.exists()
    assert _dependent_rows(migration_case.database) == dependencies_before
    assert _audio_state(migration_case.root) == audio_before
    with sqlite3.connect(migration_case.database) as connection:
        rows = connection.execute(
            "SELECT id, source_id, relative_path, file_name, display_title, "
            "category_guess, artist_guess, extension, title, artist, duration_ms, "
            "is_available FROM tracks ORDER BY id"
        ).fetchall()
    assert [row[0] for row in rows] == migration_case.track_ids
    assert [row[1] for row in rows] == migration_case.new_paths
    assert [row[2] for row in rows] == migration_case.new_paths
    assert rows[0][3:8] == ("Song 0.mp3", "Song 0", "France", "Artist_0", ".mp3")
    assert rows[0][8:11] == ("Curated 0", "Curator 0", 120000)
    assert all(row[11] == 1 for row in rows)


def test_scan_after_migration_updates_same_rows_without_duplicates(
    migration_case: MigrationCase,
) -> None:
    migration_case.execute()
    database = SQLiteDatabase(DatabaseConfig(path=migration_case.database))
    tracks = TrackRepository(database)

    result = LocalLibraryService(migration_case.root, tracks).scan()

    assert result.upserted == 2
    assert tracks.count_local() == 2
    assert [track.id for track in tracks.list_local()] == migration_case.track_ids


def test_preview_and_repeated_execution_are_idempotent(migration_case: MigrationCase) -> None:
    migration_case.execute()

    preview = migration_case.preview()
    repeated = execute_migration(
        migration_case.database,
        migration_case.manifest,
        migration_case.journal,
        migration_case.root,
        confirm_manifest_sha256=migration_case.manifest_digest,
        confirm_database_sha256=migration_case.database_digest,
        report_path=migration_case.root.parent / "unused.json",
    )

    assert preview.already_remapped == 2
    assert preview.ready == 0
    assert preview.blockers == ()
    assert repeated.status == "already_remapped"
    assert repeated.backup is None


@pytest.mark.parametrize(
    ("mutation", "field"),
    [
        ("missing", "missing_source_rows"),
        ("conflict", "destination_conflicts"),
        ("unavailable", "unavailable_rows"),
        ("quarantine", "active_quarantine_conflicts"),
    ],
)
def test_database_blocks(migration_case: MigrationCase, mutation: str, field: str) -> None:
    with sqlite3.connect(migration_case.database) as connection:
        if mutation == "missing":
            connection.execute(
                "DELETE FROM ratings WHERE track_id = ?", (migration_case.track_ids[0],)
            )
            connection.execute(
                "DELETE FROM track_volume_overrides WHERE track_id = ?",
                (migration_case.track_ids[0],),
            )
            connection.execute(
                "DELETE FROM playlist_items WHERE track_id = ?", (migration_case.track_ids[0],)
            )
            connection.execute(
                "DELETE FROM play_history WHERE track_id = ?", (migration_case.track_ids[0],)
            )
            connection.execute(
                "DELETE FROM track_quarantine WHERE track_id = ?", (migration_case.track_ids[0],)
            )
            connection.execute(
                "DELETE FROM play_all_track_exceptions WHERE track_id = ?",
                (migration_case.track_ids[0],),
            )
            connection.execute("DELETE FROM tracks WHERE id = ?", (migration_case.track_ids[0],))
        elif mutation == "conflict":
            destination = migration_case.new_paths[0]
            connection.execute(
                "INSERT INTO tracks(source, source_id, relative_path) VALUES('local', ?, ?)",
                (destination, destination),
            )
        elif mutation == "unavailable":
            connection.execute(
                "UPDATE tracks SET is_available = 0 WHERE id = ?", (migration_case.track_ids[0],)
            )
        else:
            connection.execute(
                "UPDATE track_quarantine SET state = 'quarantined' WHERE track_id = ?",
                (migration_case.track_ids[0],),
            )
        connection.commit()

    preview = migration_case.preview()

    assert getattr(preview, field) == 1
    assert preview.blockers


def test_mixed_state_is_rejected(migration_case: MigrationCase) -> None:
    with sqlite3.connect(migration_case.database) as connection:
        connection.execute(
            "UPDATE tracks SET source_id = ?, relative_path = ? WHERE id = ?",
            (migration_case.new_paths[0], migration_case.new_paths[0], migration_case.track_ids[0]),
        )
        connection.commit()

    preview = migration_case.preview()

    assert preview.ready == 1
    assert preview.already_remapped == 1
    assert "mixed pre-migration and post-migration state" in preview.blockers


@pytest.mark.parametrize(
    "target",
    ["manifest-json", "manifest-kind", "journal-json", "journal-digest", "journal-root"],
)
def test_malformed_or_mismatched_documents_block(
    migration_case: MigrationCase, target: str
) -> None:
    path = migration_case.manifest if target.startswith("manifest") else migration_case.journal
    if target.endswith("json"):
        path.write_text("{", encoding="utf-8")
    else:
        payload = json.loads(path.read_text())
        if target == "manifest-kind":
            payload["kind"] = "other"
        elif target == "journal-digest":
            payload["approved_apply_manifest_sha256"] = "0" * 64
        else:
            payload["library_root"] = "/tmp/other"
        _write_json(path, payload)

    with pytest.raises((InputError, SafetyBlock)):
        migration_case.preview()


@pytest.mark.parametrize("state", ["prepared", "in_progress"])
def test_non_terminal_journal_blocks(migration_case: MigrationCase, state: str) -> None:
    payload = json.loads(migration_case.journal.read_text())
    payload["state"] = state
    _write_json(migration_case.journal, payload)

    with pytest.raises(SafetyBlock):
        migration_case.preview()


def test_recovery_required_journal_is_critical(migration_case: MigrationCase) -> None:
    payload = json.loads(migration_case.journal.read_text())
    payload["state"] = "apply_recovery_required"
    _write_json(migration_case.journal, payload)

    with pytest.raises(CriticalError):
        migration_case.preview()


@pytest.mark.parametrize(
    ("location", "detail"),
    [
        ("journal", {"unexpected": "object"}),
        ("journal", "token=not-accepted"),
        ("operation", {"unexpected": "object"}),
        ("operation", "password=not-accepted"),
    ],
)
def test_malformed_or_unsafe_journal_detail_blocks(
    migration_case: MigrationCase, location: str, detail: object
) -> None:
    payload = json.loads(migration_case.journal.read_text())
    if location == "journal":
        payload["detail"] = detail
    else:
        payload["operations"][0]["detail"] = detail
    _write_json(migration_case.journal, payload)

    with pytest.raises(InputError, match="detail"):
        migration_case.preview()


def test_requested_music_root_mismatch_blocks(migration_case: MigrationCase) -> None:
    other = migration_case.root.parent / "other-music"
    other.mkdir()

    with pytest.raises(SafetyBlock, match="music root"):
        preview_migration(
            migration_case.database,
            migration_case.manifest,
            migration_case.journal,
            other,
        )


@pytest.mark.parametrize("mutation", ["changed", "missing", "symlink", "symlink-parent"])
def test_destination_filesystem_blocks(migration_case: MigrationCase, mutation: str) -> None:
    destination = migration_case.root / migration_case.new_paths[0]
    if mutation == "changed":
        destination.write_bytes(b"changed")
    elif mutation == "missing":
        destination.unlink()
    elif mutation == "symlink":
        target = migration_case.root.parent / "outside.mp3"
        target.write_bytes(b"audio-0")
        destination.unlink()
        destination.symlink_to(target)
    else:
        artist = destination.parent
        replacement = migration_case.root / "real-artist"
        artist.rename(replacement)
        artist.symlink_to(replacement, target_is_directory=True)

    preview = migration_case.preview()

    assert preview.blockers


def test_database_symlink_blocks(migration_case: MigrationCase) -> None:
    link = migration_case.database.parent / "linked.db"
    link.symlink_to(migration_case.database)

    with pytest.raises(SafetyBlock):
        preview_migration(
            link, migration_case.manifest, migration_case.journal, migration_case.root
        )


def test_wrong_database_confirmation_blocks_without_backup(migration_case: MigrationCase) -> None:
    with pytest.raises(SafetyBlock):
        execute_migration(
            migration_case.database,
            migration_case.manifest,
            migration_case.journal,
            migration_case.root,
            confirm_manifest_sha256=migration_case.manifest_digest,
            confirm_database_sha256="0" * 64,
        )

    assert not list(migration_case.database.parent.glob("*.bak"))


def test_database_lock_conflict_blocks(migration_case: MigrationCase) -> None:
    descriptor = os.open(migration_case.database, os.O_RDONLY)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(SafetyBlock, match="lock"):
            migration_case.execute()
    finally:
        os.close(descriptor)


def test_sqlite_busy_database_blocks(migration_case: MigrationCase) -> None:
    connection = sqlite3.connect(migration_case.database)
    connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(SafetyBlock, match="busy|locked"):
            migration_case.execute()
    finally:
        connection.rollback()
        connection.close()


def test_wal_sidecar_blocks(migration_case: MigrationCase) -> None:
    Path(f"{migration_case.database}-wal").touch()

    with pytest.raises(SafetyBlock, match="sidecars"):
        migration_case.execute()


def test_broken_sqlite_sidecar_symlink_blocks(migration_case: MigrationCase) -> None:
    Path(f"{migration_case.database}-wal").symlink_to("missing-wal-target")

    with pytest.raises(SafetyBlock, match="sidecars"):
        migration_case.preview()


def test_report_inside_music_root_blocks_before_backup(migration_case: MigrationCase) -> None:
    with pytest.raises(SafetyBlock, match="report"):
        execute_migration(
            migration_case.database,
            migration_case.manifest,
            migration_case.journal,
            migration_case.root,
            confirm_manifest_sha256=migration_case.manifest_digest,
            confirm_database_sha256=migration_case.database_digest,
            report_path=migration_case.root / "report.json",
        )

    assert not list(migration_case.database.parent.glob("*.bak"))


def test_injected_failure_rolls_back_complete_transaction(
    tmp_path: Path,
) -> None:
    migration_case = _build_case(tmp_path, count=3)
    rows_before = _track_rows(migration_case.database)

    def fail(stage: str, index: int | None) -> None:
        if stage == "after_update" and index == 1:
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        migration_case.execute(failure_hook=fail)

    assert _track_rows(migration_case.database) == rows_before
    assert not migration_case.report.exists()


def test_backup_matches_original_database(migration_case: MigrationCase) -> None:
    digest = migration_case.database_digest

    result = migration_case.execute()

    assert result.backup is not None
    assert sha256_file(result.backup) == digest


def test_cli_exit_codes(migration_case: MigrationCase, capsys: pytest.CaptureFixture[str]) -> None:
    common = [
        "--database",
        str(migration_case.database),
        "--manifest",
        str(migration_case.manifest),
        "--journal",
        str(migration_case.journal),
        "--music-root",
        str(migration_case.root),
    ]
    assert main(common) == 0
    assert "Source rows ready: 2" in capsys.readouterr().out
    assert (
        main(
            [
                *common,
                "--execute",
                "--confirm-manifest-sha256",
                migration_case.manifest_digest,
                "--confirm-database-sha256",
                migration_case.database_digest,
                "--report",
                str(migration_case.report),
            ]
        )
        == 0
    )
    assert main([*common, "--execute"]) == 1
    migration_case.manifest.write_text("{", encoding="utf-8")
    assert main(common) == 2


def test_cli_critical_exit_code(migration_case: MigrationCase) -> None:
    payload = json.loads(migration_case.journal.read_text())
    payload["state"] = "apply_recovery_required"
    _write_json(migration_case.journal, payload)

    assert (
        main(
            [
                "--database",
                str(migration_case.database),
                "--manifest",
                str(migration_case.manifest),
                "--journal",
                str(migration_case.journal),
                "--music-root",
                str(migration_case.root),
            ]
        )
        == 3
    )


def _build_case(tmp_path: Path, *, count: int) -> MigrationCase:
    root = (tmp_path / "music").resolve()
    root.mkdir()
    database = (tmp_path / "weasel.db").resolve()
    SQLiteDatabase(DatabaseConfig(path=database)).initialize()
    old_paths = [f"legacy/Song {index}.mp3" for index in range(count)]
    new_paths = [f"France/Artist_{index}/Song {index}.mp3" for index in range(count)]
    operations = []
    audio_before = {}
    for index, (old, new) in enumerate(zip(old_paths, new_paths, strict=True), 1):
        content = f"audio-{index - 1}".encode()
        destination = root / new
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        audio_before[new] = content
        operations.append(
            {
                "operation_id": f"operation-{index:06d}",
                "source_relative_path": old,
                "destination_relative_path": new,
                "source_sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest_payload = {
        "schema_version": 1,
        "kind": "organization_apply",
        "manifest_version": 1,
        "generated_at": NOW,
        "source_plan_sha256": "a" * 64,
        "source_plan_generated_at": NOW,
        "library_root": root.as_posix(),
        "operation_count": count,
        "operations": operations,
    }
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, manifest_payload)
    journal_operations = [
        {
            **operation,
            "operation_index": index,
            "state": "moved",
            "intent_at": NOW,
            "linked_at": NOW,
            "moved_at": NOW,
            "rolled_back_at": None,
            "undo_intent_at": None,
            "undo_linked_at": None,
            "undone_at": None,
            "undo_rolled_back_at": None,
            "recovery_required_at": None,
            "detail": None,
        }
        for index, operation in enumerate(operations, 1)
    ]
    journal_payload = {
        "schema_version": 2,
        "kind": "organization_apply_journal",
        "journal_version": 2,
        "created_at": NOW,
        "updated_at": NOW,
        "approved_apply_manifest_sha256": sha256_file(manifest),
        "library_root": root.as_posix(),
        "operation_count": count,
        "revision": 10,
        "state": "applied",
        "started_at": NOW,
        "completed_at": NOW,
        "undo_started_at": None,
        "undo_completed_at": None,
        "undo_attempt_count": 0,
        "detail": None,
        "operations": journal_operations,
        "created_directories": [],
    }
    journal = tmp_path / "journal.json"
    _write_json(journal, journal_payload)
    track_ids = _seed_database(database, old_paths)
    return MigrationCase(
        root,
        database,
        manifest,
        journal,
        tmp_path / "result.json",
        old_paths,
        new_paths,
        track_ids,
        audio_before,
    )


def _seed_database(database: Path, paths: list[str]) -> list[int]:
    ids = []
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("INSERT INTO users(user_id, display_name) VALUES(1, 'user')")
        connection.execute("INSERT INTO playlists(owner_user_id, name) VALUES(1, 'list')")
        for index, path in enumerate(paths):
            cursor = connection.execute(
                """
                INSERT INTO tracks(
                    source, source_id, relative_path, file_name, display_title,
                    title, artist, duration_ms, is_available
                ) VALUES('local', ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    path,
                    path,
                    PurePosixPath(path).name,
                    PurePosixPath(path).stem,
                    f"Curated {index}",
                    f"Curator {index}",
                    120000 + index,
                ),
            )
            if cursor.lastrowid is None:
                raise AssertionError("track insert did not return an ID")
            track_id = cursor.lastrowid
            ids.append(track_id)
            connection.execute(
                "INSERT INTO ratings(guild_id,user_id,track_id,rating) VALUES(1,1,?,'like')",
                (track_id,),
            )
            connection.execute(
                "INSERT INTO track_volume_overrides(guild_id,track_id,volume) VALUES(1,?,110)",
                (track_id,),
            )
            connection.execute(
                "INSERT INTO playlist_items(playlist_id,position,track_id,added_by_user_id) "
                "VALUES(1,?,?,1)",
                (index, track_id),
            )
            connection.execute(
                "INSERT INTO play_history(guild_id,user_id,track_id,context) VALUES(1,1,?,'test')",
                (track_id,),
            )
            connection.execute(
                "INSERT INTO track_quarantine(track_id,guild_id,requested_by_user_id,reason,"
                "original_relative_path,quarantine_relative_path,state) "
                "VALUES(?,1,1,'past',?,'past/path','restored')",
                (track_id, path),
            )
            connection.execute(
                "INSERT INTO play_all_track_exceptions(guild_id,track_id,created_by_user_id) "
                "VALUES(1,?,1)",
                (track_id,),
            )
        connection.commit()
    return ids


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _tree(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def _audio_state(root: Path) -> dict[str, tuple[bytes, int, int]]:
    return {
        path.relative_to(root).as_posix(): (
            path.read_bytes(),
            path.stat().st_mode,
            path.stat().st_mtime_ns,
        )
        for path in root.rglob("*.mp3")
    }


def _track_rows(database: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(database) as connection:
        return connection.execute("SELECT * FROM tracks ORDER BY id").fetchall()


def _dependent_rows(database: Path) -> dict[str, list[tuple[object, ...]]]:
    tables = (
        "ratings",
        "track_volume_overrides",
        "playlist_items",
        "play_history",
        "track_quarantine",
        "play_all_track_exceptions",
    )
    with sqlite3.connect(database) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in tables
        }
