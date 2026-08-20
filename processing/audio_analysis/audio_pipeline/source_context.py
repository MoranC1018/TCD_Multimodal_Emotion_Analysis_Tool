from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from procurement.input_limits import count_json_items, read_control_json


# Catalog DOCX input permits 128 MiB of expanded XML and CSV permits 100,000
# rows. JSON/CSV sidecars add core identity fields and quoting overhead, so the
# propagation ceilings deliberately cover that producer envelope while staying
# finite for untrusted reused output roots.
MAX_SOURCE_CONTEXT_BYTES = 256 * 1024 * 1024
MAX_SOURCE_CONTEXT_ITEMS = 50_000
MAX_SOURCE_MANIFEST_BYTES = 512 * 1024 * 1024
MAX_SOURCE_MANIFEST_ITEMS = 10_000_000
MAX_SOURCE_METADATA_BYTES = 384 * 1024 * 1024
SOURCE_ID_PATTERN = re.compile(r"source-\d{4,6}")
RUN_SIDECAR_NAMES = ("source_manifest.json", "source_metadata.csv")


def load_source_context(input_video: Path, *, boundary: Path | None = None) -> dict[str, object]:
    """Load the nearest bounded catalog context without crossing the input/run root."""

    video = input_video.expanduser().resolve(strict=True)
    root = _context_boundary(video, boundary)
    if video != root and root not in video.parents:
        raise ValueError(f"Audio input is outside the source-context boundary: {video}")

    directory = video.parent
    while directory == root or root in directory.parents:
        candidate = directory / "source_context.json"
        if candidate.is_symlink():
            raise ValueError(f"Source context must not be a symlink: {candidate}")
        if candidate.exists():
            resolved = candidate.resolve(strict=True)
            if resolved != root and root not in resolved.parents:
                raise ValueError(f"Source context escapes the input boundary: {candidate}")
            payload = read_control_json(
                resolved,
                label="source context",
                max_bytes=MAX_SOURCE_CONTEXT_BYTES,
                max_items=MAX_SOURCE_CONTEXT_ITEMS,
            )
            context = validate_source_context(payload, path=resolved)
            if boundary is None:
                _validate_single_file_context_ownership(video, context)
            return context
        if directory == root:
            break
        directory = directory.parent
    return {}


def _context_boundary(video: Path, boundary: Path | None) -> Path:
    if boundary is not None:
        return boundary.expanduser().resolve(strict=True)
    return video.parent


def _validate_single_file_context_ownership(
    video: Path,
    context: Mapping[str, object],
) -> None:
    raw_run_root = context.get("run_root")
    if not isinstance(raw_run_root, str) or not raw_run_root.strip():
        raise ValueError(f"Source context has no explicit catalog run root: {video}")
    run_root = Path(raw_run_root).expanduser().resolve(strict=True)
    if not run_root.is_dir() or (video != run_root and run_root not in video.parents):
        raise ValueError(f"Source context catalog run root does not own the audio input: {video}")
    pair = _find_run_sidecars(
        run_root,
        expected_source_ids={str(context.get("source_id") or "")},
        source_bindings=[(video, context)],
    )
    if pair is None:
        raise ValueError(f"Catalog source context has no immutable sidecar pair at its run root: {run_root}")


def validate_source_context(payload: object, *, path: Path) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError(f"Source context must be a JSON object: {path}")
    source_id = str(payload.get("source_id") or "")
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise ValueError(f"Source context has an invalid SourceID: {path}")
    for field in (
        "speaker",
        "speaker_display",
        "source_kind",
        "resolved_link",
        "catalog_sha256",
    ):
        if not isinstance(payload.get(field, ""), str):
            raise ValueError(f"Source context field {field} must be text: {path}")
    user_metadata = payload.get("user_metadata", {})
    if not isinstance(user_metadata, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in user_metadata.items()
    ):
        raise ValueError(f"Source context user_metadata must contain text labels and values: {path}")
    if not isinstance(payload.get("system_metadata", {}), dict):
        raise ValueError(f"Source context system_metadata must be an object: {path}")
    if payload.get("source_kind") == "local":
        identity = payload.get("local_identity")
        if not isinstance(identity, dict):
            raise ValueError(f"Local source context has no immutable media identity: {path}")
        canonical_path = identity.get("canonical_path")
        digest = identity.get("sha256")
        size = identity.get("size_bytes")
        if (
            not isinstance(canonical_path, str)
            or not canonical_path
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise ValueError(f"Local source context has an invalid immutable media identity: {path}")
    return dict(payload)


def copy_run_sidecars(
    input_path: Path,
    output_root: Path,
    *,
    expected_source_ids: set[str] | None = None,
    source_bindings: Sequence[tuple[Path, Mapping[str, object]]] | None = None,
    require_mapped_input_paths: bool = True,
    expected_catalog_sha256: str = "",
) -> bool:
    """Copy the nearest immutable run-sidecar pair without rewriting its bytes."""

    pair = snapshot_run_sidecars(
        input_path,
        expected_source_ids=expected_source_ids,
        source_bindings=source_bindings,
        require_mapped_input_paths=require_mapped_input_paths,
        expected_catalog_sha256=expected_catalog_sha256,
    )
    if pair is None:
        return False
    publish_run_sidecars(output_root, pair)
    return True


def snapshot_run_sidecars(
    input_path: Path,
    *,
    expected_source_ids: set[str] | None = None,
    source_bindings: Sequence[tuple[Path, Mapping[str, object]]] | None = None,
    require_mapped_input_paths: bool = True,
    expected_catalog_sha256: str = "",
) -> tuple[bytes, bytes] | None:
    """Return one exact bounded source-sidecar pair after validating its bindings."""

    return _find_run_sidecars(
        input_path,
        expected_source_ids=expected_source_ids,
        source_bindings=source_bindings,
        require_mapped_input_paths=require_mapped_input_paths,
        expected_catalog_sha256=expected_catalog_sha256,
    )


def publish_run_sidecars(output_root: Path, pair: tuple[bytes, bytes]) -> None:
    """Publish a previously validated pair without reopening the input paths."""

    destination = output_root.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    _publish_sidecar_pair(
        (destination / RUN_SIDECAR_NAMES[0], pair[0]),
        (destination / RUN_SIDECAR_NAMES[1], pair[1]),
    )


def preflight_run_sidecars(output_root: Path, pair: tuple[bytes, bytes]) -> None:
    """Reject an incomplete or conflicting destination pair without writing."""

    destination = output_root.expanduser().resolve()
    _preflight_sidecar_pair(
        (destination / RUN_SIDECAR_NAMES[0], pair[0]),
        (destination / RUN_SIDECAR_NAMES[1], pair[1]),
    )


def _find_run_sidecars(
    input_path: Path,
    *,
    expected_source_ids: set[str] | None,
    source_bindings: Sequence[tuple[Path, Mapping[str, object]]] | None,
    require_mapped_input_paths: bool = True,
    expected_catalog_sha256: str = "",
) -> tuple[bytes, bytes] | None:
    resolved = input_path.expanduser().resolve(strict=True)
    directory = resolved if resolved.is_dir() else resolved.parent
    candidates = tuple(directory / name for name in RUN_SIDECAR_NAMES)
    present = tuple(_lexically_exists(path) for path in candidates)
    if not any(present):
        if expected_catalog_sha256:
            raise ValueError(f"Expected catalog digest but source sidecars are missing under {directory}")
        return None
    if not all(present):
        raise ValueError(f"Incomplete source sidecar pair under {directory}")
    manifest = _read_regular_bounded(candidates[0], MAX_SOURCE_MANIFEST_BYTES)
    metadata = _read_regular_bounded(candidates[1], MAX_SOURCE_METADATA_BYTES)
    try:
        payload = json.loads(manifest.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid source manifest JSON: {candidates[0]}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Source manifest must be a JSON object: {candidates[0]}")
    if count_json_items(payload, stop_after=MAX_SOURCE_MANIFEST_ITEMS) > MAX_SOURCE_MANIFEST_ITEMS:
        raise ValueError(
            f"Source manifest contains more than {MAX_SOURCE_MANIFEST_ITEMS} items: {candidates[0]}"
        )
    expected_digest = str(expected_catalog_sha256 or "").strip().casefold()
    if expected_digest:
        if re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
            raise ValueError("Expected audio catalog digest must be a SHA-256 value")
        catalog = payload.get("catalog")
        manifest_digest = str(catalog.get("sha256") or "").strip().casefold() if isinstance(catalog, dict) else ""
        if manifest_digest != expected_digest:
            raise ValueError("Audio source manifest catalog digest does not match the selected catalog run")
    if expected_source_ids:
        sources = payload.get("sources")
        if not isinstance(sources, list):
            raise ValueError(f"Source manifest sources must be a list: {candidates[0]}")
        manifest_ids = [
            str(entry.get("source_id") or "")
            for entry in sources
            if isinstance(entry, dict) and bool(entry.get("selected"))
        ]
        if len(manifest_ids) != len(set(manifest_ids)):
            raise ValueError(f"Source manifest contains duplicate selected SourceIDs: {candidates[0]}")
        unknown = sorted(expected_source_ids - set(manifest_ids))
        if unknown:
            raise ValueError(f"Audio inputs are not selected in the source manifest: {', '.join(unknown)}")
    if source_bindings is not None:
        _validate_source_bindings(
            payload,
            directory,
            source_bindings,
            candidates[0],
            require_mapped_input_paths=require_mapped_input_paths,
        )
    return manifest, metadata


def _validate_source_bindings(
    manifest: Mapping[str, object],
    run_root: Path,
    source_bindings: Sequence[tuple[Path, Mapping[str, object]]],
    manifest_path: Path,
    *,
    require_mapped_input_paths: bool,
) -> None:
    sources = manifest.get("sources")
    catalog = manifest.get("catalog")
    if not isinstance(sources, list) or not isinstance(catalog, dict):
        raise ValueError(f"Catalog source manifest has an invalid structure: {manifest_path}")
    selected_entries: dict[str, Mapping[str, object]] = {}
    for raw_entry in sources:
        if not isinstance(raw_entry, dict) or not raw_entry.get("selected"):
            continue
        source_id = str(raw_entry.get("source_id") or "")
        if not SOURCE_ID_PATTERN.fullmatch(source_id) or source_id in selected_entries:
            raise ValueError(f"Catalog source manifest has invalid or duplicate selected SourceIDs: {manifest_path}")
        selected_entries[source_id] = raw_entry
    seen: set[str] = set()
    context_roots: set[Path] = set()
    catalog_sha256 = str(catalog.get("sha256") or "")
    for video_path, context in source_bindings:
        source_id = str(context.get("source_id") or "")
        if not source_id:
            raise ValueError(f"Catalog audio input has no source context: {video_path}")
        if source_id in seen:
            raise ValueError(f"Multiple audio inputs claim the same catalog SourceID: {source_id}")
        seen.add(source_id)
        entry = selected_entries.get(source_id)
        if entry is None:
            raise ValueError(f"Audio input SourceID is unknown or unselected in the source manifest: {source_id}")
        raw_context_root = context.get("run_root")
        if not isinstance(raw_context_root, str) or not raw_context_root.strip():
            raise ValueError(f"Audio source context has no explicit catalog run root: {source_id}")
        try:
            context_root = Path(raw_context_root).expanduser().resolve(
                strict=require_mapped_input_paths
            )
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Audio source context catalog run root is invalid: {source_id}") from exc
        context_roots.add(context_root)
        if require_mapped_input_paths and context_root != run_root:
            raise ValueError(f"Audio source context catalog run root does not match the selected input: {source_id}")
        for field in ("speaker", "speaker_display", "source_kind", "resolved_link"):
            if context.get(field) != entry.get(field):
                raise ValueError(f"Audio source context {field} does not match manifest row {source_id}")
        if context.get("user_metadata") != entry.get("user_metadata"):
            raise ValueError(f"Audio source metadata does not match manifest row {source_id}")
        if context.get("system_metadata") != entry.get("system_metadata"):
            raise ValueError(f"Audio system metadata does not match manifest row {source_id}")
        if context.get("output_mapping") != entry.get("output_mapping"):
            raise ValueError(f"Audio output mapping does not match manifest row {source_id}")
        if context.get("source_kind") == "local" and context.get("local_identity") != entry.get("local_identity"):
            raise ValueError(f"Audio local media identity does not match manifest row {source_id}")
        if str(context.get("catalog_sha256") or "") != catalog_sha256:
            raise ValueError(f"Audio source context catalog digest does not match manifest row {source_id}")
        output_mapping = entry.get("output_mapping")
        if not isinstance(output_mapping, dict):
            raise ValueError(f"Audio output mapping is invalid for {source_id}")
        mapped_directory = Path(str(output_mapping.get("video_directory") or "")).expanduser().resolve()
        resolved_video = video_path.expanduser().resolve(strict=True)
        if mapped_directory != context_root and context_root not in mapped_directory.parents:
            raise ValueError(f"Manifest output mapping escapes the source context catalog run root: {source_id}")
        if require_mapped_input_paths and resolved_video != mapped_directory and mapped_directory not in resolved_video.parents:
            raise ValueError(f"Audio input location does not match manifest output mapping: {source_id}")
    if len(context_roots) > 1:
        raise ValueError("Audio source contexts do not share one catalog run root.")


def _lexically_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _read_regular_bounded(path: Path, max_bytes: int) -> bytes:
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode):
        raise ValueError(f"Source sidecar must not be a symlink: {path}")
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"Source sidecar must be a regular file: {path}")
    if before.st_size > max_bytes:
        raise ValueError(f"Source sidecar exceeds {max_bytes} bytes: {path}")
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or _file_identity(before) != _file_identity(opened):
            raise ValueError(f"Source sidecar changed while it was opened: {path}")
        content = handle.read(max_bytes + 1)
        after = os.fstat(handle.fileno())
    if len(content) > max_bytes:
        raise ValueError(f"Source sidecar exceeds {max_bytes} bytes: {path}")
    try:
        current = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"Source sidecar changed while it was read: {path}") from exc
    if not _same_open_snapshot(opened, after) or _file_identity(opened) != _file_identity(current):
        raise ValueError(f"Source sidecar changed while it was read: {path}")
    return content


def _publish_sidecar_pair(*entries: tuple[Path, bytes]) -> None:
    _preflight_sidecar_pair(*entries)
    existing = tuple(_lexically_exists(path) for path, _content in entries)
    if any(existing):
        if not all(existing):
            raise FileExistsError("Immutable source sidecar pair changed during publication preflight")
        return

    staged: list[tuple[Path, tuple[int, int]]] = []
    published: list[tuple[Path, tuple[int, int]]] = []
    try:
        for path, content in entries:
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                identity = _file_identity(os.fstat(handle.fileno()))
            staged.append((temporary, identity))
        for (temporary, identity), (destination, _content) in zip(staged, entries, strict=True):
            os.link(temporary, destination)
            published.append((destination, identity))
    except Exception:
        for destination, identity in reversed(published):
            if _path_has_identity(destination, identity):
                destination.unlink()
        raise
    finally:
        for temporary, _identity in staged:
            temporary.unlink(missing_ok=True)


def _preflight_sidecar_pair(*entries: tuple[Path, bytes]) -> None:
    existing = tuple(_lexically_exists(path) for path, _content in entries)
    if any(existing) and not all(existing):
        raise FileExistsError("Immutable source sidecar pair is incomplete at the audio output root")
    if not any(existing):
        return
    for path, content in entries:
        try:
            details = path.lstat()
            matches = (
                stat.S_ISREG(details.st_mode)
                and details.st_size == len(content)
                and _read_regular_bounded(path, len(content)) == content
            )
        except (FileNotFoundError, ValueError):
            matches = False
        if not matches:
            raise FileExistsError(f"Immutable source sidecar has different content: {path}")


def _file_identity(details: os.stat_result) -> tuple[int, int]:
    return int(details.st_dev), int(details.st_ino)


def _same_open_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        _file_identity(left) == _file_identity(right)
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
        and left.st_ctime_ns == right.st_ctime_ns
    )


def _path_has_identity(path: Path, expected: tuple[int, int]) -> bool:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(details.st_mode) and _file_identity(details) == expected
