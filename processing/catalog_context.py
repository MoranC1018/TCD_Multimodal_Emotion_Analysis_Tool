"""Shared immutable procurement-catalog bindings for native processors.

The procurement catalog is the authority whenever its sidecars are present.
Legacy recursive discovery is deliberately left to each modality and is only
permitted when this module returns ``None`` because no catalog evidence exists.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from procurement.input_limits import read_control_json
from spreadsheet_safety import neutralize_spreadsheet_value

from processing.audio_analysis.audio_pipeline.batch import (
    STITCHED_VIDEO_NAME,
    is_catalog_internal,
    is_generated_intermediate,
)
from processing.audio_analysis.audio_pipeline.source_context import (
    MAX_SOURCE_CONTEXT_BYTES,
    MAX_SOURCE_CONTEXT_ITEMS,
    RUN_SIDECAR_NAMES,
    preflight_run_sidecars,
    publish_run_sidecars,
    snapshot_run_sidecars,
    validate_source_context,
)
from processing.io_utils import atomic_write_json


PROCESSED_SOURCE_IDS_NAME = "processed_source_ids.json"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_METADATA_CORE_FIELDS = (
    "SourceID",
    "Link",
    "ResolvedLink",
    "SourceKind",
    "Speaker",
    "SpeakerDisplay",
    "Selected",
    "Status",
    "Title",
    "DurationSeconds",
    "YouTubeLanguage",
    "OutputDirectory",
)


@dataclass(frozen=True, slots=True)
class CatalogProcessingJob:
    source_id: str
    speaker: str
    speaker_display: str
    media_path: Path
    relative_output: Path
    source_context: Mapping[str, object]
    catalog_sha256: str
    user_metadata: Mapping[str, object]
    system_metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CatalogDiscoveryResult:
    run_root: Path
    jobs: tuple[CatalogProcessingJob, ...]
    sidecar_pair: tuple[bytes, bytes]
    catalog_sha256: str


def discover_catalog_jobs(
    input_path: Path | str,
    *,
    selected_source_ids: Sequence[str] | None = None,
    expected_catalog_sha256: str = "",
) -> CatalogDiscoveryResult | None:
    """Return validated catalog jobs, or ``None`` for a truly legacy input.

    Every manifest-selected context is validated before the authorized subset
    is returned.  This prevents a caller from hiding stale catalog state by
    asking to process only one apparently healthy SourceID.
    """

    requested_path = Path(input_path).expanduser().resolve(strict=True)
    run_root = _catalog_run_root(requested_path)
    if run_root is None:
        return None

    pair = snapshot_run_sidecars(
        run_root,
        expected_catalog_sha256=expected_catalog_sha256,
    )
    if pair is None:  # guarded by _catalog_run_root; retained as a fail-closed invariant
        raise ValueError(f"Partial catalog evidence exists under {run_root}")
    manifest = _manifest_payload(pair[0], run_root / RUN_SIDECAR_NAMES[0])
    catalog = manifest.get("catalog")
    sources = manifest.get("sources")
    if not isinstance(catalog, dict) or not isinstance(sources, list):
        raise ValueError("Catalog source manifest must contain catalog and sources objects")
    catalog_sha256 = str(catalog.get("sha256") or "").strip().casefold()
    if _SHA256_PATTERN.fullmatch(catalog_sha256) is None:
        raise ValueError("Catalog source manifest has an invalid catalog digest")

    selected_entries: list[Mapping[str, object]] = []
    selected_ids: list[str] = []
    for raw_entry in sources:
        if not isinstance(raw_entry, dict):
            raise ValueError("Catalog source manifest sources must contain objects")
        if not raw_entry.get("selected"):
            continue
        source_id = str(raw_entry.get("source_id") or "")
        if not source_id or source_id in selected_ids:
            raise ValueError("Catalog source manifest contains a duplicate selected SourceID")
        selected_ids.append(source_id)
        selected_entries.append(raw_entry)

    _validate_metadata_sidecar(pair[1], manifest)

    all_jobs: list[CatalogProcessingJob] = []
    source_bindings: list[tuple[Path, Mapping[str, object]]] = []
    expected_context_paths: set[Path] = set()
    for entry in selected_entries:
        job, context_path = _job_from_entry(run_root, catalog_sha256, entry)
        all_jobs.append(job)
        source_bindings.append((job.media_path, job.source_context))
        expected_context_paths.add(context_path)

    actual_context_paths = {
        path.resolve(strict=True)
        for path in run_root.rglob("source_context.json")
        if not is_catalog_internal(path, run_root)
    }
    orphaned = sorted(
        actual_context_paths - expected_context_paths,
        key=lambda path: str(path).casefold(),
    )
    if orphaned:
        raise ValueError(f"Orphan catalog source context is not mapped by the manifest: {orphaned[0]}")
    missing = sorted(
        expected_context_paths - actual_context_paths,
        key=lambda path: str(path).casefold(),
    )
    if missing:
        raise ValueError(f"Catalog manifest row has no exact source context: {missing[0]}")

    # Reuse the Audio sidecar validator for the final row/context/media binding
    # and exact catalog digest check.  No model work or output publication has
    # happened at this point.
    snapshot_run_sidecars(
        run_root,
        expected_source_ids=set(selected_ids),
        source_bindings=source_bindings,
        expected_catalog_sha256=catalog_sha256,
    )

    available_jobs = all_jobs
    if requested_path.is_file():
        available_jobs = [job for job in all_jobs if job.media_path == requested_path]
        if not available_jobs:
            raise ValueError(
                "Selected catalog file is not the exact canonical final media declared by its SourceID"
            )
    requested = _validate_selection(
        [job.source_id for job in available_jobs],
        selected_source_ids,
    )
    jobs = tuple(job for job in available_jobs if job.source_id in requested)
    return CatalogDiscoveryResult(
        run_root=run_root,
        jobs=jobs,
        sidecar_pair=pair,
        catalog_sha256=catalog_sha256,
    )


def publish_catalog_run_context(
    output_root: Path | str,
    discovery: CatalogDiscoveryResult,
) -> Path:
    """Publish exact top sidecars and a separate processed-SourceID record."""

    destination = Path(output_root).expanduser()
    preflight_run_sidecars(destination, discovery.sidecar_pair)
    publish_run_sidecars(destination, discovery.sidecar_pair)
    selection_path = destination / PROCESSED_SOURCE_IDS_NAME
    atomic_write_json(
        selection_path,
        {
            "format_version": 1,
            "catalog_sha256": discovery.catalog_sha256,
            "processed_source_ids": [job.source_id for job in discovery.jobs],
        },
    )
    return selection_path


def catalog_text_language(job: CatalogProcessingJob, explicit_language: str = "") -> str:
    """Apply the catalog Text-language contract without reading user metadata."""

    return str(
        job.system_metadata.get("youtube_language") or explicit_language or ""
    ).strip()


def _catalog_run_root(input_path: Path) -> Path | None:
    directory = input_path if input_path.is_dir() else input_path.parent
    if input_path.is_file():
        for ancestor in (directory, *directory.parents):
            manifest_path = ancestor / RUN_SIDECAR_NAMES[0]
            metadata_path = ancestor / RUN_SIDECAR_NAMES[1]
            present = (_lexically_exists(manifest_path), _lexically_exists(metadata_path))
            if any(present):
                if not all(present):
                    raise ValueError(f"Incomplete source sidecar pair under {ancestor}")
                return ancestor
            context_path = ancestor / "source_context.json"
            if _lexically_exists(context_path):
                context = _load_exact_context(context_path)
                raw_root = context.get("run_root")
                if not isinstance(raw_root, str) or not raw_root.strip():
                    raise ValueError(f"Catalog source context has no run root: {context_path}")
                root = Path(raw_root).expanduser().resolve(strict=True)
                pair_present = tuple(_lexically_exists(root / name) for name in RUN_SIDECAR_NAMES)
                if not all(pair_present):
                    raise ValueError(f"Partial catalog evidence exists under {ancestor}")
                return root
        return None
    manifest_path = directory / RUN_SIDECAR_NAMES[0]
    metadata_path = directory / RUN_SIDECAR_NAMES[1]
    present = (_lexically_exists(manifest_path), _lexically_exists(metadata_path))
    if any(present):
        if not all(present):
            raise ValueError(f"Incomplete source sidecar pair under {directory}")
        return directory

    context_path = directory / "source_context.json"
    if _lexically_exists(context_path):
        context = _load_exact_context(context_path)
        raw_root = context.get("run_root")
        if not isinstance(raw_root, str) or not raw_root.strip():
            raise ValueError(f"Catalog source context has no run root: {context_path}")
        root = Path(raw_root).expanduser().resolve(strict=True)
        pair_present = tuple(_lexically_exists(root / name) for name in RUN_SIDECAR_NAMES)
        if not all(pair_present):
            raise ValueError(f"Partial catalog evidence exists under {directory}")
        return root

    if input_path.is_dir():
        evidence = next(
            (
                path
                for name in (*RUN_SIDECAR_NAMES, "source_context.json")
                for path in input_path.rglob(name)
                if not is_catalog_internal(path, input_path)
            ),
            None,
        )
        if evidence is not None:
            raise ValueError(f"Partial catalog evidence exists under {input_path}: {evidence}")
    return None


def _manifest_payload(raw: bytes, path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid source manifest JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Source manifest must be a JSON object: {path}")
    return payload


def _validate_selection(
    available_source_ids: Sequence[str],
    selected_source_ids: Sequence[str] | None,
) -> set[str]:
    if selected_source_ids is None:
        return set(available_source_ids)
    requested = [str(source_id) for source_id in selected_source_ids]
    if len(requested) != len(set(requested)):
        raise ValueError("Selected catalog SourceIDs must be unique")
    unknown = sorted(set(requested) - set(available_source_ids))
    if unknown:
        raise ValueError(f"Unknown or unselected catalog SourceID: {', '.join(unknown)}")
    return set(requested)


def _job_from_entry(
    run_root: Path,
    catalog_sha256: str,
    entry: Mapping[str, object],
) -> tuple[CatalogProcessingJob, Path]:
    source_id = str(entry.get("source_id") or "")
    output_mapping = entry.get("output_mapping")
    if not isinstance(output_mapping, dict):
        raise ValueError(f"Catalog output mapping is invalid for {source_id}")
    raw_directory = output_mapping.get("video_directory")
    if not isinstance(raw_directory, str) or not raw_directory:
        raise ValueError(f"Catalog output mapping is missing for {source_id}")
    mapped_directory = Path(raw_directory).expanduser().resolve(strict=True)
    try:
        relative_output = mapped_directory.relative_to(run_root)
    except ValueError as exc:
        raise ValueError(f"Catalog output mapping escapes the run root for {source_id}") from exc
    if not relative_output.parts:
        raise ValueError(f"Catalog output mapping cannot be the run root for {source_id}")

    context_path = mapped_directory / "source_context.json"
    if not _lexically_exists(context_path):
        raise ValueError(f"Catalog manifest row has no exact source context: {source_id}")
    context = _load_exact_context(context_path)
    if context.get("source_id") != source_id:
        raise ValueError(f"Catalog source context SourceID does not match manifest row {source_id}")
    media_path = _canonical_media(mapped_directory, run_root, source_id)
    user_metadata = entry.get("user_metadata")
    system_metadata = entry.get("system_metadata")
    if not isinstance(user_metadata, dict) or not isinstance(system_metadata, dict):
        raise ValueError(f"Catalog metadata objects are invalid for {source_id}")
    return (
        CatalogProcessingJob(
            source_id=source_id,
            speaker=str(entry.get("speaker") or ""),
            speaker_display=str(entry.get("speaker_display") or ""),
            media_path=media_path,
            relative_output=relative_output,
            source_context=_freeze_mapping(context),
            catalog_sha256=catalog_sha256,
            user_metadata=_freeze_mapping(user_metadata),
            system_metadata=_freeze_mapping(system_metadata),
        ),
        context_path.resolve(strict=True),
    )


def _load_exact_context(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise ValueError(f"Source context must not be a symlink: {path}")
    payload = read_control_json(
        path,
        label="source context",
        max_bytes=MAX_SOURCE_CONTEXT_BYTES,
        max_items=MAX_SOURCE_CONTEXT_ITEMS,
    )
    return validate_source_context(payload, path=path)


def _canonical_media(mapped_directory: Path, run_root: Path, source_id: str) -> Path:
    stitched = [
        path.resolve(strict=True)
        for path in mapped_directory.rglob(STITCHED_VIDEO_NAME)
        if not is_catalog_internal(path, run_root)
    ]
    if len(stitched) == 1:
        return stitched[0]
    if len(stitched) > 1:
        raise ValueError(f"Catalog SourceID has ambiguous canonical stitched media: {source_id}")
    candidates: list[Path] = []
    for path in mapped_directory.rglob("*.mp4"):
        if is_catalog_internal(path, run_root):
            continue
        if any(part.casefold() == "raw_clips" for part in path.parts):
            continue
        if is_generated_intermediate(path):
            continue
        candidates.append(path.resolve(strict=True))
    unique = list(dict.fromkeys(candidates))
    if len(unique) != 1:
        qualifier = "no" if not unique else "ambiguous"
        raise ValueError(f"Catalog SourceID has {qualifier} canonical final media: {source_id}")
    return unique[0]


def _validate_metadata_sidecar(raw: bytes, manifest: Mapping[str, object]) -> None:
    catalog = manifest.get("catalog")
    sources = manifest.get("sources")
    if not isinstance(catalog, dict) or not isinstance(sources, list):
        raise ValueError("Catalog source manifest has invalid metadata association")
    export_headers = catalog.get("metadata_export_headers")
    metadata_headers = catalog.get("metadata_headers")
    if not isinstance(export_headers, dict) or not isinstance(metadata_headers, list):
        raise ValueError("Catalog source manifest has invalid metadata header mapping")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("Invalid source metadata CSV") from exc
    expected_headers = [
        *_METADATA_CORE_FIELDS,
        *[
            str(neutralize_spreadsheet_value(export_headers.get(label, "")))
            for label in metadata_headers
        ],
    ]
    if reader.fieldnames != expected_headers or len(rows) != len(sources):
        raise ValueError("Source metadata CSV does not match the source manifest")
    for raw_entry, row in zip(sources, rows, strict=True):
        if not isinstance(raw_entry, dict):
            raise ValueError("Source metadata CSV does not match the source manifest")
        system = raw_entry.get("system_metadata")
        output = raw_entry.get("output_mapping")
        user = raw_entry.get("user_metadata")
        if not isinstance(system, dict) or not isinstance(output, dict) or not isinstance(user, dict):
            raise ValueError("Source metadata CSV does not match the source manifest")
        expected_core = {
            "SourceID": raw_entry.get("source_id", ""),
            "Link": raw_entry.get("link", ""),
            "ResolvedLink": raw_entry.get("resolved_link", ""),
            "SourceKind": raw_entry.get("source_kind", ""),
            "Speaker": raw_entry.get("speaker", ""),
            "SpeakerDisplay": raw_entry.get("speaker_display", ""),
            "Selected": str(bool(raw_entry.get("selected"))).lower(),
            "Status": raw_entry.get("status", ""),
            "Title": system.get("title", ""),
            "DurationSeconds": system.get("duration_seconds", ""),
            "YouTubeLanguage": system.get("youtube_language", ""),
            "OutputDirectory": output.get("video_directory", ""),
        }
        for label, value in expected_core.items():
            if row.get(label) != str(neutralize_spreadsheet_value(value)):
                raise ValueError("Source metadata CSV does not match the source manifest")
        for label in metadata_headers:
            exported = str(neutralize_spreadsheet_value(export_headers[label]))
            expected = str(neutralize_spreadsheet_value(user.get(label, "")))
            if row.get(exported) != expected:
                raise ValueError("Source metadata CSV does not match the source manifest")


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _lexically_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True
