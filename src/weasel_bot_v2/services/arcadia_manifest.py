from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from weasel_bot_v2.services.local_library import safe_relative_path

_ALLOWED_REASONS = {"duplicate_high_confidence", "non_music"}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ArcadiaManifestError(ValueError):
    """Raised when an Arcadia quarantine report family is unsafe to use."""


@dataclass(frozen=True)
class ArcadiaManifestOperation:
    relative_path: str
    source_sha256: str
    reasons: tuple[str, ...]
    confidence: float
    reference_file: str | None

    @property
    def reason(self) -> str:
        return self.reasons[0]


@dataclass(frozen=True)
class LoadedArcadiaManifest:
    digest: str
    generated_at: str
    duplicate_threshold: float
    operations: tuple[ArcadiaManifestOperation, ...]


def load_arcadia_manifest(
    manifest_path: Path,
    validation_path: Path,
) -> LoadedArcadiaManifest:
    manifest_bytes = _read_bytes(manifest_path, "quarantine manifest")
    validation_bytes = _read_bytes(validation_path, "project validation")
    manifest = _json_mapping(manifest_bytes, "quarantine manifest")
    validation = _json_mapping(validation_bytes, "project validation")
    return _validate_report_family(
        manifest,
        validation,
        hashlib.sha256(manifest_bytes).hexdigest(),
    )


def _validate_report_family(
    manifest: Mapping[str, Any],
    validation: Mapping[str, Any],
    digest: str,
) -> LoadedArcadiaManifest:
    if manifest.get("kind") != "arcadia_quarantine_manifest":
        raise ArcadiaManifestError("Unsupported quarantine manifest kind.")
    if manifest.get("schema_version") != 2 or manifest.get("manifest_version") != 2:
        raise ArcadiaManifestError("Unsupported quarantine manifest version.")
    if manifest.get("dry_run") is not True:
        raise ArcadiaManifestError("The quarantine manifest must be a reviewed dry run.")
    if manifest.get("reference_policy") != "canonical_originality_first":
        raise ArcadiaManifestError("Unsupported canonical reference policy.")

    if validation.get("schema_version") != 1 or validation.get("validation_version") != 1:
        raise ArcadiaManifestError("Unsupported project validation version.")
    if validation.get("overall_status") != "pass":
        raise ArcadiaManifestError("Project validation did not pass.")

    checks = validation.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ArcadiaManifestError("Project validation checks are missing.")
    if any(
        not isinstance(check, Mapping) or check.get("status") != "pass"
        for check in checks
    ):
        raise ArcadiaManifestError("Every project validation check must pass.")

    summary = _mapping(validation.get("summary"), "validation summary")
    if _integer(summary.get("checks_failed"), "checks_failed") != 0:
        raise ArcadiaManifestError("Project validation contains failed checks.")
    if _integer(summary.get("checks_warning"), "checks_warning") != 0:
        raise ArcadiaManifestError("Project validation contains warnings.")

    generated_at = _timestamp(manifest.get("generated_at"), "manifest generated_at")
    validation_generated_at = _timestamp(
        validation.get("generated_at"),
        "validation generated_at",
    )
    if _parse_timestamp(validation_generated_at) < _parse_timestamp(generated_at):
        raise ArcadiaManifestError("Project validation predates the quarantine manifest.")

    threshold = _number(manifest.get("duplicate_threshold"), "duplicate_threshold")
    if not 0.9 <= threshold <= 1.0:
        raise ArcadiaManifestError("Duplicate threshold must be between 0.90 and 1.00.")

    raw_operations = manifest.get("operations")
    if not isinstance(raw_operations, list):
        raise ArcadiaManifestError("Quarantine operations must be a list.")
    operations = tuple(_operation(value, threshold) for value in raw_operations)

    if _integer(manifest.get("operation_count"), "operation_count") != len(operations):
        raise ArcadiaManifestError("Manifest operation count is inconsistent.")
    if _integer(summary.get("quarantine_operations"), "quarantine_operations") != len(
        operations
    ):
        raise ArcadiaManifestError("Validation operation count is inconsistent.")

    paths = [operation.relative_path for operation in operations]
    if len(paths) != len(set(paths)):
        raise ArcadiaManifestError("Manifest contains duplicate source paths.")
    selected_paths = set(paths)
    if any(operation.reference_file in selected_paths for operation in operations):
        raise ArcadiaManifestError("A duplicate reference is selected for quarantine.")

    computed_counts = dict(Counter(operation.reason for operation in operations))
    manifest_counts = _count_mapping(manifest.get("reason_counts"), "manifest reason counts")
    validation_counts = _count_mapping(
        summary.get("quarantine_reason_counts"),
        "validation reason counts",
    )
    if computed_counts != manifest_counts or computed_counts != validation_counts:
        raise ArcadiaManifestError("Quarantine reason counts are inconsistent.")

    verification = _mapping(
        validation.get("quarantine_verification"),
        "quarantine verification",
    )
    if _integer(verification.get("operation_count"), "verification operation_count") != len(
        operations
    ):
        raise ArcadiaManifestError("Quarantine verification count is inconsistent.")
    if _integer(verification.get("blocked_duplicates"), "blocked_duplicates") != 0:
        raise ArcadiaManifestError("Validation reports blocked duplicate operations.")

    results = verification.get("results")
    if not isinstance(results, list):
        raise ArcadiaManifestError("Quarantine verification results are missing.")
    result_map = _verification_results(results)
    if set(result_map) != selected_paths:
        raise ArcadiaManifestError("Verification paths do not match the manifest.")

    duplicate_count = computed_counts.get("duplicate_high_confidence", 0)
    non_music_count = computed_counts.get("non_music", 0)
    if _integer(verification.get("safe_duplicate_copies"), "safe_duplicate_copies") != (
        duplicate_count
    ):
        raise ArcadiaManifestError("Safe duplicate count is inconsistent.")
    if _integer(verification.get("non_music_candidates"), "non_music_candidates") != (
        non_music_count
    ):
        raise ArcadiaManifestError("Non-music count is inconsistent.")
    if _integer(summary.get("safe_duplicate_copies"), "summary safe_duplicate_copies") != (
        duplicate_count
    ):
        raise ArcadiaManifestError("Validation summary duplicate count is inconsistent.")
    if _integer(summary.get("non_music_candidates"), "summary non_music_candidates") != (
        non_music_count
    ):
        raise ArcadiaManifestError("Validation summary non-music count is inconsistent.")

    for operation in operations:
        _validate_verification_result(operation, result_map[operation.relative_path])

    return LoadedArcadiaManifest(
        digest=digest,
        generated_at=generated_at,
        duplicate_threshold=threshold,
        operations=operations,
    )


def _verification_results(results: list[object]) -> dict[str, Mapping[str, Any]]:
    mapped: dict[str, Mapping[str, Any]] = {}
    for value in results:
        result = _mapping(value, "quarantine verification result")
        path = _safe_path(_text(result.get("relative_path"), "verification relative_path"))
        if path in mapped:
            raise ArcadiaManifestError("Verification contains duplicate paths.")
        mapped[path] = result
    return mapped


def _validate_verification_result(
    operation: ArcadiaManifestOperation,
    result: Mapping[str, Any],
) -> None:
    reasons = result.get("reasons")
    if not isinstance(reasons, list) or tuple(str(value) for value in reasons) != operation.reasons:
        raise ArcadiaManifestError("Verification reasons do not match the manifest.")
    if operation.reason == "duplicate_high_confidence":
        if result.get("verdict") != "safe_duplicate_copy":
            raise ArcadiaManifestError("A duplicate is not verified as safe.")
        if result.get("safe_to_remove_quarantine_copy") is not True:
            raise ArcadiaManifestError("A duplicate is not safe to quarantine.")
        if result.get("reference_active") is not True:
            raise ArcadiaManifestError("A duplicate reference is not active.")
        if str(result.get("reference_file") or "") != operation.reference_file:
            raise ArcadiaManifestError("Duplicate reference paths are inconsistent.")
    elif result.get("verdict") != "non_music_candidate":
        raise ArcadiaManifestError("A non-music operation has an unexpected verdict.")


def _operation(value: object, threshold: float) -> ArcadiaManifestOperation:
    raw = _mapping(value, "quarantine operation")
    relative_path = _safe_path(_text(raw.get("relative_path"), "relative_path"))
    source_sha256 = _text(raw.get("source_sha256"), "source_sha256").casefold()
    if _SHA256_PATTERN.fullmatch(source_sha256) is None:
        raise ArcadiaManifestError("Every operation requires a valid SHA-256 digest.")

    raw_reasons = raw.get("reasons")
    if not isinstance(raw_reasons, list) or len(raw_reasons) != 1:
        raise ArcadiaManifestError("Every operation requires exactly one reason.")
    reasons = tuple(str(reason) for reason in raw_reasons)
    if reasons[0] not in _ALLOWED_REASONS:
        raise ArcadiaManifestError("An operation contains an unsupported reason.")

    confidence = _number(raw.get("confidence"), "confidence")
    if not 0.0 <= confidence <= 1.0:
        raise ArcadiaManifestError("Operation confidence must be between 0 and 1.")

    raw_reference = str(raw.get("reference_file") or "").strip()
    reference_file = _safe_path(raw_reference) if raw_reference else None
    if reasons[0] == "duplicate_high_confidence":
        if reference_file is None:
            raise ArcadiaManifestError("Every duplicate requires a reference file.")
        if reference_file == relative_path:
            raise ArcadiaManifestError("A duplicate cannot reference itself.")
        if confidence < threshold:
            raise ArcadiaManifestError("A duplicate is below the manifest threshold.")

    return ArcadiaManifestOperation(
        relative_path=relative_path,
        source_sha256=source_sha256,
        reasons=reasons,
        confidence=confidence,
        reference_file=reference_file,
    )


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ArcadiaManifestError(f"Configured {label} file is unavailable.") from exc


def _json_mapping(data: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArcadiaManifestError(f"Configured {label} is not valid UTF-8 JSON.") from exc
    return _mapping(value, label)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ArcadiaManifestError(f"{label.capitalize()} must be a JSON object.")
    return value


def _count_mapping(value: object, label: str) -> dict[str, int]:
    raw = _mapping(value, label)
    return {str(key): _integer(count, f"{label}.{key}") for key, count in raw.items()}


def _safe_path(value: str) -> str:
    try:
        return safe_relative_path(value).as_posix()
    except ValueError as exc:
        raise ArcadiaManifestError("Manifest contains an unsafe relative path.") from exc


def _text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ArcadiaManifestError(f"{label} is required.")
    return text


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ArcadiaManifestError(f"{label} must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ArcadiaManifestError(f"{label} must be an integer.") from exc


def _number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ArcadiaManifestError(f"{label} must be a number.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ArcadiaManifestError(f"{label} must be a number.") from exc


def _timestamp(value: object, label: str) -> str:
    timestamp = _text(value, label)
    _parse_timestamp(timestamp)
    return timestamp


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArcadiaManifestError("Report timestamps must use ISO-8601.") from exc
    if parsed.tzinfo is None:
        raise ArcadiaManifestError("Report timestamps must include a timezone.")
    return parsed
