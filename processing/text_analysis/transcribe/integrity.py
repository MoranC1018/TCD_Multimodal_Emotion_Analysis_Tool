"""Strict integrity checks for persisted Whisper artifacts.

These checks are intentionally independent from model execution.  A caller can
therefore decide whether a completed transcription batch is reusable without
loading Whisper or a model checkpoint.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from processing.text_analysis.contracts import TEXT_SCHEMA_VERSION, file_sha256
from processing.text_analysis.transcribe.provenance import (
    whisper_provenance_is_complete,
    whisper_provenance_matches,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TASK_BY_KIND = {
    "original": "transcribe",
    "eng": "translate",
    "bilingual": "bilingual",
    "transcribe": "transcribe",
    "translate": "translate",
}


def transcript_segments_are_valid(payload: object, expected_task: str) -> bool:
    """Return whether a transcript has ordered, uniquely identified segments."""

    if not isinstance(payload, dict):
        return False
    segments = payload.get("segments")
    if not isinstance(segments, list):
        return False
    identifiers: list[object] = []
    previous_start = -1.0
    for segment in segments:
        if not isinstance(segment, dict):
            return False
        try:
            start, end = float(segment["start"]), float(segment["end"])
        except (KeyError, TypeError, ValueError):
            return False
        if start < 0 or end <= start or start < previous_start:
            return False
        previous_start = start
        required_text = (
            ("text_original", "text_en")
            if expected_task == "bilingual"
            else ("text",)
        )
        if any(not isinstance(segment.get(key), str) for key in required_text):
            return False
        if expected_task == "bilingual" and any(
            not str(segment[key]).strip() for key in required_text
        ):
            return False
        identifier = segment.get("id")
        if identifier is not None and not isinstance(
            identifier, (str, int, float, bool)
        ):
            return False
        identifiers.append(identifier)
    try:
        return len(identifiers) == len(set(identifiers))
    except TypeError:
        return False


def validate_transcription_artifact(
    path: Path,
    *,
    expected_task: str,
    expected_model: str,
    expected_source_sha256: str,
    expected_provenance: object,
    expected_artifact_sha256: str | None = None,
) -> dict[str, Any]:
    """Load one current-schema artifact and validate every reuse identity."""

    artifact = Path(path)
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read Whisper artifact {artifact}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Whisper artifact root is not an object: {artifact}")
    if payload.get("schema_version") != TEXT_SCHEMA_VERSION:
        raise ValueError(f"Whisper artifact has an unsupported schema: {artifact}")
    if payload.get("task") != expected_task:
        raise ValueError(
            f"Whisper artifact task mismatch at {artifact}: "
            f"expected {expected_task!r}, got {payload.get('task')!r}"
        )
    if payload.get("model") != expected_model:
        raise ValueError(
            f"Whisper artifact model mismatch at {artifact}: "
            f"expected {expected_model!r}, got {payload.get('model')!r}"
        )
    expected_source = str(expected_source_sha256).casefold()
    if not _SHA256_RE.fullmatch(expected_source):
        raise ValueError("Expected media SHA-256 must contain 64 lowercase hex digits")
    saved_source = payload.get("source_sha256")
    if not isinstance(saved_source, str) or saved_source.casefold() != expected_source:
        raise ValueError(f"Whisper artifact media hash mismatch: {artifact}")
    if not whisper_provenance_is_complete(expected_provenance):
        raise ValueError("Expected Whisper provenance is incomplete")
    if not whisper_provenance_matches(
        payload.get("whisper_provenance"), expected_provenance
    ):
        raise ValueError(f"Whisper artifact provenance mismatch: {artifact}")
    if not transcript_segments_are_valid(payload, expected_task):
        raise ValueError(f"Whisper artifact contains invalid segments: {artifact}")
    if expected_artifact_sha256 is not None:
        expected_artifact = str(expected_artifact_sha256).casefold()
        if not _SHA256_RE.fullmatch(expected_artifact):
            raise ValueError(f"Invalid expected artifact SHA-256 for {artifact}")
        if file_sha256(artifact) != expected_artifact:
            raise ValueError(f"Whisper artifact content hash mismatch: {artifact}")
    return payload


def validate_transcription_artifact_set(
    paths: Mapping[str, Path],
    *,
    expected_model: str,
    expected_source_sha256: str,
    expected_provenance_by_kind: Mapping[str, object],
    expected_artifact_sha256_by_kind: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Validate an exact one-pass or original/English/bilingual artifact set.

    The keys in ``paths`` and ``expected_provenance_by_kind`` must match
    exactly.  This prevents a bilingual run from being considered complete
    when only one or two of its three companion files remain.
    """

    path_keys = set(paths)
    provenance_keys = set(expected_provenance_by_kind)
    if path_keys != provenance_keys:
        raise ValueError(
            "Whisper artifact/provenance kinds differ: "
            f"artifacts={sorted(path_keys)}, provenance={sorted(provenance_keys)}"
        )
    if path_keys == {"original", "eng", "bilingual"}:
        pass
    elif len(path_keys) != 1 or next(iter(path_keys), None) not in {
        "transcribe",
        "translate",
    }:
        raise ValueError(f"Unsupported Whisper artifact set: {sorted(path_keys)}")
    artifact_hashes = expected_artifact_sha256_by_kind or {}
    unknown_hashes = set(artifact_hashes) - path_keys
    if unknown_hashes:
        raise ValueError(
            f"Artifact hashes contain unknown Whisper kinds: {sorted(unknown_hashes)}"
        )

    validated: dict[str, dict[str, Any]] = {}
    for kind in sorted(path_keys):
        validated[kind] = validate_transcription_artifact(
            paths[kind],
            expected_task=_TASK_BY_KIND[kind],
            expected_model=expected_model,
            expected_source_sha256=expected_source_sha256,
            expected_provenance=expected_provenance_by_kind[kind],
            expected_artifact_sha256=artifact_hashes.get(kind),
        )
    return validated
