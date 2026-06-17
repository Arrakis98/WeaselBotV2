from __future__ import annotations

import json
from pathlib import Path

from weasel_bot_v2.services.arcadia_manifest import load_arcadia_manifest


def test_arcadia_report_family_is_cross_checked(tmp_path: Path) -> None:
    operation = {
        "relative_path": "Artist/interview.mp3",
        "source_sha256": "a" * 64,
        "reasons": ["non_music"],
        "confidence": 1.0,
        "reference_file": "",
    }
    manifest_path, validation_path = _write_reports(tmp_path, operation)
    loaded = load_arcadia_manifest(manifest_path, validation_path)
    assert len(loaded.operations) == 1
    assert loaded.operations[0].relative_path == "Artist/interview.mp3"
    assert loaded.operations[0].reason == "non_music"


def _write_reports(
    tmp_path: Path,
    operation: dict[str, object],
) -> tuple[Path, Path]:
    manifest = {
        "schema_version": 2,
        "kind": "arcadia_quarantine_manifest",
        "manifest_version": 2,
        "generated_at": "2026-06-17T02:44:11.391265+00:00",
        "dry_run": True,
        "duplicate_threshold": 0.9,
        "reference_policy": "canonical_originality_first",
        "operation_count": 1,
        "reason_counts": {"non_music": 1},
        "operations": [operation],
    }
    validation = {
        "schema_version": 1,
        "validation_version": 1,
        "generated_at": "2026-06-17T02:44:11.392144+00:00",
        "overall_status": "pass",
        "summary": {
            "quarantine_operations": 1,
            "quarantine_reason_counts": {"non_music": 1},
            "safe_duplicate_copies": 0,
            "non_music_candidates": 1,
            "checks_failed": 0,
            "checks_warning": 0,
        },
        "checks": [{"id": "all", "status": "pass"}],
        "quarantine_verification": {
            "operation_count": 1,
            "safe_duplicate_copies": 0,
            "blocked_duplicates": 0,
            "non_music_candidates": 1,
            "results": [
                {
                    "relative_path": operation["relative_path"],
                    "reasons": ["non_music"],
                    "reference_file": None,
                    "reference_active": False,
                    "safe_to_remove_quarantine_copy": False,
                    "verdict": "non_music_candidate",
                }
            ],
        },
    }
    manifest_path = tmp_path / "manifest.json"
    validation_path = tmp_path / "validation.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    validation_path.write_text(json.dumps(validation), encoding="utf-8")
    return manifest_path, validation_path
