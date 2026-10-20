"""Strict loaders for manifests exchanged between Text processing stages.

The orchestrator treats a stage manifest as a completion capability, not as a
hint.  A later stage may resume only when the manifest has the expected schema
and kind, its inventory digest is reproducible, and its scientific settings
still match the current request.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from processing.text_analysis.contracts import TEXT_SCHEMA_VERSION, inventory_digest
from processing.text_analysis.transcribe.provenance import whisper_provenance_is_complete


@dataclass(frozen=True)
class ManifestContract:
    kind: str
    schemas: frozenset[str]
    records_key: str | None = None


TRANSCRIPTION = ManifestContract(
    "whisper-transcription-batch", frozenset({TEXT_SCHEMA_VERSION}), "videos"
)
SELECTION = ManifestContract(
    "text-language-selection", frozenset({TEXT_SCHEMA_VERSION}), "files"
)
PREPARE = ManifestContract(
    "whisper-to-rocksteady-prepare", frozenset({TEXT_SCHEMA_VERSION}), "videos"
)
ROCKSTEADY = ManifestContract(
    "rocksteady-analysis-batch", frozenset({"2.0"}), "videos"
)
DERIVED = ManifestContract(
    "derived-rocksteady-category-view", frozenset({TEXT_SCHEMA_VERSION}), "files"
)
POSTPROCESSING_PAIR = ManifestContract(
    "text-postprocessing-selected-extra-pair", frozenset({"1.0"})
)
POSTPROCESSING_VARIANT = ManifestContract(
    "text-postprocessing-variant", frozenset({"2.1"})
)


def read_completed_manifest(
    path: Path,
    label: str,
    contract: ManifestContract,
) -> dict[str, object]:
    """Read and verify one current-schema completed stage manifest."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label} manifest is missing: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} manifest is invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} manifest must contain a JSON object: {path}")
    if payload.get("status") != "completed":
        raise RuntimeError(f"{label} manifest is not completed: {path}")
    if payload.get("schema_version") not in contract.schemas:
        raise RuntimeError(
            f"{label} manifest has unsupported schema {payload.get('schema_version')!r}: {path}"
        )
    if payload.get("kind") != contract.kind:
        raise RuntimeError(
            f"{label} manifest has kind {payload.get('kind')!r}; expected {contract.kind!r}: {path}"
        )
    if contract.records_key is not None:
        _validate_inventory(payload, label, contract.records_key)
    return payload


def validate_transcription_settings(
    payload: Mapping[str, object],
    *,
    input_path: Path,
    output_root: Path,
    model: str,
    requested_device: str,
    requested_language: str | None = None,
) -> None:
    """Bind a resumed transcription inventory to the current Whisper request."""

    _require_same_path(payload.get("input_path"), input_path, "transcription input")
    _require_same_path(payload.get("output_root"), output_root, "transcription output")
    config = _require_mapping(payload.get("config"), "transcription config")
    expected = {"task": "bilingual", "model": model, "language": requested_language}
    for key, value in expected.items():
        if config.get(key) != value:
            raise RuntimeError(
                f"Transcription manifest {key}={config.get(key)!r} does not match {value!r}"
            )
    resolved_device = config.get("device")
    if resolved_device not in {"cpu", "cuda"}:
        raise RuntimeError("Transcription manifest has an invalid resolved device")
    if requested_device != "auto" and resolved_device != requested_device:
        raise RuntimeError(
            f"Transcription manifest device={resolved_device!r} does not match {requested_device!r}"
        )

    provenance = _require_mapping(payload.get("whisper_provenance"), "Whisper provenance")
    if set(provenance) != {"original", "eng", "bilingual"}:
        raise RuntimeError("Transcription manifest has an incomplete Whisper provenance set")
    for kind, value in provenance.items():
        if not whisper_provenance_is_complete(value):
            raise RuntimeError(f"Transcription manifest has incomplete {kind} Whisper provenance")
        assert isinstance(value, Mapping)
        checkpoint = value.get("checkpoint")
        if not isinstance(checkpoint, Mapping) or checkpoint.get("requested_name") != model:
            raise RuntimeError(
                f"Transcription {kind} checkpoint does not match Whisper model {model!r}"
            )


def validate_selection_settings(
    payload: Mapping[str, object],
    *,
    input_path: Path,
    default_variant: str,
    language_policy: Mapping[str, str],
) -> None:
    _require_same_path(payload.get("input_path"), input_path, "selection input")
    if payload.get("default_variant") != default_variant:
        raise RuntimeError("Selection manifest default language variant does not match current config")
    saved_policy = payload.get("language_policy")
    if not isinstance(saved_policy, dict) or saved_policy != dict(language_policy):
        raise RuntimeError("Selection manifest language policy does not match current config")


def validate_prepare_settings(
    payload: Mapping[str, object],
    *,
    input_root: Path,
    output_root: Path,
) -> None:
    _require_same_path(payload.get("input_root"), input_root, "prepare input")
    _require_same_path(payload.get("output_root"), output_root, "prepare output")
    if payload.get("language") != "original":
        raise RuntimeError("Prepare manifest must extract the already-selected original text field")


def validate_derived_settings(
    payload: Mapping[str, object],
    *,
    source_root: Path,
    categories: Sequence[str],
) -> None:
    _require_same_path(payload.get("source_root"), source_root, "derived-view source")
    if payload.get("categories") != list(categories):
        raise RuntimeError("Derived-view categories do not match the stable core category contract")


def _validate_inventory(payload: Mapping[str, object], label: str, key: str) -> None:
    records = payload.get(key)
    if not isinstance(records, list) or not records:
        raise RuntimeError(f"{label} manifest has no {key} inventory")
    if any(not isinstance(record, dict) for record in records):
        raise RuntimeError(f"{label} manifest contains a malformed {key} inventory row")
    bad_statuses = [record.get("status") for record in records if record.get("status") not in {"completed", "skipped"}]
    if bad_statuses:
        raise RuntimeError(f"{label} completed manifest contains incomplete inventory rows")
    stored_digest = payload.get("inventory_sha256")
    actual_digest = inventory_digest(records)
    if stored_digest != actual_digest:
        raise RuntimeError(f"{label} manifest inventory digest does not match its records")

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError(f"{label} manifest has no summary contract")
    expected_counts = {
        "total": len(records),
        "completed": sum(record.get("status") == "completed" for record in records),
        "failed": 0,
    }
    if "skipped" in summary:
        expected_counts["skipped"] = sum(record.get("status") == "skipped" for record in records)
    for name, value in expected_counts.items():
        if summary.get(name) != value:
            raise RuntimeError(
                f"{label} manifest summary {name}={summary.get(name)!r}; expected {value}"
            )


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _require_same_path(value: object, expected: Path, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label} path is missing")
    if Path(value).expanduser().resolve() != Path(expected).expanduser().resolve():
        raise RuntimeError(f"{label} path does not match the current Text config")
