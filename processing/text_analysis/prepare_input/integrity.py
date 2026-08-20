"""Integrity contracts for Whisper-to-RockSteady prepared segment trees."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from processing.text_analysis.contracts import (
    TEXT_SCHEMA_VERSION,
    file_sha256,
    inventory_digest,
    validate_text_identity,
)


PREPARE_MANIFEST = ".prepare_manifest.json"
_TEXT_OWNER_FILE = ".text_pipeline_owner.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SEGMENT_SUFFIX_RE = re.compile(r"__segment_(\d{6})\.txt$", re.IGNORECASE)


def prepared_content_sha256(
    entries: Sequence[tuple[str, str, Mapping[str, object]]],
) -> str:
    """Hash filenames, exact text, and source mappings in publication order."""

    digest = hashlib.sha256()
    for name, text, mapping in entries:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(text.encode("utf-8"))
        digest.update(b"\0")
        digest.update(json.dumps(dict(mapping), sort_keys=True).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def validate_prepared_video_tree(
    video_dir: Path,
    *,
    expected_identity: str | None = None,
    expected_source_sha256: str | None = None,
    expected_selection_source_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate contiguous segment files, source mapping, and content digest."""

    root = Path(video_dir).resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"Prepared video artifact is not a safe directory: {root}")
    manifest_path = root / PREPARE_MANIFEST
    if manifest_path.is_symlink():
        raise ValueError(f"Prepared video manifest must not be a symlink: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Prepared video has no valid {PREPARE_MANIFEST}: {root}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"Prepared video manifest is not an object: {manifest_path}")
    if manifest.get("schema_version") != TEXT_SCHEMA_VERSION:
        raise ValueError(f"Prepared video schema is unsupported: {manifest_path}")

    identity = manifest.get("video_identity")
    if not isinstance(identity, str) or not identity:
        raise ValueError(f"Prepared video manifest has no identity: {manifest_path}")
    if expected_identity is not None and identity != expected_identity:
        raise ValueError(
            f"Prepared video identity mismatch: expected {expected_identity!r}, got {identity!r}"
        )
    if len(Path(identity).parts) in {2, 3}:
        validate_text_identity(Path(identity))

    count = manifest.get("segment_count")
    mappings = manifest.get("segments")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError(f"Prepared segment_count must be a positive integer: {manifest_path}")
    if not isinstance(mappings, list) or len(mappings) != count:
        raise ValueError(f"Prepared segment mapping count is inconsistent: {manifest_path}")

    files = sorted(root.glob("*.txt"), key=lambda path: path.name.casefold())
    expected_names = [
        f"{root.name}__segment_{index:06d}.txt" for index in range(1, count + 1)
    ]
    if [path.name for path in files] != expected_names:
        raise ValueError(f"Prepared segments are not contiguous for {identity}")
    allowed_entries = {*expected_names, PREPARE_MANIFEST, _TEXT_OWNER_FILE}
    unexpected_entries = [
        path.name for path in root.iterdir() if path.name not in allowed_entries
    ]
    if unexpected_entries:
        raise ValueError(
            f"Prepared video contains unexpected entries for {identity}: "
            f"{', '.join(unexpected_entries)}"
        )

    entries: list[tuple[str, str, Mapping[str, object]]] = []
    previous_source_index = -1
    for index, (path, raw_mapping) in enumerate(zip(files, mappings), start=1):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Prepared segment is not a regular file: {path}")
        if not isinstance(raw_mapping, dict):
            raise ValueError(f"Prepared source mapping {index} is not an object: {manifest_path}")
        if raw_mapping.get("analysis_segment_id") != index:
            raise ValueError(f"Prepared analysis segment IDs are not contiguous: {manifest_path}")
        source_index = raw_mapping.get("source_segment_index")
        if (
            not isinstance(source_index, int)
            or isinstance(source_index, bool)
            or source_index <= previous_source_index
        ):
            raise ValueError(f"Prepared source segment indexes are not increasing: {manifest_path}")
        previous_source_index = source_index
        source_id = raw_mapping.get("source_segment_id")
        if source_id is not None and not isinstance(source_id, (str, int, float, bool)):
            raise ValueError(f"Prepared source segment ID is not scalar: {manifest_path}")
        if set(raw_mapping) != {
            "analysis_segment_id",
            "source_segment_index",
            "source_segment_id",
        }:
            raise ValueError(f"Prepared source mapping fields are invalid: {manifest_path}")
        if _SEGMENT_SUFFIX_RE.search(path.name) is None:
            raise ValueError(f"Prepared segment filename is invalid: {path}")
        text = path.read_text(encoding="utf-8")
        if not text or text != text.strip():
            raise ValueError(f"Prepared segment text is empty or not normalized: {path}")
        entries.append((path.name, text, raw_mapping))

    calculated = prepared_content_sha256(entries)
    if manifest.get("content_sha256") != calculated:
        raise ValueError(f"Prepared segment content hash mismatch: {root}")

    _validate_optional_hash(
        manifest,
        "source_sha256",
        expected_source_sha256,
        manifest_path,
    )
    _validate_optional_hash(
        manifest,
        "selection_source_sha256",
        expected_selection_source_sha256,
        manifest_path,
    )
    return manifest


def validate_prepare_batch_artifacts(
    output_root: Path,
    batch_manifest_path: Path,
    *,
    selection_manifest_path: Path | None = None,
) -> tuple[set[str], str]:
    """Validate a completed prepare inventory and every referenced video tree."""

    root = Path(output_root).resolve()
    manifest_path = Path(batch_manifest_path).resolve()
    payload = _read_object(manifest_path, "prepare batch manifest")
    if payload.get("schema_version") != TEXT_SCHEMA_VERSION:
        raise ValueError(f"Prepare inventory schema is unsupported: {manifest_path}")
    if payload.get("kind") != "whisper-to-rocksteady-prepare":
        raise ValueError(f"Unexpected prepare inventory kind: {manifest_path}")
    if payload.get("status") != "completed":
        raise ValueError(f"Prepare inventory is not completed: {manifest_path}")
    records = payload.get("videos")
    if not isinstance(records, list) or not records:
        raise ValueError(f"Prepare inventory has no completed videos: {manifest_path}")
    if payload.get("inventory_sha256") != inventory_digest(records):
        raise ValueError(f"Prepare inventory digest mismatch: {manifest_path}")

    selection_items: dict[str, dict[str, object]] | None = None
    if selection_manifest_path is not None:
        selection = _read_object(Path(selection_manifest_path), "selection manifest")
        if selection.get("status") != "completed" or not isinstance(selection.get("files"), list):
            raise ValueError(f"Selection inventory is not completed: {selection_manifest_path}")
        if selection.get("inventory_sha256") != inventory_digest(selection["files"]):
            raise ValueError(f"Selection inventory digest mismatch: {selection_manifest_path}")
        selection_items = {}
        for raw in selection["files"]:
            if not isinstance(raw, dict) or not isinstance(raw.get("identity"), str):
                raise ValueError(f"Malformed selection inventory item: {selection_manifest_path}")
            identity = validate_text_identity(Path(raw["identity"])).as_posix()
            if identity in selection_items:
                raise ValueError(f"Duplicate selection identity: {identity}")
            selection_items[identity] = raw

    identities: set[str] = set()
    for raw in records:
        if not isinstance(raw, dict) or raw.get("status") != "completed":
            raise ValueError(f"Prepare inventory contains an incomplete video: {manifest_path}")
        raw_identity = raw.get("identity")
        if not isinstance(raw_identity, str):
            raise ValueError(f"Prepare inventory contains an invalid identity: {raw_identity!r}")
        identity = validate_text_identity(Path(raw_identity)).as_posix()
        if identity in identities:
            raise ValueError(f"Prepare inventory contains duplicate identity: {identity}")
        identities.add(identity)
        artifact = Path(str(raw.get("artifact", identity)))
        if artifact.is_absolute() or ".." in artifact.parts or artifact.as_posix() != identity:
            raise ValueError(f"Prepare artifact path does not match identity {identity}: {artifact}")
        source_hash = raw.get("source_sha256")
        selection_hash = raw.get("selection_source_sha256")
        if not isinstance(source_hash, str) or not _SHA256_RE.fullmatch(source_hash.casefold()):
            raise ValueError(f"Prepare source hash is invalid for {identity}")
        if selection_hash is not None and selection_hash != source_hash:
            raise ValueError(f"Prepare/selection source hash mismatch for {identity}")
        if selection_items is not None:
            selected = selection_items.get(identity)
            if selected is None:
                raise ValueError(f"Prepare identity is absent from selection inventory: {identity}")
            expected_selection_hash = selected.get("source_sha256")
            if not isinstance(expected_selection_hash, str):
                raise ValueError(f"Selection source hash is missing for {identity}")
            if selection_hash != expected_selection_hash or source_hash != expected_selection_hash:
                raise ValueError(f"Prepare/selection source hash mismatch for {identity}")
        prepared_manifest = validate_prepared_video_tree(
            root / artifact,
            expected_identity=identity,
            expected_source_sha256=source_hash,
            expected_selection_source_sha256=(
                str(selection_hash) if selection_hash is not None else None
            ),
        )
        if raw.get("prepared_content_sha256") != prepared_manifest.get("content_sha256"):
            raise ValueError(f"Prepare batch/video content hash mismatch for {identity}")
        prepare_manifest_hash = raw.get("prepare_manifest_sha256")
        if (
            not isinstance(prepare_manifest_hash, str)
            or file_sha256(root / artifact / PREPARE_MANIFEST) != prepare_manifest_hash
        ):
            raise ValueError(f"Prepare per-video manifest hash mismatch for {identity}")
        source_path = raw.get("source_path")
        if not isinstance(source_path, str) or not Path(source_path).is_file():
            raise ValueError(f"Selected Whisper source is missing after prepare: {source_path}")
        if file_sha256(Path(source_path)) != source_hash:
            raise ValueError(f"Selected Whisper source changed after prepare: {source_path}")

    if selection_items is not None and set(selection_items) != identities:
        raise ValueError("Prepare and selection inventories contain different identity sets")
    digest = payload.get("inventory_sha256")
    assert isinstance(digest, str)
    return identities, digest


def _validate_optional_hash(
    manifest: Mapping[str, object],
    key: str,
    expected: str | None,
    manifest_path: Path,
) -> None:
    actual = manifest.get(key)
    if actual is not None and (
        not isinstance(actual, str) or not _SHA256_RE.fullmatch(actual.casefold())
    ):
        raise ValueError(f"Prepared {key} is invalid: {manifest_path}")
    if expected is not None:
        normalized = str(expected).casefold()
        if not _SHA256_RE.fullmatch(normalized) or actual != normalized:
            raise ValueError(f"Prepared {key} mismatch: {manifest_path}")


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label.capitalize()} is not an object: {path}")
    return value
