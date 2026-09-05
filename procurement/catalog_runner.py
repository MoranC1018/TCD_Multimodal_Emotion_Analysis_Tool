"""Thin coordinator for ordered mixed-source procurement catalogs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import random
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable, Mapping, Sequence

from spreadsheet_safety import SpreadsheetSafeWriter, neutralize_spreadsheet_value

from procurement.catalog import CatalogSource, SourceCatalog, read_catalog
from procurement.external_tools import credential_free_media_environment
from procurement.video_sampling.full_video_download import make_filename_safe


MetadataFetcher = Callable[[list[str]], dict[str, dict[str, object]]]
LocalMetadataFetcher = Callable[[CatalogSource], Mapping[str, object]]
SourceProcessor = Callable[[CatalogSource, Path, "CatalogRunOptions"], Mapping[str, str]]


WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
MAX_LOCAL_SOURCE_BYTES = 20 * 1024 * 1024 * 1024
MAX_LOCAL_CATALOG_BYTES = 100 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class CatalogRunOptions:
    mode: str = "standard"
    percentage: float = 0.10
    max_segment_seconds: int = 30
    segments_json: str = ""
    manifest_sha256: str = ""
    expected_source: str = ""
    output_mode: str = "clean"
    min_clean_seconds: float = 10.0
    gap_seconds: float = 0.5
    identity_stills: int = 20
    scan_fps: float = 1.0
    validation_fps: float = 4.0
    face_confidence: float = 0.65
    speaker_confidence: float = 0.65
    workers: int = 1
    device: str = "auto"
    keep_debug: bool = False
    resource_guard_percent: float = 15.0
    resource_poll_seconds: float = 15.0
    resource_guard_timeout_seconds: float = 900.0
    parallel_detectors: bool = False
    reference_audio: str = ""
    only_video_ids: tuple[str, ...] = ()
    random_one: bool = False
    random_seed: str = ""
    isolated_video_processes: bool = False
    skip_first_videos: int = 0
    skip_completed_outputs: bool = False
    video_cooldown_seconds: float = 60.0
    max_download_height: int = 720
    max_affinity_cores: int = 2
    native_threads: int = 1
    cpu_throttle_high_percent: float = 95.0
    cpu_throttle_low_percent: float = 90.0
    ram_throttle_high_percent: float = 95.0
    ram_throttle_low_percent: float = 90.0
    catalog_path: str = ""
    focus_payload: Mapping[str, object] | None = field(default=None, repr=False, compare=False)
    allow_external_local_paths: bool = False

    def manifest_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("catalog_path", None)
        payload.pop("focus_payload", None)
        payload["only_video_ids"] = list(self.only_video_ids)
        return payload


@dataclass(frozen=True)
class CatalogRunResult:
    run_root: Path
    manifest_path: Path
    metadata_path: Path
    processed_source_ids: tuple[str, ...]


def resolve_youtube_language(snippet: Mapping[str, object]) -> str:
    """Return API language precedence without consulting researcher metadata."""

    return str(
        snippet.get("youtube_language")
        or snippet.get("defaultAudioLanguage")
        or snippet.get("defaultLanguage")
        or ""
    ).strip()


def run_catalog(
    catalog_path: Path | str,
    run_root: Path | str,
    *,
    mode: str = "standard",
    selected_source_ids: Sequence[str] | None = None,
    expected_catalog_sha256: str = "",
    metadata_fetcher: MetadataFetcher | None = None,
    local_metadata_fetcher: LocalMetadataFetcher | None = None,
    processor: SourceProcessor | None = None,
    options: CatalogRunOptions | None = None,
) -> CatalogRunResult:
    """Write immutable source sidecars, then process selected rows in catalog order."""

    options = options or CatalogRunOptions(mode=str(mode or "standard"))
    catalog = read_catalog(
        catalog_path,
        expected_sha256=expected_catalog_sha256,
        allow_external_local_paths=options.allow_external_local_paths,
    )
    selected = _validated_selection(catalog, selected_source_ids)
    if options.mode != str(mode or options.mode) and mode != "standard":
        raise ValueError("Catalog mode and run options disagree.")
    options = replace(options, catalog_path=str(catalog.path))
    _validate_options(options)
    if options.mode == "manual":
        selected, focus_payload = _preflight_focus(catalog, selected, options)
        options = replace(options, focus_payload=focus_payload)
    elif options.mode == "clean-speaker-beta":
        selected, options = _apply_clean_catalog_selection(catalog, selected, options)
    root = Path(os.path.abspath(Path(run_root).expanduser()))
    if _is_reparse_path(root):
        raise ValueError(f"Catalog run root must not be a symlink or reparse point: {root}")
    root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="mea-catalog-snapshot-") as snapshot_directory:
        return _run_catalog_with_local_snapshots(
            catalog,
            root,
            selected,
            options,
            Path(snapshot_directory),
            metadata_fetcher=metadata_fetcher,
            local_metadata_fetcher=local_metadata_fetcher,
            processor=processor,
        )


def _run_catalog_with_local_snapshots(
    catalog: SourceCatalog,
    root: Path,
    selected: set[str],
    options: CatalogRunOptions,
    snapshot_directory: Path,
    *,
    metadata_fetcher: MetadataFetcher | None,
    local_metadata_fetcher: LocalMetadataFetcher | None,
    processor: SourceProcessor | None,
) -> CatalogRunResult:
    processing_sources: dict[str, CatalogSource] = {}
    selected_local_identities: dict[str, dict[str, object]] = {}
    snapshot_bytes = 0
    for source in catalog.sources:
        if source.source_id not in selected or source.source_kind != "local":
            continue
        # Keep filename-derived metadata stable while isolating duplicate names
        # and continuing to probe and process only the sealed media snapshot.
        source_snapshot_directory = snapshot_directory / source.source_id
        source_snapshot_directory.mkdir()
        snapshot_path = source_snapshot_directory / Path(source.resolved_link).name
        remaining = MAX_LOCAL_CATALOG_BYTES - snapshot_bytes
        if remaining <= 0:
            raise ValueError(
                f"Catalog local snapshots exceed the {MAX_LOCAL_CATALOG_BYTES} byte limit"
            )
        identity = _snapshot_local_source(
            source,
            snapshot_path,
            max_bytes=min(MAX_LOCAL_SOURCE_BYTES, remaining),
        )
        selected_local_identities[source.source_id] = identity
        snapshot_bytes += int(identity["size_bytes"])
        processing_sources[source.source_id] = replace(source, resolved_link=str(snapshot_path))

    youtube_ids = list(dict.fromkeys(source.youtube_id for source in catalog.sources if source.youtube_id))
    youtube_metadata = metadata_fetcher(youtube_ids) if metadata_fetcher and youtube_ids else {}
    entries = []
    for source in catalog.sources:
        system_metadata: Mapping[str, object]
        if source.source_kind == "youtube":
            system_metadata = youtube_metadata.get(source.youtube_id, {})
        elif local_metadata_fetcher is not None:
            system_metadata = local_metadata_fetcher(processing_sources.get(source.source_id, source))
        else:
            system_metadata = {}
        entries.append(
            _manifest_entry(
                source,
                root,
                source.source_id in selected,
                system_metadata,
                local_identity=selected_local_identities.get(source.source_id),
            )
        )
    metadata_field_map = _metadata_export_field_map(catalog.metadata_headers)
    manifest = {
        "format_version": 1,
        "catalog": {
            "path": str(catalog.path),
            "format": catalog.format,
            "sha256": catalog.sha256,
            "original_headers": list(catalog.original_headers),
            "ignored_headers": list(catalog.ignored_headers),
            "metadata_headers": list(catalog.metadata_headers),
            "metadata_export_headers": metadata_field_map,
        },
        "procurement_options": options.manifest_dict(),
        "sources": entries,
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")
    metadata_bytes = _metadata_csv_bytes(catalog, entries, metadata_field_map)
    manifest_path = root / "source_manifest.json"
    metadata_path = root / "source_metadata.csv"
    entries_by_id = {str(entry["source_id"]): entry for entry in entries}
    context_items: list[tuple[Path, bytes]] = []
    for entry in entries:
        output_directory = Path(str(entry["output_mapping"]["video_directory"]))
        _ensure_output_path_safe(root, output_directory)
        if entry["source_id"] in selected:
            context_items.append(
                (
                    output_directory / "source_context.json",
                    _source_context_bytes(root, catalog, entry),
                )
            )

    top_items = ((manifest_path, manifest_bytes), (metadata_path, metadata_bytes))
    _preflight_complete_pair(*top_items)
    _preflight_immutable_sidecars(*top_items, *context_items)
    for context_path, _content in context_items:
        context_path.parent.mkdir(parents=True, exist_ok=True)
        _ensure_output_path_safe(root, context_path.parent)
    _write_immutable_sidecar_pair(*top_items, *context_items)

    processed: list[str] = []
    if selected:
        processor = processor or _default_source_processor
        for source in catalog.sources:
            if source.source_id not in selected:
                continue
            output_directory = Path(entries_by_id[source.source_id]["output_mapping"]["video_directory"])
            _ensure_output_path_safe(root, output_directory)
            processor(processing_sources.get(source.source_id, source), output_directory, options)
            processed.append(source.source_id)

    return CatalogRunResult(
        run_root=root,
        manifest_path=manifest_path,
        metadata_path=metadata_path,
        processed_source_ids=tuple(processed),
    )


def _validated_selection(catalog: SourceCatalog, selected_source_ids: Sequence[str] | None) -> set[str]:
    available = {source.source_id for source in catalog.sources}
    requested = list(available if selected_source_ids is None else selected_source_ids)
    if len(requested) != len(set(requested)):
        raise ValueError("Selected source IDs must be unique.")
    unknown = [source_id for source_id in requested if source_id not in available]
    if unknown:
        raise ValueError(f"Unknown selected source IDs: {', '.join(unknown)}")
    return set(requested)


def _validate_options(options: CatalogRunOptions) -> None:
    if options.mode not in {"standard", "full", "manual", "clean-speaker-beta"}:
        raise ValueError(f"Unsupported catalog procurement mode: {options.mode}")
    percentage = _finite(options.percentage, "Sample percentage")
    if not 0 < percentage <= 1:
        raise ValueError("Sample percentage must be greater than 0 and no more than 100%.")
    _whole_range(options.max_segment_seconds, "Maximum segment length", 1, 3600)
    if options.output_mode not in {"clean", "percentage"}:
        raise ValueError("Clean speaker output mode must be 'clean' or 'percentage'.")
    if _finite(options.min_clean_seconds, "Minimum clean overlap") <= 0:
        raise ValueError("Minimum clean overlap must be greater than 0 seconds.")
    _number_range(options.gap_seconds, "Black/silent gap", 0, 60)
    _whole_range(options.identity_stills, "Identity still count", 1, 200)
    _number_range(options.scan_fps, "Scan FPS", 0.1, 10)
    _number_range(options.validation_fps, "Validation FPS", 0.1, 10)
    _number_range(options.face_confidence, "Face confidence", 0, 1, minimum_exclusive=True)
    _number_range(options.speaker_confidence, "Speaker confidence", 0, 1, minimum_exclusive=True)
    _whole_range(options.workers, "Worker count", 1, 64)
    if options.device not in {"auto", "cpu", "cuda"}:
        raise ValueError("Clean speaker model device must be auto, cpu, or cuda.")
    _number_range(options.resource_guard_percent, "Resource guard", 0, 95)
    _number_range(options.resource_poll_seconds, "Resource poll interval", 0.5, 300)
    _number_range(options.resource_guard_timeout_seconds, "Resource wait timeout", 0, 86400)
    _whole_range(options.skip_first_videos, "Skip-first count", 0, 10_000)
    _number_range(options.video_cooldown_seconds, "Video cooldown", 0, 3600)
    _whole_range(options.max_download_height, "Maximum download height", 0, 4320)
    _whole_range(options.max_affinity_cores, "Maximum CPU cores", 0, 256)
    _whole_range(options.native_threads, "Native thread count", 1, 256)
    cpu_high = _number_range(options.cpu_throttle_high_percent, "CPU pause threshold", 1, 100)
    cpu_low = _number_range(options.cpu_throttle_low_percent, "CPU resume threshold", 1, 100)
    ram_high = _number_range(options.ram_throttle_high_percent, "RAM pause threshold", 1, 100)
    ram_low = _number_range(options.ram_throttle_low_percent, "RAM resume threshold", 1, 100)
    if cpu_low > cpu_high:
        raise ValueError("CPU resume threshold must be no greater than its pause threshold.")
    if ram_low > ram_high:
        raise ValueError("RAM resume threshold must be no greater than its pause threshold.")
    if options.mode == "manual":
        if not options.segments_json or not options.expected_source:
            raise ValueError("Manual catalog mode requires the validated Focus manifest binding.")
        if not re.fullmatch(r"[0-9a-f]{64}", options.manifest_sha256.casefold()):
            raise ValueError("Manual catalog mode requires a valid Focus manifest SHA-256.")


def _finite(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number.")
    return number


def _number_range(
    value: object,
    label: str,
    minimum: float,
    maximum: float,
    *,
    minimum_exclusive: bool = False,
) -> float:
    number = _finite(value, label)
    minimum_ok = number > minimum if minimum_exclusive else number >= minimum
    if not minimum_ok or number > maximum:
        qualifier = "greater than" if minimum_exclusive else "between"
        raise ValueError(f"{label} must be {qualifier} {minimum:g} and no more than {maximum:g}.")
    return number


def _whole_range(value: object, label: str, minimum: int, maximum: int) -> int:
    number = _finite(value, label)
    if not number.is_integer() or not minimum <= number <= maximum:
        raise ValueError(f"{label} must be a whole number between {minimum} and {maximum}.")
    return int(number)


def _preflight_focus(
    catalog: SourceCatalog,
    authorized_source_ids: set[str],
    options: CatalogRunOptions,
) -> tuple[set[str], Mapping[str, object]]:
    from application import backend, manual_segments

    if not backend.source_references_match(options.expected_source, str(catalog.path)):
        raise ValueError("Focus expected source does not match this catalog snapshot.")
    payload = manual_segments.load_focus_manifest(
        Path(options.segments_json),
        expected_sha256=options.manifest_sha256,
        expected_source=options.expected_source,
    )
    if not backend.source_references_match(payload.get("processing_source_path"), str(catalog.path)):
        raise ValueError("Focus processing source does not match this catalog snapshot.")
    segments = payload.get("selected_segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Focus manifest selected_segments must be a non-empty list.")
    sources_by_id = {source.source_id: source for source in catalog.sources}
    segment_source_ids: set[str] = set()
    for segment in segments:
        if not isinstance(segment, Mapping):
            raise ValueError("Focus manifest selected_segments must contain objects.")
        source_id = str(segment.get("source_id") or "")
        source = sources_by_id.get(source_id)
        if source is None:
            raise ValueError(f"Focus manifest contains an unknown catalog SourceID: {source_id or '<blank>'}")
        if source_id not in authorized_source_ids:
            raise ValueError(f"Focus manifest SourceID was not selected in the latest catalog scan: {source_id}")
        _validate_focus_identity(source, segment, backend)
        segment_source_ids.add(source_id)
    return segment_source_ids, dict(payload)


def _apply_clean_catalog_selection(
    catalog: SourceCatalog,
    authorized_source_ids: set[str],
    options: CatalogRunOptions,
) -> tuple[set[str], CatalogRunOptions]:
    ordered = [source for source in catalog.sources if source.source_id in authorized_source_ids]
    if options.only_video_ids:
        requested_video_ids = list(options.only_video_ids)
        if len(requested_video_ids) != len(set(requested_video_ids)):
            raise ValueError("Clean speaker YouTube video ID filters must be unique.")
        available_video_ids = {source.youtube_id for source in ordered if source.youtube_id}
        unknown = sorted(set(requested_video_ids) - available_video_ids)
        if unknown:
            raise ValueError(f"Unknown selected YouTube video IDs: {', '.join(unknown)}")
        selected_video_ids = set(requested_video_ids)
        ordered = [source for source in ordered if source.youtube_id in selected_video_ids]
    if options.skip_first_videos:
        ordered = ordered[options.skip_first_videos :]
    effective_options = options
    if options.random_one and ordered:
        seed = options.random_seed or secrets.token_hex(16)
        ordered = [random.Random(seed).choice(ordered)]
        effective_options = replace(options, random_seed=seed)
    if not ordered:
        raise ValueError("Clean speaker catalog filters removed every selected SourceID.")
    return {source.source_id for source in ordered}, effective_options


def _validate_focus_identity(
    source: CatalogSource,
    segment: Mapping[str, object],
    backend_module,
) -> None:
    identity = backend_module.focus_source_identity(segment)
    if source.source_kind == "local":
        expected = os.path.normcase(str(Path(source.resolved_link).resolve()))
        if identity.kind not in {"file", "folder"} or identity.reference != expected:
            raise ValueError(f"Focus segment source does not match {source.source_id}.")
    elif identity.kind != "youtube" or identity.youtube_id != source.youtube_id:
        raise ValueError(f"Focus segment source does not match {source.source_id}.")


def _manifest_entry(
    source: CatalogSource,
    run_root: Path,
    selected: bool,
    system_metadata: Mapping[str, object],
    *,
    local_identity: Mapping[str, object] | None = None,
) -> dict[str, object]:
    title = str(system_metadata.get("title") or _source_title(source)).strip()
    duration = system_metadata.get("duration_seconds")
    youtube_language = resolve_youtube_language(system_metadata) if source.source_kind == "youtube" else ""
    output_directory = _output_directory(run_root, source, title)
    entry: dict[str, object] = {
        "source_id": source.source_id,
        "catalog_row": source.row_number,
        "link": source.link,
        "resolved_link": source.resolved_link,
        "source_kind": source.source_kind,
        "speaker": source.speaker,
        "speaker_display": source.speaker_display,
        "selected": selected,
        "status": "selected" if selected else "not_selected",
        "system_metadata": {
            "title": title,
            "duration_seconds": duration if isinstance(duration, (int, float)) else "",
            "youtube_language": youtube_language,
        },
        "user_metadata": dict(source.metadata),
        "output_mapping": {"video_directory": str(output_directory)},
    }
    if source.source_kind == "youtube":
        entry["youtube"] = {"video_id": source.youtube_id, "url": source.resolved_link}
    else:
        entry["local_identity"] = dict(local_identity or _local_identity(Path(source.resolved_link)))
    return entry


def _source_title(source: CatalogSource) -> str:
    if source.source_kind == "local":
        return Path(source.resolved_link).stem
    return source.youtube_id or "youtube_video"


def _output_directory(run_root: Path, source: CatalogSource, title: str) -> Path:
    video_name = _safe_windows_segment(f"{source.source_id}_{title}", max_length=100)
    parent = run_root
    if source.speaker:
        parent = run_root / _safe_windows_segment(source.speaker, max_length=80)
    candidate = Path(os.path.abspath(parent / video_name))
    _ensure_output_path_safe(run_root, candidate)
    return candidate


def _ensure_output_path_safe(run_root: Path, output_directory: Path) -> None:
    lexical_root = Path(os.path.abspath(run_root))
    lexical_output = Path(os.path.abspath(output_directory))
    try:
        relative = lexical_output.relative_to(lexical_root)
    except ValueError as exc:
        raise ValueError("Catalog output mapping escapes the selected run root.") from exc
    if not relative.parts:
        raise ValueError("Catalog output mapping escapes the selected run root.")
    current = lexical_root
    for part in relative.parts:
        current = current / part
        if _is_reparse_path(current):
            raise ValueError(
                "Catalog output mapping escapes the selected run root through a symlink or reparse point: "
                f"{current}"
            )


def _safe_windows_segment(value: str, *, max_length: int) -> str:
    cleaned = make_filename_safe(value, max_length=max_length)
    if cleaned.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:max_length]


def _is_reparse_path(path: Path) -> bool:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    attributes = int(getattr(details, "st_file_attributes", 0) or 0)
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0)
    return stat.S_ISLNK(details.st_mode) or bool(reparse_flag and attributes & reparse_flag)


def _local_identity(path: Path) -> dict[str, object]:
    canonical = path.expanduser().resolve(strict=True)
    before = canonical.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"Catalog local source must be a regular file: {canonical}")
    digest = hashlib.sha256()
    size = 0
    with canonical.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or not _same_file_identity(before, opened):
            raise ValueError(f"Catalog local source changed while it was opened: {canonical}")
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
        after = os.fstat(handle.fileno())
        if not _same_open_snapshot(opened, after):
            raise ValueError(f"Catalog local source changed while it was read: {canonical}")
    return {
        "canonical_path": str(canonical),
        "sha256": digest.hexdigest(),
        "size_bytes": size,
    }


def _snapshot_local_source(
    source: CatalogSource,
    snapshot_path: Path,
    *,
    max_bytes: int | None = None,
) -> dict[str, object]:
    original = Path(source.resolved_link).expanduser().resolve(strict=True)
    before = original.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"Catalog local source must be a regular file: {original}")
    limit = MAX_LOCAL_SOURCE_BYTES if max_bytes is None else int(max_bytes)
    if before.st_size > limit:
        raise ValueError(
            f"Catalog local source exceeds the {limit} byte limit: {original}"
        )
    digest = hashlib.sha256()
    size = 0
    with original.open("rb") as source_handle, snapshot_path.open("xb") as snapshot_handle:
        opened = os.fstat(source_handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or not _same_file_identity(before, opened):
            raise ValueError(f"Catalog local source changed while it was opened: {original}")
        for block in iter(lambda: source_handle.read(1024 * 1024), b""):
            snapshot_handle.write(block)
            digest.update(block)
            size += len(block)
            if size > limit:
                raise ValueError(
                    f"Catalog local source exceeds the {limit} byte limit: {original}"
                )
        after = os.fstat(source_handle.fileno())
        if not _same_open_snapshot(opened, after):
            raise ValueError(f"Catalog local source changed while it was read: {original}")
        snapshot_handle.flush()
        os.fsync(snapshot_handle.fileno())
    return {
        "canonical_path": str(original),
        "sha256": digest.hexdigest(),
        "size_bytes": size,
    }


def _source_context_bytes(
    run_root: Path,
    catalog: SourceCatalog,
    entry: Mapping[str, object],
) -> bytes:
    """Serialize the immutable per-source provenance consumed by audio analysis."""

    context = {
        "format_version": 1,
        "source_id": entry["source_id"],
        "speaker": entry["speaker"],
        "speaker_display": entry["speaker_display"],
        "source_kind": entry["source_kind"],
        "resolved_link": entry["resolved_link"],
        "run_root": str(run_root),
        "catalog_path": str(catalog.path),
        "catalog_sha256": catalog.sha256,
        "user_metadata": entry["user_metadata"],
        "system_metadata": entry["system_metadata"],
        "output_mapping": entry["output_mapping"],
    }
    if entry["source_kind"] == "local":
        context["local_identity"] = entry["local_identity"]
    return (json.dumps(context, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _default_source_processor(
    source: CatalogSource,
    output_directory: Path,
    options: CatalogRunOptions,
) -> Mapping[str, str]:
    """Dispatch one selected row through the existing procurement adapters."""

    if options.mode == "manual":
        return _process_manual_source(source, output_directory, options)
    if options.mode == "clean-speaker-beta":
        command = _clean_speaker_command(source, output_directory, options)
        subprocess.run(command, check=True, env=_clean_speaker_environment())
        return {"output_directory": str(output_directory)}
    if options.mode not in {"standard", "full"}:
        raise ValueError(f"Unsupported catalog procurement mode: {options.mode}")

    if source.source_kind == "local":
        from application import local_videos

        target = output_directory / "stitched_imotions.mp4"
        local_path = Path(source.resolved_link)
        if options.mode == "standard":
            local_videos.create_standard_sample(
                local_path,
                target,
                options.percentage,
                options.max_segment_seconds,
            )
        else:
            local_videos.create_full_video(local_path, target)
        return {"video": str(target)}

    if options.mode == "standard":
        from procurement.video_sampling import run_docx_extractions

        extractor_script = Path(run_docx_extractions.__file__).resolve().parent / "extraction_router.py"
        folder = run_docx_extractions.extract_or_reuse_folder(
            url=source.resolved_link,
            video_id=source.youtube_id,
            extractor_script=extractor_script,
            working_folder=output_directory,
            force=False,
            extra_extractor_args=(
                "--percentage",
                str(options.percentage),
                "--segment-length",
                str(options.max_segment_seconds),
            ),
        )
        return {"video_directory": str(folder)}

    from procurement import run_pipeline

    item = run_pipeline.PipelineItem(
        table_number=0,
        row_number=source.row_number,
        video_id=source.youtube_id,
        url=source.resolved_link,
        speaker=source.speaker_display,
        speaker_reason="Catalog Speaker value" if source.speaker else "Pooled catalog source",
        license_text="",
        strategy=run_pipeline.STRATEGY_FULL_MANUAL_OVERRIDE,
    )
    folder = run_pipeline.run_full_video_download(
        item=item,
        speaker_folder=output_directory,
        dry_run=False,
        allow_non_cc=True,
        extra_args=[],
    )
    return {"video_directory": str(folder or output_directory)}


def _process_manual_source(
    source: CatalogSource,
    output_directory: Path,
    options: CatalogRunOptions,
) -> Mapping[str, str]:
    from application import backend, manual_segments

    payload = options.focus_payload
    if not isinstance(payload, Mapping):
        raise ValueError("Manual catalog mode requires a preflighted Focus manifest.")
    selected_segments = payload.get("selected_segments")
    if not isinstance(selected_segments, list):
        raise ValueError("Focus manifest selected_segments must be a list.")
    segments = [
        dict(item)
        for item in selected_segments
        if isinstance(item, dict) and str(item.get("source_id") or "") == source.source_id
    ]
    if not segments:
        raise ValueError(f"No Focus segments were selected for {source.source_id}.")
    if source.source_kind != "local":
        for segment in segments:
            _validate_focus_identity(source, segment, backend)

    gap_seconds = max(0.0, float(payload.get("gap_seconds") or 0))
    if source.source_kind == "local":
        local_path = Path(source.resolved_link).resolve()
        manual_segments.process_one_video(
            local_path.parent,
            output_directory,
            local_path,
            segments,
            gap_seconds,
            target_directory=output_directory,
        )
    else:
        manual_segments.process_one_youtube_video(
            output_directory,
            source.resolved_link,
            segments,
            gap_seconds,
            target_directory=output_directory,
        )
    return {"video_directory": str(output_directory)}


def _clean_speaker_command(
    source: CatalogSource,
    output_directory: Path,
    options: CatalogRunOptions,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "procurement.procurement_beta.cli",
        "--source",
        source.resolved_link,
        "--output-root",
        str(output_directory),
        "--source-context",
        str(output_directory / "source_context.json"),
        "--source-id",
        source.source_id,
        "--output-mode",
        options.output_mode,
        "--percentage",
        str(options.percentage),
        "--min-clean-seconds",
        str(options.min_clean_seconds),
        "--max-segment-seconds",
        str(options.max_segment_seconds),
        "--gap-seconds",
        str(options.gap_seconds),
        "--identity-stills",
        str(options.identity_stills),
        "--scan-fps",
        str(options.scan_fps),
        "--validation-fps",
        str(options.validation_fps),
        "--face-confidence",
        str(options.face_confidence),
        "--speaker-confidence",
        str(options.speaker_confidence),
        "--workers",
        str(options.workers),
        "--device",
        options.device,
        "--resource-guard-percent",
        str(options.resource_guard_percent),
        "--resource-poll-seconds",
        str(options.resource_poll_seconds),
        "--resource-guard-timeout-seconds",
        str(options.resource_guard_timeout_seconds),
        "--max-download-height",
        str(options.max_download_height),
        "--video-cooldown-seconds",
        str(options.video_cooldown_seconds),
        "--max-affinity-cores",
        str(options.max_affinity_cores),
        "--native-threads",
        str(options.native_threads),
        "--cpu-throttle-high-percent",
        str(options.cpu_throttle_high_percent),
        "--cpu-throttle-low-percent",
        str(options.cpu_throttle_low_percent),
        "--ram-throttle-high-percent",
        str(options.ram_throttle_high_percent),
        "--ram-throttle-low-percent",
        str(options.ram_throttle_low_percent),
    ]
    if options.isolated_video_processes:
        command.append("--isolated-video-processes")
    if options.skip_completed_outputs:
        command.append("--skip-completed-outputs")
    if options.parallel_detectors:
        command.append("--parallel-detectors")
    if options.keep_debug:
        command.append("--keep-debug")
    if options.reference_audio:
        command.extend(["--reference-audio", str(Path(options.reference_audio).expanduser().resolve())])
    return command


def _clean_speaker_environment() -> dict[str, str]:
    source_environment = dict(os.environ)
    huggingface_token = next(
        (
            str(source_environment.get(name) or "").strip()
            for name in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN")
            if str(source_environment.get(name) or "").strip()
        ),
        "",
    )
    environment = credential_free_media_environment(source_environment)
    if huggingface_token:
        environment["HF_TOKEN"] = huggingface_token
    return environment


def _metadata_csv_bytes(
    catalog: SourceCatalog,
    entries: list[dict[str, object]],
    metadata_field_map: Mapping[str, str],
) -> bytes:
    core_fields = [
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
    ]
    handle = io.StringIO(newline="")
    writer = SpreadsheetSafeWriter(
        csv.DictWriter(handle, fieldnames=[*core_fields, *metadata_field_map.values()], extrasaction="ignore")
    )
    writer.writeheader()
    for entry in entries:
        system = entry["system_metadata"]
        output = entry["output_mapping"]
        row = {
            "SourceID": entry["source_id"],
            "Link": entry["link"],
            "ResolvedLink": entry["resolved_link"],
            "SourceKind": entry["source_kind"],
            "Speaker": entry["speaker"],
            "SpeakerDisplay": entry["speaker_display"],
            "Selected": str(entry["selected"]).lower(),
            "Status": entry["status"],
            "Title": system["title"],
            "DurationSeconds": system["duration_seconds"],
            "YouTubeLanguage": system["youtube_language"],
            "OutputDirectory": output["video_directory"],
        }
        row.update(
            {
                metadata_field_map[label]: entry["user_metadata"].get(label, "")
                for label in catalog.metadata_headers
            }
        )
        writer.writerow(row)
    return ("\ufeff" + handle.getvalue()).encode("utf-8")


def _metadata_export_field_map(metadata_headers: Sequence[str]) -> dict[str, str]:
    core_fields = (
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
    used = {_spreadsheet_header_key(field) for field in core_fields}
    result: dict[str, str] = {}
    for label in metadata_headers:
        candidate = label
        counter = 1
        while _spreadsheet_header_key(candidate) in used:
            counter += 1
            candidate = f"Metadata {counter}: {label}"
        result[label] = candidate
        used.add(_spreadsheet_header_key(candidate))
    return result


def _spreadsheet_header_key(value: str) -> str:
    return str(neutralize_spreadsheet_value(value)).casefold()


def _preflight_complete_pair(*items: tuple[Path, bytes]) -> None:
    present = tuple(_lexically_exists(path) for path, _content in items)
    if any(present) and not all(present):
        raise FileExistsError(
            "Immutable source sidecar pair is incomplete and has different content at the catalog run root"
        )


def _preflight_immutable_sidecars(*items: tuple[Path, bytes]) -> None:
    for path, content in items:
        if not _lexically_exists(path):
            continue
        if not _regular_file_matches(path, content):
            raise FileExistsError(f"Immutable source sidecar already exists with different content: {path}")


def _write_immutable_sidecar_pair(*items: tuple[Path, bytes]) -> None:
    _preflight_immutable_sidecars(*items)
    missing: list[tuple[Path, bytes]] = []
    for path, content in items:
        if not _lexically_exists(path):
            missing.append((path, content))
    if not missing:
        return

    staged: list[tuple[Path, Path, tuple[int, int]]] = []
    created: list[tuple[Path, tuple[int, int]]] = []
    try:
        for final_path, content in missing:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{final_path.name}.", suffix=".tmp", dir=final_path.parent
            )
            temp_path = Path(temp_name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                staged_identity = _file_identity(os.fstat(handle.fileno()))
            staged.append((temp_path, final_path, staged_identity))

        for temp_path, final_path, staged_identity in staged:
            if _lexically_exists(final_path):
                raise FileExistsError(f"Immutable source sidecar path appeared during publish: {final_path}")
            os.link(temp_path, final_path)
            created.append((final_path, staged_identity))
    except Exception:
        for final_path, staged_identity in reversed(created):
            if _path_has_identity(final_path, staged_identity):
                final_path.unlink()
        raise
    finally:
        for temp_path, _final_path, _identity in staged:
            if _lexically_exists(temp_path):
                temp_path.unlink()


def _regular_file_matches(path: Path, expected: bytes) -> bool:
    try:
        before = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(before.st_mode) or before.st_size != len(expected):
        return False
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or not _same_file_identity(before, opened):
                return False
            content = handle.read(len(expected) + 1)
            after = os.fstat(handle.fileno())
    except (FileNotFoundError, OSError):
        return False
    try:
        current = path.lstat()
    except FileNotFoundError:
        return False
    return (
        content == expected
        and _same_open_snapshot(opened, after)
        and _same_file_identity(opened, current)
    )


def _lexically_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _file_identity(details: os.stat_result) -> tuple[int, int]:
    return int(details.st_dev), int(details.st_ino)


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return _file_identity(left) == _file_identity(right)


def _same_open_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        _same_file_identity(left, right)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an ordered CSV/DOCX source catalog through procurement.")
    parser.add_argument("catalog", type=Path, help="CSV or DOCX source catalog.")
    parser.add_argument("--run-root", type=Path, required=True, help="Run root for immutable source sidecars and video outputs.")
    parser.add_argument("--mode", choices=["standard", "full", "manual", "clean-speaker-beta"], default="standard")
    parser.add_argument("--source-id", action="append", default=None, help="Selected source ID. Repeat for multiple rows.")
    parser.add_argument("--catalog-sha256", default="", help="SHA-256 recorded by the launcher scan.")
    parser.add_argument(
        "--allow-external-local-paths",
        action="store_true",
        help="Explicitly allow local catalog files outside the catalog directory; network and linked paths remain rejected.",
    )
    parser.add_argument("--percentage", type=float, default=0.10)
    parser.add_argument("--max-segment-seconds", type=int, default=30)
    parser.add_argument("--segments-json", type=Path, default=None)
    parser.add_argument("--manifest-sha256", default="")
    parser.add_argument("--expected-source", default="")
    parser.add_argument("--output-mode", choices=["clean", "percentage"], default="clean")
    parser.add_argument("--min-clean-seconds", type=float, default=10.0)
    parser.add_argument("--gap-seconds", type=float, default=0.5)
    parser.add_argument("--identity-stills", type=int, default=20)
    parser.add_argument("--scan-fps", type=float, default=1.0)
    parser.add_argument("--validation-fps", type=float, default=4.0)
    parser.add_argument("--face-confidence", type=float, default=0.65)
    parser.add_argument("--speaker-confidence", type=float, default=0.65)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--keep-debug", action="store_true")
    parser.add_argument("--resource-guard-percent", type=float, default=15.0)
    parser.add_argument("--resource-poll-seconds", type=float, default=15.0)
    parser.add_argument("--resource-guard-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--parallel-detectors", action="store_true")
    parser.add_argument("--reference-audio", type=Path, default=None)
    parser.add_argument("--only-video-id", action="append", default=[])
    parser.add_argument("--random-one", action="store_true")
    parser.add_argument("--random-seed", default="")
    parser.add_argument("--isolated-video-processes", action="store_true")
    parser.add_argument("--skip-first-videos", type=int, default=0)
    parser.add_argument("--skip-completed-outputs", action="store_true")
    parser.add_argument("--video-cooldown-seconds", type=float, default=60.0)
    parser.add_argument("--max-download-height", type=int, default=720)
    parser.add_argument("--max-affinity-cores", type=int, default=2)
    parser.add_argument("--native-threads", type=int, default=1)
    parser.add_argument("--cpu-throttle-high-percent", type=float, default=95.0)
    parser.add_argument("--cpu-throttle-low-percent", type=float, default=90.0)
    parser.add_argument("--ram-throttle-high-percent", type=float, default=95.0)
    parser.add_argument("--ram-throttle-low-percent", type=float, default=90.0)
    return parser


def _options_from_args(args: argparse.Namespace) -> CatalogRunOptions:
    return CatalogRunOptions(
        mode=args.mode,
        percentage=args.percentage,
        max_segment_seconds=args.max_segment_seconds,
        segments_json=str(args.segments_json.expanduser().resolve()) if args.segments_json else "",
        manifest_sha256=str(args.manifest_sha256).casefold(),
        expected_source=str(args.expected_source),
        output_mode=args.output_mode,
        min_clean_seconds=args.min_clean_seconds,
        gap_seconds=args.gap_seconds,
        identity_stills=args.identity_stills,
        scan_fps=args.scan_fps,
        validation_fps=args.validation_fps,
        face_confidence=args.face_confidence,
        speaker_confidence=args.speaker_confidence,
        workers=args.workers,
        device=args.device,
        keep_debug=args.keep_debug,
        resource_guard_percent=args.resource_guard_percent,
        resource_poll_seconds=args.resource_poll_seconds,
        resource_guard_timeout_seconds=args.resource_guard_timeout_seconds,
        parallel_detectors=args.parallel_detectors,
        reference_audio=str(args.reference_audio.expanduser().resolve()) if args.reference_audio else "",
        only_video_ids=tuple(args.only_video_id),
        random_one=args.random_one,
        random_seed=args.random_seed,
        isolated_video_processes=args.isolated_video_processes,
        skip_first_videos=args.skip_first_videos,
        skip_completed_outputs=args.skip_completed_outputs,
        video_cooldown_seconds=args.video_cooldown_seconds,
        max_download_height=args.max_download_height,
        max_affinity_cores=args.max_affinity_cores,
        native_threads=args.native_threads,
        cpu_throttle_high_percent=args.cpu_throttle_high_percent,
        cpu_throttle_low_percent=args.cpu_throttle_low_percent,
        ram_throttle_high_percent=args.ram_throttle_high_percent,
        ram_throttle_low_percent=args.ram_throttle_low_percent,
        allow_external_local_paths=args.allow_external_local_paths,
    )


def _default_metadata_fetcher(video_ids: list[str]) -> dict[str, dict[str, object]]:
    from application import backend

    api_key = backend.load_youtube_api_key()
    return backend.fetch_youtube_api_metadata(video_ids, api_key) if api_key else {}


def _default_local_metadata(source: CatalogSource) -> Mapping[str, object]:
    from application import backend

    return {
        "title": Path(source.resolved_link).stem,
        "duration_seconds": backend.read_duration_seconds(Path(source.resolved_link)) or "",
    }


def main() -> int:
    args = build_parser().parse_args()
    options = _options_from_args(args)
    run_catalog(
        args.catalog,
        args.run_root,
        mode=args.mode,
        selected_source_ids=args.source_id,
        expected_catalog_sha256=args.catalog_sha256,
        metadata_fetcher=_default_metadata_fetcher,
        local_metadata_fetcher=_default_local_metadata,
        options=options,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
