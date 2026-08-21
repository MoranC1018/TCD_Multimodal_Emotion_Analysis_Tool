"""Backend helpers for the local video processing launcher.

This module stays deliberately side-effect light: it scans inputs, normalises
metadata, and builds command lines. The HTTP launcher is responsible for
actually starting subprocesses.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from docx import Document
from procurement.catalog import POOLED_SPEAKER_LABEL, read_catalog
from procurement.input_limits import read_control_json
from procurement.video_sampling.full_video_download import make_filename_safe
from application import credential_store
from processing.audio_analysis.audio_pipeline.source_context import snapshot_run_sidecars

from analysis.audio import (
    discover_audio_analysis_inputs,
    read_audio_analysis_csv,
    read_audio_analysis_export,
)
from analysis.combined_summary import (
    AUDIO_METRICS,
    AUDIO_REQUIRED_METRICS,
    VIDEO_METRICS,
    InputError,
    Speaker,
    SpeakerGroupDefinition,
    canonical_metric,
    normalized,
    parse_sectioned_csv,
    resolve_speaker,
)
from analysis.histograms import (
    classify_histogram_columns,
    collect_numeric_values,
    filter_report_domain,
)
from analysis.imotions import (
    discover_csv_inputs,
    imotions_speaker_name,
    inspect_imotions_csv,
    read_imotions_csv,
)
from analysis.native_face import read_native_face_folder
from analysis.metadata import (
    find_source_manifest,
    load_source_metadata,
    resolve_analysis_profile,
    validate_source_manifest_associations,
    validate_text_profile_grouping,
)
from analysis.profile import AnalysisProfile, profile_payload
from analysis.text_results import TextResultsError, discover_text_results
from procurement.video_sampling import run_docx_extractions
from procurement.external_tools import (
    build_yt_dlp_command,
    credential_free_media_environment,
    resolve_media_binary,
    yt_dlp_is_available,
)


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
SKIP_FOLDER_NAMES = {"raw_clips", "__pycache__", ".git", ".venv", "venv", "node_modules"}
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_OEMBED_URL = "https://www.youtube.com/oembed"
PRODUCT_NAME = "Multimodal Emotion Analysis Tool"
DEFAULT_UI_SETTINGS: dict[str, object] = {
    "youtubeCookiesBrowser": "",
    "resourceLimitsEnabled": True,
    "maxCpuPercent": 90.0,
    "maxCpuCores": 0,
    "maxGpuPercent": 95.0,
    "ramLimitMode": "percent",
    "maxRamPercent": 90.0,
    "maxRamGb": 16.0,
    "nativeThreads": 1,
    "resourcePollSeconds": 2.0,
}
SECRET_SETTING_KEYS = {"youtubeApiKey", "huggingFaceToken"}
EULA_FILENAME = "eula.txt"
EULA_ACCEPTED_KEY = "terms_accepted"
WRAPPING_QUOTE_PAIRS = {
    '"': '"',
    "'": "'",
}
PERSISTENCE_LOCK = threading.RLock()
SETTINGS_WARNINGS: dict[str, str] = {}
MAX_METADATA_JSON_BYTES = 1024 * 1024
MAX_METADATA_JSON_ITEMS = 50_000
MAX_SETTINGS_JSON_BYTES = 64 * 1024
MAX_SETTINGS_JSON_ITEMS = 2048


@dataclass(frozen=True)
class VideoItem:
    """One video shown in the review UI, regardless of source type."""

    id: str
    title: str
    speaker: str
    source_path: str
    source_kind: str
    youtube_url: str = ""
    video_id: str = ""
    duration_seconds: float | None = None
    upload_date: str = ""
    license: str = "Unknown"
    relative_path: str = ""
    thumbnail_url: str = ""
    source_id: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    youtube_language: str = ""


@dataclass(frozen=True)
class FocusSourceIdentity:
    """Canonical identity shared by Focus validation and processing."""

    kind: str
    reference: str
    youtube_id: str = ""


def focus_source_identity(item: Mapping[str, object] | VideoItem) -> FocusSourceIdentity:
    """Return one strict file/folder/DOCX/YouTube identity for a Focus item."""

    def value(name: str) -> str:
        if isinstance(item, Mapping):
            raw_value = item.get(name)
        else:
            raw_value = getattr(item, name, "")
        return str(raw_value or "").strip()

    source_kind = value("source_kind").casefold()
    if source_kind not in {"file", "folder", "docx", "youtube"}:
        raise ValueError("Focus source_kind must be file, folder, docx, or youtube.")

    source_path = value("source_path")
    if source_kind in {"file", "folder"}:
        if not source_path:
            raise ValueError(f"Focus {source_kind} source_path must not be blank.")
        resolved = os.path.normcase(str(Path(source_path).expanduser().resolve()))
        return FocusSourceIdentity(source_kind, resolved)

    youtube_values = [value("video_id"), value("youtube_url")]
    if source_kind == "youtube":
        youtube_values.append(source_path)
    supplied = [candidate for candidate in youtube_values if candidate]
    video_ids = [
        candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else run_docx_extractions.get_youtube_video_id(candidate)
        for candidate in supplied
    ]
    if not supplied or any(not video_id for video_id in video_ids) or len(set(video_ids)) != 1:
        raise ValueError("Focus YouTube references must identify one matching video.")
    video_id = str(video_ids[0])

    if source_kind == "youtube":
        return FocusSourceIdentity("youtube", video_id, video_id)

    if not source_path:
        raise ValueError("Focus DOCX source_path must not be blank.")
    docx_path = Path(source_path).expanduser()
    if docx_path.suffix.casefold() != ".docx":
        raise ValueError("Focus DOCX source_path must identify a DOCX catalog.")
    resolved_docx = os.path.normcase(str(docx_path.resolve()))
    return FocusSourceIdentity("docx", resolved_docx, video_id)


def source_references_match(left: object, right: object) -> bool:
    """Compare one validated Focus source across URL and absolute-path forms."""

    left_text = clean_user_supplied_path(str(left or ""))
    right_text = clean_user_supplied_path(str(right or ""))
    if not left_text or not right_text:
        return False
    left_video_id = run_docx_extractions.get_youtube_video_id(left_text)
    right_video_id = run_docx_extractions.get_youtube_video_id(right_text)
    if left_video_id or right_video_id:
        return bool(left_video_id and right_video_id and left_video_id == right_video_id)
    return os.path.normcase(str(Path(left_text).expanduser().resolve())) == os.path.normcase(
        str(Path(right_text).expanduser().resolve())
    )


@dataclass(frozen=True)
class SpeakerGroup:
    """Videos grouped under the speaker label the user will review."""

    speaker: str
    videos: list[VideoItem]


@dataclass(frozen=True)
class ScanResult:
    """Normalised scan output for either a folder tree or DOCX source list."""

    source_path: str
    source_kind: str
    groups: list[SpeakerGroup]
    sources: list[VideoItem] = field(default_factory=list)
    catalog_sha256: str = ""
    catalog_format: str = ""
    metadata_headers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunRequest:
    """Procurement run options sent from the UI."""

    mode: str
    source_path: Path
    output_root: Path
    segment_manifest: Path | None = None
    segment_manifest_sha256: str = ""
    segment_expected_source: str = ""
    selected_ids: list[str] | None = None
    selected_speakers: list[str] | None = None
    catalog_sha256: str = ""
    internal_youtube_source: bool = False
    max_segment_seconds: int = 30
    percentage: float = 0.10
    beta_output_mode: str = "clean"
    beta_min_clean_seconds: float = 10.0
    beta_gap_seconds: float = 0.5
    beta_identity_stills: int = 20
    beta_scan_fps: float = 1.0
    beta_validation_fps: float = 4.0
    beta_face_confidence: float = 0.65
    beta_speaker_confidence: float = 0.65
    beta_worker_count: int = 1
    beta_device: str = "auto"
    beta_keep_debug: bool = False
    beta_resource_guard_percent: float = 15.0
    beta_resource_poll_seconds: float = 15.0
    beta_resource_guard_timeout_seconds: float = 900.0
    beta_parallel_detector_streams: bool = False
    beta_reference_audio: Path | None = None
    beta_max_download_height: int = 720
    beta_only_video_ids: list[str] | None = None
    beta_random_one: bool = False
    beta_random_seed: str = ""
    beta_isolated_video_processes: bool = True
    beta_skip_first_videos: int = 0
    beta_skip_completed_outputs: bool = True
    beta_video_cooldown_seconds: float = 60.0
    beta_max_affinity_cores: int = 2
    beta_native_threads: int = 1
    beta_cpu_throttle_high_percent: float = 95.0
    beta_cpu_throttle_low_percent: float = 90.0
    beta_ram_throttle_high_percent: float = 95.0
    beta_ram_throttle_low_percent: float = 90.0


@dataclass(frozen=True)
class AudioRunRequest:
    """Audio processing options sent from the UI."""

    mode: str
    source_path: Path
    output_root: Path
    window_seconds: float = 10.0
    stride_seconds: float = 5.0
    opensmile_feature_set: str = "egemaps"
    include_emotions: bool = True
    device: str = "auto"
    keep_temp_audio: bool = False
    debug: bool = False
    stop_on_error: bool = False
    selected_source_ids: tuple[str, ...] = ()
    catalog_sha256: str = ""


@dataclass(frozen=True)
class FaceProcessingRunRequest:
    """Native Py-Feat processing options sent from the UI."""

    source_path: Path
    output_root: Path
    sample_fps: float = 5.0
    confidence_threshold: float = 0.90
    batch_size: int = 8
    device: str = "auto"
    recursive: bool = True
    overwrite: bool = False
    debug: bool = False
    selected_source_ids: tuple[str, ...] = ()
    catalog_sha256: str = ""


@dataclass(frozen=True)
class TextProcessingRunRequest:
    """Native Whisper/RockSteady processing options sent from the UI."""

    source_path: Path
    output_root: Path
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_language: str = ""
    default_language_variant: str = "eng"
    dictionaries: tuple[str, ...] = ()
    dictionary_combination: str = "merge"
    categories: tuple[str, ...] = ()
    all_categories: bool = False
    threads: int = 1
    force_rocksteady: bool = False
    write_graphs: bool = True
    debug: bool = False
    selected_source_ids: tuple[str, ...] = ()
    catalog_sha256: str = ""


@dataclass(frozen=True)
class AnalysisRunRequest:
    """Statistical analysis options sent from the UI."""

    mode: str
    source_path: Path
    output_root: Path
    write_graphs: bool = True
    include_logscale: bool = False
    include_landmarks: bool = False
    include_timing: bool = False
    exclude_geometry: bool = False


@dataclass(frozen=True)
class AnalysisModalityRunRequest:
    """One input modality supplied to the combined analysis workflow."""

    name: str
    source_method: str
    source_path: Path


@dataclass(frozen=True)
class AnalysisSpeakerGroupRunRequest:
    """Launcher-owned speaker group compatible with the workflow definition."""

    group_id: str
    name: str
    speaker_ids: tuple[str, ...]

    def to_workflow_definition(self) -> SpeakerGroupDefinition:
        """Translate this immutable launcher request into the workflow type."""

        return SpeakerGroupDefinition(self.group_id, self.name, self.speaker_ids)


@dataclass(frozen=True)
class AnalysisWorkflowRunRequest:
    """Options for one combined iMotions and audio analysis workflow run."""

    output_root: Path
    modalities: tuple[AnalysisModalityRunRequest, ...]
    speaker_groups: tuple[AnalysisSpeakerGroupRunRequest, ...] = ()
    analysis_profile: AnalysisProfile | None = None
    write_combined_workbook: bool = True
    include_construct_comparison: bool = True
    include_probability_sheets: bool = True
    confidence_level: float = 0.95
    headline_policy: str = "weighted"
    default_reference: float = 0.0
    reference_overrides: Mapping[str, float] = field(default_factory=dict)
    write_graphs: bool = True
    include_logscale: bool = False
    include_landmarks: bool = False
    include_timing: bool = False
    exclude_geometry: bool = False


def discover_analysis_speakers(
    modalities: Iterable[AnalysisModalityRunRequest],
) -> dict[str, object]:
    """Find selectable canonical speakers without running an analysis pipeline."""

    available_in: dict[str, set[str]] = {}
    discovered_speakers: dict[str, Speaker] = {}
    warnings: list[str] = []
    by_name = {str(modality.name).casefold(): modality for modality in modalities}

    for name in ("imotions", "native_face", "audio", "text"):
        modality = by_name.get(name)
        if modality is None:
            continue
        source_method = str(modality.source_method).casefold()
        if name == "text":
            if source_method != "import":
                raise ValueError("Text results are import-only in Analysis.")
            try:
                discovery = discover_text_results(modality.source_path)
            except TextResultsError as exc:
                raise ValueError(f"Invalid imported Text results: {exc}") from exc
            for summary in discovery.summaries:
                _add_discovered_speaker(
                    summary.display_name,
                    name,
                    "imported text summary",
                    discovered_speakers,
                    available_in,
                    warnings,
                )
            continue
        if source_method == "import":
            report_modality = (
                "video" if name == "imotions" else "native_face" if name == "native_face" else "audio"
            )
            labels = _discover_imported_speaker_labels(modality.source_path, report_modality, name, warnings)
            for label in labels:
                _add_discovered_speaker(
                    label,
                    name,
                    f"imported {name} report",
                    discovered_speakers,
                    available_in,
                    warnings,
                )
            continue

        if name == "imotions":
            selected_paths, _ = discover_csv_inputs(modality.source_path)
            if not selected_paths:
                raise ValueError(f"No usable iMotions CSV inputs found under {modality.source_path}.")
            for path in selected_paths:
                try:
                    _, _, data_count = inspect_imotions_csv(path, "utf-8-sig")
                except ValueError as exc:
                    raise ValueError(f"Invalid iMotions CSV: {path}: {exc}") from exc
                if data_count <= 0:
                    raise ValueError(f"No usable iMotions data rows found in {path}.")
                _require_finite_emotion_metrics(path, "imotions", modality.source_path)
                label = imotions_speaker_name(path, modality.source_path)
                _add_discovered_speaker(
                    label,
                    name,
                    "iMotions speaker folder",
                    discovered_speakers,
                    available_in,
                    warnings,
                )
            continue

        if name == "native_face":
            try:
                exports = read_native_face_folder(modality.source_path)
            except (NotADirectoryError, ValueError) as exc:
                raise ValueError(f"Invalid Py-Feat / Native Face output: {exc}") from exc
            for export in exports:
                _add_discovered_speaker(
                    str(export.speaker or export.source),
                    name,
                    "Py-Feat / Native Face source",
                    discovered_speakers,
                    available_in,
                    warnings,
                )
            continue

        selected_paths, _, _ = discover_audio_analysis_inputs(modality.source_path)
        if not selected_paths:
            raise ValueError(f"No usable audio_analysis.csv inputs found under {modality.source_path}.")
        for path in selected_paths:
            audio_csv = read_audio_analysis_csv(path)
            if not audio_csv.header or len(audio_csv.rows) <= 0:
                raise ValueError(f"Invalid audio_analysis.csv with no usable rows: {path}")
            if not {"WindowIndex", "StartSeconds"}.issubset(audio_csv.header):
                raise ValueError(f"Invalid audio_analysis.csv missing required columns: {path}")
            label = audio_csv.metadata.get("SpeakerName", "").strip()
            if not label:
                label = str(audio_csv.rows[0].get("SpeakerName", "")).strip()
            if not label:
                raise ValueError(f"Invalid audio_analysis.csv missing a speaker name: {path}")
            _require_finite_emotion_metrics(path, "audio", modality.source_path)
            _add_discovered_speaker(
                label,
                name,
                "Audio speaker",
                discovered_speakers,
                available_in,
                warnings,
            )

    ordered_ids = sorted(
        available_in,
        key=lambda speaker_id: (
            discovered_speakers[speaker_id].display_name.casefold(),
            speaker_id,
        ),
    )

    return {
        "speakers": [
            {
                "key": speaker.speaker_id,
                "name": speaker.display_name,
                "availableIn": [
                    name
                    for name in ("imotions", "audio", "text")
                    if name in available_in[speaker.speaker_id]
                ],
            }
            for speaker_id in ordered_ids
            for speaker in (discovered_speakers[speaker_id],)
        ],
        "warnings": warnings,
    }


def discover_analysis_profile_context(
    modalities: Iterable[AnalysisModalityRunRequest],
    *,
    source_manifest: Path | None = None,
) -> dict[str, object]:
    """Describe reusable metadata choices for the source run behind Analysis inputs."""

    modality_paths = tuple(modality.source_path for modality in modalities)
    manifest_path = (
        Path(source_manifest).expanduser().resolve()
        if source_manifest is not None
        else find_source_manifest(modality_paths)
    )
    metadata = load_source_metadata(manifest_path)
    validate_source_manifest_associations(
        modality_paths,
        metadata.manifest_path,
        metadata.manifest_sha256,
    )
    selected_sources = tuple(source for source in metadata.sources if source.selected)
    sources_by_speaker: dict[str, list[str]] = {}
    speaker_names: dict[str, str] = {}
    for source in selected_sources:
        sources_by_speaker.setdefault(source.speaker_key, []).append(source.source_id)
        speaker_names.setdefault(source.speaker_key, source.speaker)
    return {
        "sourceManifest": str(metadata.manifest_path),
        "sourceManifestSha256": metadata.manifest_sha256,
        "metadataFields": [
            {"name": field, "values": list(metadata.distinct_values(field))}
            for field in metadata.fields
        ],
        "speakers": [
            {
                "id": speaker_id,
                "name": speaker_names[speaker_id],
                "sourceIds": source_ids,
            }
            for speaker_id, source_ids in sources_by_speaker.items()
        ],
        "sources": [
            {
                "id": source.source_id,
                "title": source.title,
                "speakerId": source.speaker_key,
                "speaker": source.speaker,
                "metadata": dict(source.user_metadata),
            }
            for source in selected_sources
        ],
    }


def _require_finite_emotion_metrics(path: Path, modality: str, input_root: Path) -> None:
    """Apply the analyser's emotion-domain rules before offering a speaker."""

    if modality == "audio":
        export = read_audio_analysis_export(path)
        required = AUDIO_REQUIRED_METRICS
    else:
        export = read_imotions_csv(path, input_root=input_root)
        required = VIDEO_METRICS
    numeric_values = collect_numeric_values(export)
    classifications = classify_histogram_columns(
        export,
        numeric_values,
        include_landmarks=False,
        include_timing=False,
        exclude_geometry=False,
    )
    emotion_values, _ = filter_report_domain(
        export,
        numeric_values,
        classifications,
        "emotion",
    )
    available: set[str] = set()
    for column, values in emotion_values.items():
        if not any(math.isfinite(float(value)) for value in values):
            continue
        info = export.info[column]
        for candidate in (info.label, info.original_name, column):
            try:
                metric = canonical_metric(candidate)
            except InputError:
                continue
            if metric in required:
                available.add(metric)
                break
    missing = [metric for metric in required if metric not in available]
    if missing:
        display = "Audio" if modality == "audio" else "iMotions"
        raise ValueError(
            f"{display} input cannot produce speaker-level combined emotion reports; "
            f"required finite emotion metrics are missing in {path}: {', '.join(missing)}"
        )


def _add_discovered_speaker(
    label: str,
    modality: str,
    context: str,
    discovered_speakers: dict[str, Speaker],
    available_in: dict[str, set[str]],
    warnings: list[str],
) -> None:
    try:
        speaker = resolve_speaker(label)
    except InputError as exc:
        warnings.append(f"Unrecognized {context}: {label} ({exc})")
        return
    discovered_speakers.setdefault(speaker.speaker_id, speaker)
    available_in.setdefault(speaker.speaker_id, set()).add(modality)


def _discover_imported_speaker_labels(
    root: Path,
    report_modality: str,
    source_name: str,
    warnings: list[str],
) -> list[str]:
    root_path = root.expanduser().resolve()
    grouped: dict[str, list[tuple[str, Path]]] = {}
    speakers: dict[str, Speaker] = {}
    for path in sorted(root_path.rglob("descriptive_statistics.csv"), key=lambda item: str(item).casefold()):
        label = _imported_report_speaker_label(root_path, path)
        if label is None:
            continue
        try:
            speaker = resolve_speaker(label)
        except InputError as exc:
            warnings.append(f"Unrecognized imported {source_name} speaker: {label} ({exc})")
            continue
        _validate_imported_report(path, report_modality)
        speakers.setdefault(speaker.speaker_id, speaker)
        grouped.setdefault(speaker.speaker_id, []).append((label, path))

    selected: dict[str, str] = {}
    ordered_ids = sorted(
        grouped,
        key=lambda speaker_id: (
            speakers[speaker_id].display_name.casefold(),
            speaker_id,
        ),
    )
    for speaker_id in ordered_ids:
        speaker = speakers[speaker_id]
        options = grouped.get(speaker.speaker_id, [])
        if len(options) > 1:
            canonical = [option for option in options if normalized(option[0]) == normalized(speaker.display_name)]
            if len(canonical) != 1:
                paths = ", ".join(str(option[1]) for option in options)
                raise InputError(f"Ambiguous duplicate reports for {speaker.speaker_id}: {paths}")
        if options:
            selected[speaker.speaker_id] = speaker.display_name
    return [selected[speaker_id] for speaker_id in ordered_ids if speaker_id in selected]


def _imported_report_speaker_label(root_path: Path, path: Path) -> str | None:
    relative = path.relative_to(root_path)
    if len(relative.parts) == 5:
        domain, supplied_speaker, combined, findings, filename = relative.parts
    elif len(relative.parts) == 4 and normalized(root_path.parent.name) == "emotion":
        domain = "emotion"
        supplied_speaker, combined, findings, filename = relative.parts
    else:
        return None
    ignored = ("temp", "tmp", "cache", "debug", "raw")
    if (
        normalized(domain) != "emotion"
        or normalized(combined) != "combined"
        or normalized(findings) != "otherfindings"
        or filename.casefold() != "descriptive_statistics.csv"
        or any(marker in normalized(part) for part in relative.parts for marker in ignored)
    ):
        return None
    return supplied_speaker


def _validate_imported_report(path: Path, modality: str) -> None:
    metrics = parse_sectioned_csv(path)
    required = AUDIO_REQUIRED_METRICS if modality == "audio" else VIDEO_METRICS
    missing = [metric for metric in required if metric not in metrics]
    if missing:
        raise InputError(f"{path}: missing required {modality} metrics: {', '.join(missing)}")
    expected_sources = metrics[required[0]].sources
    for metric in required[1:]:
        if metrics[metric].sources != expected_sources:
            raise InputError(f"{path}: required metric source order changes at {metric}")


def scan_input_source(
    source_path: str | Path,
    *,
    duration_reader: Callable[[Path], float | None] | None = None,
    enrich_youtube: bool = True,
    logger: Callable[[str], None] | None = None,
) -> ScanResult:
    """Scan a YouTube URL, DOCX list, local video, or folder into one UI shape."""

    raw_source = clean_user_supplied_path(source_path)
    if run_docx_extractions.get_youtube_video_id(raw_source):
        return scan_youtube_source(raw_source, enrich_youtube=enrich_youtube, logger=logger)

    path = Path(raw_source).expanduser().resolve()
    if path.suffix.casefold() in {".csv", ".docx"}:
        return scan_catalog_source(
            path,
            duration_reader=duration_reader,
            enrich_youtube=enrich_youtube,
            logger=logger,
        )
    if path.suffix.casefold() in VIDEO_EXTENSIONS:
        return scan_single_video_source(path, duration_reader=duration_reader)
    if path.exists() and path.is_file():
        supported = ", ".join(sorted(VIDEO_EXTENSIONS))
        raise ValueError(
            f"Unsupported input file type '{path.suffix or '(none)'}'. "
            f"Supported videos: {supported}; catalogs: .csv or .docx."
        )
    return scan_folder_source(path, duration_reader=duration_reader)


def scan_youtube_source(
    youtube_url: str,
    *,
    enrich_youtube: bool = True,
    logger: Callable[[str], None] | None = None,
) -> ScanResult:
    """Create the review model for one directly pasted YouTube URL."""

    canonical_url = run_docx_extractions.normalise_youtube_url(youtube_url)
    if not canonical_url:
        raise ValueError("The supplied YouTube URL does not contain a valid video ID.")
    video_id = run_docx_extractions.get_youtube_video_id(canonical_url) or ""
    item = VideoItem(
        id=f"youtube:{video_id}",
        title=clean_display_title(canonical_url, canonical_url),
        speaker="YouTube",
        source_path=canonical_url,
        source_kind="youtube",
        youtube_url=canonical_url,
        video_id=video_id,
        license="Unknown",
        relative_path=canonical_url,
        thumbnail_url=youtube_thumbnail_url(video_id),
    )
    items = enrich_youtube_items([item], logger=logger) if enrich_youtube else [item]
    if enrich_youtube and (
        items[0].duration_seconds is None or title_looks_like_youtube_reference(items[0].title)
    ):
        details = fetch_youtube_ytdlp_metadata(canonical_url)
        if details:
            items = apply_youtube_metadata(items, {video_id: details})
    return ScanResult(
        source_path=canonical_url,
        source_kind="youtube",
        groups=[SpeakerGroup(speaker="YouTube", videos=items)],
    )


def clean_user_supplied_path(value: str | Path) -> str:
    """Return a path string suitable for Path(...) from pasted UI text.

    Windows users often copy paths with surrounding quotes. A shell treats
    those quotes as syntax, but the browser sends them as literal characters,
    so remove only wrapping quote pairs before resolving the path.
    """

    text = str(value or "").strip()
    while len(text) >= 2:
        first = text[0]
        expected_last = WRAPPING_QUOTE_PAIRS.get(first)
        if expected_last is None or text[-1] != expected_last:
            break
        text = text[1:-1].strip()
    return text


def scan_folder_source(
    folder: Path,
    *,
    duration_reader: Callable[[Path], float | None] | None = None,
) -> ScanResult:
    """Scan local video files while preserving the first folder as speaker."""

    if not folder.exists() or not folder.is_dir():
        raise NotADirectoryError(f"Folder does not exist: {folder}")

    duration_reader = duration_reader or read_duration_seconds
    items: list[VideoItem] = []
    for video_path in sorted(iter_video_files(folder), key=lambda item: str(item).casefold()):
        metadata = read_nearby_metadata(video_path)
        relative_path = video_path.relative_to(folder)
        speaker = speaker_from_relative_path(folder, relative_path)
        title = str(metadata.get("title") or metadata.get("video_title") or video_path.stem)
        youtube_url = str(metadata.get("url") or metadata.get("webpage_url") or "")
        video_id = str(metadata.get("video_id") or run_docx_extractions.get_youtube_video_id(youtube_url or "") or "")
        upload_date = str(metadata.get("upload_date") or metadata.get("published_at") or metadata.get("uploadDate") or "")
        license_text = str(metadata.get("license") or metadata.get("licence") or metadata.get("license_text") or "Local file / unknown")
        video_duration = metadata_duration_seconds(metadata)
        item = VideoItem(
            id=f"folder:{relative_path.as_posix()}",
            title=title,
            speaker=speaker,
            source_path=str(video_path),
            source_kind="folder",
            youtube_url=youtube_url,
            video_id=video_id,
            duration_seconds=video_duration if video_duration is not None else duration_reader(video_path),
            upload_date=upload_date,
            license=license_text,
            relative_path=relative_path.as_posix(),
            thumbnail_url=youtube_thumbnail_url(video_id),
        )
        items.append(item)

    if not items:
        supported = ", ".join(sorted(VIDEO_EXTENSIONS))
        raise ValueError(f"No supported videos were found under {folder}. Supported formats: {supported}.")

    return ScanResult(
        source_path=str(folder),
        source_kind="folder",
        groups=group_video_items_by_speaker(items),
    )


def scan_single_video_source(
    video_path: Path,
    *,
    duration_reader: Callable[[Path], float | None] | None = None,
) -> ScanResult:
    """Scan one local video file for quick regression runs and ad hoc UI use."""

    if not video_path.exists() or not video_path.is_file():
        raise FileNotFoundError(f"Video file does not exist: {video_path}")
    if video_path.suffix.casefold() not in VIDEO_EXTENSIONS:
        raise ValueError(f"Unsupported video file type: {video_path}")

    duration_reader = duration_reader or read_duration_seconds
    metadata = read_nearby_metadata(video_path)
    title = str(metadata.get("title") or metadata.get("video_title") or video_path.stem)
    youtube_url = str(metadata.get("url") or metadata.get("webpage_url") or "")
    video_id = str(metadata.get("video_id") or run_docx_extractions.get_youtube_video_id(youtube_url or "") or "")
    upload_date = str(metadata.get("upload_date") or metadata.get("published_at") or metadata.get("uploadDate") or "")
    license_text = str(metadata.get("license") or metadata.get("licence") or metadata.get("license_text") or "Local file / unknown")
    video_duration = metadata_duration_seconds(metadata)
    speaker = video_path.parent.name if video_path.parent.name else "Local Video"
    item = VideoItem(
        id=f"file:{video_path.name}",
        title=title,
        speaker=speaker,
        source_path=str(video_path),
        source_kind="file",
        youtube_url=youtube_url,
        video_id=video_id,
        duration_seconds=video_duration if video_duration is not None else duration_reader(video_path),
        upload_date=upload_date,
        license=license_text,
        relative_path=video_path.name,
        thumbnail_url=youtube_thumbnail_url(video_id),
    )

    return ScanResult(
        source_path=str(video_path),
        source_kind="file",
        groups=[SpeakerGroup(speaker=speaker, videos=[item])],
    )


def scan_docx_source(
    docx_path: Path,
    *,
    enrich_youtube: bool = True,
    logger: Callable[[str], None] | None = None,
) -> ScanResult:
    """Compatibility-named entry point using the shared catalog parser."""

    return scan_catalog_source(
        docx_path,
        enrich_youtube=enrich_youtube,
        logger=logger,
    )


def scan_catalog_source(
    catalog_path: Path,
    *,
    duration_reader: Callable[[Path], float | None] | None = None,
    enrich_youtube: bool = True,
    logger: Callable[[str], None] | None = None,
) -> ScanResult:
    """Read CSV/DOCX rows into one ordered UI model without changing selection."""

    log = logger or (lambda _message: None)
    catalog = read_catalog(catalog_path)
    duration_reader = duration_reader or read_duration_seconds
    items: list[VideoItem] = []
    for source in catalog.sources:
        if source.source_kind == "youtube":
            item = VideoItem(
                id=source.source_id,
                source_id=source.source_id,
                title=source.resolved_link,
                speaker=source.speaker_display,
                source_path=source.resolved_link,
                source_kind="youtube",
                youtube_url=source.resolved_link,
                video_id=source.youtube_id,
                license="Unknown",
                relative_path=f"catalog row {source.row_number}",
                thumbnail_url=youtube_thumbnail_url(source.youtube_id),
                metadata=dict(source.metadata),
            )
        else:
            local_path = Path(source.resolved_link)
            item = VideoItem(
                id=source.source_id,
                source_id=source.source_id,
                title=local_path.stem,
                speaker=source.speaker_display,
                source_path=str(local_path),
                source_kind="file",
                duration_seconds=duration_reader(local_path),
                license="Local file / unknown",
                relative_path=source.link,
                metadata=dict(source.metadata),
            )
        items.append(item)

    if enrich_youtube:
        items = enrich_youtube_items(items, logger=log)
    groups = group_video_items_by_speaker(items)
    return ScanResult(
        source_path=str(catalog.path),
        source_kind="catalog",
        groups=groups,
        sources=items,
        catalog_sha256=catalog.sha256,
        catalog_format=catalog.format,
        metadata_headers=list(catalog.metadata_headers),
    )


def scan_audio_catalog_run(source_path: Path) -> ScanResult | None:
    """Reopen the immutable catalog manifest belonging to one audio batch root."""

    run_root = source_path.expanduser().resolve(strict=True)
    if not run_root.is_dir():
        raise ValueError(f"Audio catalog source must be a folder: {run_root}")
    pair = snapshot_run_sidecars(run_root)
    if pair is None:
        return None
    try:
        manifest = json.loads(pair[0].decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid source manifest JSON: {run_root / 'source_manifest.json'}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"Source manifest must be a JSON object: {run_root / 'source_manifest.json'}")
    catalog = manifest.get("catalog")
    raw_sources = manifest.get("sources")
    if not isinstance(catalog, dict) or not isinstance(raw_sources, list):
        raise ValueError(f"Catalog source manifest has an invalid structure: {run_root / 'source_manifest.json'}")
    catalog_sha256 = str(catalog.get("sha256") or "").strip().casefold()
    if re.fullmatch(r"[0-9a-f]{64}", catalog_sha256) is None:
        raise ValueError(f"Catalog source manifest has an invalid catalog digest: {run_root / 'source_manifest.json'}")

    metadata_headers: list[str] = []
    seen_headers: set[str] = set()

    def add_metadata_header(raw_header: object) -> None:
        if not isinstance(raw_header, str) or not raw_header.strip():
            raise ValueError(f"Catalog source manifest has an invalid metadata header: {run_root / 'source_manifest.json'}")
        header = raw_header.strip()
        if header not in seen_headers:
            seen_headers.add(header)
            metadata_headers.append(header)

    raw_headers = catalog.get("metadata_headers", [])
    if not isinstance(raw_headers, list):
        raise ValueError(f"Catalog source manifest metadata_headers must be a list: {run_root / 'source_manifest.json'}")
    for raw_header in raw_headers:
        add_metadata_header(raw_header)

    items: list[VideoItem] = []
    seen_source_ids: set[str] = set()
    for raw_entry in raw_sources:
        if not isinstance(raw_entry, dict) or not bool(raw_entry.get("selected")):
            continue
        source_id = str(raw_entry.get("source_id") or "").strip()
        if re.fullmatch(r"source-\d{4,6}", source_id) is None or source_id in seen_source_ids:
            raise ValueError(
                f"Catalog source manifest has invalid or duplicate selected SourceIDs: {run_root / 'source_manifest.json'}"
            )
        seen_source_ids.add(source_id)
        source_kind = str(raw_entry.get("source_kind") or "").strip().casefold()
        if source_kind not in {"local", "youtube"}:
            raise ValueError(f"Catalog source manifest has an invalid source kind for {source_id}")
        speaker = raw_entry.get("speaker_display")
        resolved_link = raw_entry.get("resolved_link")
        system_metadata = raw_entry.get("system_metadata")
        user_metadata = raw_entry.get("user_metadata")
        if not isinstance(speaker, str) or not speaker.strip():
            raise ValueError(f"Catalog source manifest has no speaker display for {source_id}")
        if not isinstance(resolved_link, str) or not resolved_link.strip():
            raise ValueError(f"Catalog source manifest has no resolved link for {source_id}")
        if not isinstance(system_metadata, dict):
            raise ValueError(f"Catalog source manifest has invalid system metadata for {source_id}")
        if not isinstance(user_metadata, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in user_metadata.items()
        ):
            raise ValueError(f"Catalog source manifest has invalid user metadata for {source_id}")
        for header in user_metadata:
            add_metadata_header(header)

        raw_duration = system_metadata.get("duration_seconds")
        duration = (
            float(raw_duration)
            if isinstance(raw_duration, (int, float))
            and not isinstance(raw_duration, bool)
            and math.isfinite(float(raw_duration))
            and float(raw_duration) >= 0
            else None
        )
        youtube = raw_entry.get("youtube") if source_kind == "youtube" else None
        if source_kind == "youtube" and not isinstance(youtube, dict):
            raise ValueError(f"Catalog source manifest has invalid YouTube metadata for {source_id}")
        video_id = str(youtube.get("video_id") or "") if isinstance(youtube, dict) else ""
        youtube_url = str(youtube.get("url") or resolved_link) if isinstance(youtube, dict) else ""
        title = str(system_metadata.get("title") or Path(resolved_link).stem or source_id).strip()
        items.append(
            VideoItem(
                id=source_id,
                source_id=source_id,
                title=title,
                speaker=speaker.strip(),
                source_path=resolved_link,
                source_kind="youtube" if source_kind == "youtube" else "file",
                youtube_url=youtube_url,
                video_id=video_id,
                duration_seconds=duration,
                relative_path=source_id,
                thumbnail_url=youtube_thumbnail_url(video_id),
                metadata=dict(user_metadata),
                youtube_language=str(system_metadata.get("youtube_language") or ""),
            )
        )

    return ScanResult(
        source_path=str(run_root),
        source_kind="catalog",
        groups=group_video_items_by_speaker(items),
        sources=items,
        catalog_sha256=catalog_sha256,
        catalog_format=str(catalog.get("format") or ""),
        metadata_headers=metadata_headers,
    )


def group_video_items_by_speaker(items: Iterable[VideoItem]) -> list[SpeakerGroup]:
    """Merge labels that differ only by case or repeated whitespace."""

    labels: dict[str, str] = {}
    videos_by_key: dict[str, list[VideoItem]] = {}
    for item in items:
        display_label = " ".join(str(item.speaker or "Unknown Speaker").split()) or "Unknown Speaker"
        key = run_docx_extractions.speaker_match_key(display_label)
        labels.setdefault(key, display_label)
        videos_by_key.setdefault(key, []).append(item)
    return [
        SpeakerGroup(speaker=labels[key], videos=videos_by_key[key])
        for key in sorted(videos_by_key, key=lambda value: labels[value].casefold())
    ]


def iter_video_files(folder: Path) -> Iterable[Path]:
    for path in folder.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in VIDEO_EXTENSIONS:
            continue
        if any(part.casefold() in SKIP_FOLDER_NAMES for part in path.relative_to(folder).parts):
            continue
        yield path


def speaker_from_relative_path(root: Path, relative_path: Path) -> str:
    if len(relative_path.parts) > 1:
        return relative_path.parts[0]
    return root.name


def read_nearby_metadata(video_path: Path) -> dict[str, object]:
    """Load sidecar metadata written by procurement/audio tools when present."""

    specific_sidecar = video_path.with_suffix(".json")
    if specific_sidecar.exists():
        try:
            data = read_control_json(
                specific_sidecar,
                label="metadata",
                max_bytes=MAX_METADATA_JSON_BYTES,
                max_items=MAX_METADATA_JSON_ITEMS,
            )
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            return data

    candidates = [
        video_path.parent / "extraction_metadata.json",
        video_path.parent / "audio_analysis_manifest.json",
        video_path.parent / "metadata.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            data = read_control_json(
                candidate,
                label="metadata",
                max_bytes=MAX_METADATA_JSON_BYTES,
                max_items=MAX_METADATA_JSON_ITEMS,
            )
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and metadata_matches_video(data, video_path):
            return data
    return {}


def metadata_matches_video(metadata: dict[str, object], video_path: Path) -> bool:
    """Require generic folder metadata to identify the adjacent video."""

    references = [
        metadata.get(key)
        for key in (
            "input_video",
            "source_video",
            "source_path",
            "output_video",
            "filepath",
            "filename",
            "_filename",
        )
        if metadata.get(key)
    ]
    resolved_video = video_path.expanduser().resolve()
    for reference in references:
        candidate = Path(str(reference)).expanduser()
        if candidate.name.casefold() == resolved_video.name.casefold():
            return True
        try:
            if candidate.resolve() == resolved_video:
                return True
        except OSError:
            continue

    video_id = str(metadata.get("video_id") or "").strip()
    if video_id and video_id.casefold() in resolved_video.stem.casefold():
        return True

    adjacent_videos = [
        path
        for path in video_path.parent.iterdir()
        if path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS
    ]
    return len(adjacent_videos) == 1 and adjacent_videos[0].resolve() == resolved_video


def metadata_duration_seconds(metadata: dict[str, object]) -> float | None:
    for key in ("duration_seconds", "duration", "video_duration", "length_seconds"):
        if key not in metadata:
            continue
        value = metadata.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        parsed = parse_duration_seconds(str(value or ""))
        if parsed is not None:
            return parsed
    return None


def read_duration_seconds(video_path: Path) -> float | None:
    """Best-effort duration lookup for local files using ffprobe."""

    command = [
        str(resolve_media_binary("ffprobe", excluded_roots=(video_path.parent,))),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            env=credential_free_media_environment(),
        )
        return float(completed.stdout.strip())
    except Exception:
        return None


def header_map_for_rows(table_rows) -> dict[str, int]:
    """Build a normalised header map from an already materialised row list."""

    if not table_rows:
        return {}
    return {normalise_header(cell.text): index for index, cell in enumerate(table_rows[0].cells)}


def header_map_for_table(table) -> dict[str, int]:
    return header_map_for_rows(list(table.rows))


def cell_text_by_header(row, header_map: dict[str, int], names: list[str]) -> str:
    for name in names:
        index = header_map.get(normalise_header(name))
        if index is not None and index < len(row.cells):
            value = row.cells[index].text.strip()
            if value:
                return value
    return ""


def normalise_header(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def parse_duration_seconds(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    parts = text.split(":")
    if len(parts) in {2, 3} and all(part.strip().isdigit() for part in parts):
        numbers = [int(part) for part in parts]
        if len(numbers) == 2:
            minutes, seconds = numbers
            return float(minutes * 60 + seconds)
        hours, minutes, seconds = numbers
        return float(hours * 3600 + minutes * 60 + seconds)
    match = re.search(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?", text, flags=re.IGNORECASE)
    if match and any(match.groups()):
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return float(hours * 3600 + minutes * 60 + seconds)
    return None


def first_non_empty(*values: str) -> str:
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return ""


def clean_display_title(title: str, fallback_url: str) -> str:
    cleaned = " ".join(str(title or "").split())
    if cleaned and not run_docx_extractions.get_youtube_video_id(cleaned):
        return cleaned
    video_id = run_docx_extractions.get_youtube_video_id(cleaned or fallback_url or "")
    if video_id:
        return f"Title unavailable [{video_id}]"
    return cleaned or "Untitled video"


def title_looks_like_youtube_reference(title: str) -> bool:
    cleaned = str(title or "").strip()
    if not cleaned:
        return True
    if run_docx_extractions.get_youtube_video_id(cleaned):
        return True
    folded = cleaned.casefold()
    return (
        folded in {"link", "video", "youtube"}
        or folded.startswith("youtube video ")
        or folded.startswith("title unavailable [")
    )


def parse_youtube_iso8601_duration(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", text)
    if not match or not any(match.groups()):
        return None
    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    seconds = int(match.group(4) or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def load_youtube_api_key(config_path: Path | None = None, settings_path: Path | None = None) -> str:
    """Read the YouTube API key from the environment or Windows-protected storage."""

    env_value = str(os.getenv("YOUTUBE_API_KEY") or "").strip()
    if env_value:
        return strip_env_value(env_value)

    settings_path = settings_path or ui_settings_path(Path(__file__).resolve().parents[1])
    _ = config_path  # Retained for API compatibility; plaintext config fallback is intentionally disabled.
    load_ui_settings_from_path(settings_path)
    return strip_env_value(credential_store.load_secret(settings_path, "youtubeApiKey"))


def load_huggingface_token(settings_path: Path | None = None) -> str:
    """Read an optional free Hugging Face token for gated model downloads."""

    for env_name in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        env_value = str(os.getenv(env_name) or "").strip()
        if env_value:
            return strip_env_value(env_value)

    settings_path = settings_path or ui_settings_path(Path(__file__).resolve().parents[1])
    load_ui_settings_from_path(settings_path)
    return strip_env_value(credential_store.load_secret(settings_path, "huggingFaceToken"))


def strip_env_value(value: str) -> str:
    return str(value or "").strip().strip('"').strip("'")


def eula_path(repo_root: Path) -> Path:
    """Return the local Minecraft-style terms file path."""

    return repo_root.expanduser().resolve() / "_local" / EULA_FILENAME


def load_eula_state(repo_root: Path, *, now: datetime | None = None) -> dict[str, object]:
    """Read terms acceptance from the local EULA file.

    The file defaults to false. If a user manually sets the flag to true, the
    next read stamps the file with the acceptance time for a simple audit trail.
    """

    path = eula_path(repo_root)
    if not path.exists():
        write_eula_state(repo_root, False, accepted_at="")
        return eula_state_payload(path, False, "")

    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return eula_state_payload(path, False, "")

    accepted = False
    accepted_at = ""
    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue
        if cleaned.startswith("#") and "accepted_at=" in cleaned:
            accepted_at = cleaned.split("accepted_at=", 1)[1].strip()
            continue
        if "=" not in cleaned or cleaned.startswith("#"):
            continue
        key, value = cleaned.split("=", 1)
        if normalise_header(key).replace(" ", "_") == EULA_ACCEPTED_KEY:
            accepted = strip_env_value(value).casefold() == "true"

    if accepted and not accepted_at:
        accepted_at = iso_timestamp(now)
        write_eula_state(repo_root, True, accepted_at=accepted_at)
    return eula_state_payload(path, accepted, accepted_at if accepted else "")


def write_eula_state(repo_root: Path, accepted: bool, *, accepted_at: str | None = None) -> dict[str, object]:
    """Write the EULA file in a format users can inspect and edit manually."""

    path = eula_path(repo_root)
    timestamp = accepted_at if accepted_at is not None else iso_timestamp()
    if not accepted:
        timestamp = ""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {PRODUCT_NAME} EULA",
        "# Set terms_accepted=true to confirm you have permission to process the selected media and derived data.",
        f"# data: accepted_at={timestamp}",
        f"{EULA_ACCEPTED_KEY}={'true' if accepted else 'false'}",
    ]
    atomic_write_text(path, "\n".join(lines) + "\n")
    return eula_state_payload(path, accepted, timestamp)


def eula_state_payload(path: Path, accepted: bool, accepted_at: str) -> dict[str, object]:
    """Return the JSON shape shared by startup checks and the frontend."""

    return {"termsAccepted": accepted, "acceptedAt": accepted_at, "eulaPath": str(path)}


def terms_are_accepted(repo_root: Path) -> bool:
    return bool(load_eula_state(repo_root).get("termsAccepted"))


def iso_timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ui_settings_path(repo_root: Path) -> Path:
    """Return the local-only settings file used by the launcher UI."""

    return repo_root.expanduser().resolve() / "_local" / "ui_settings.json"


def load_ui_settings(repo_root: Path) -> dict[str, object]:
    """Read persisted launcher settings, returning safe defaults if absent."""

    return load_ui_settings_from_path(ui_settings_path(repo_root))


def load_ui_settings_from_path(path: Path) -> dict[str, object]:
    with PERSISTENCE_LOCK:
        purged_files = migrate_legacy_settings_secrets(path)
        warning_key = str(path.resolve())
        if purged_files:
            SETTINGS_WARNINGS[warning_key] = (
                "Unsafe or unreadable legacy settings were purged from "
                + ", ".join(purged_files)
                + "; safe settings remain active."
            )
        if not path.exists():
            if warning_key not in SETTINGS_WARNINGS:
                SETTINGS_WARNINGS.pop(warning_key, None)
            return dict(DEFAULT_UI_SETTINGS)
        data = read_json_object(path)
        if data is not None:
            if not SETTINGS_WARNINGS.get(warning_key, "").startswith("Unsafe or unreadable legacy settings"):
                SETTINGS_WARNINGS.pop(warning_key, None)
            return normalise_ui_settings(data)

        backup_path = settings_backup_path(path)
        backup = read_json_object(backup_path)
        if backup is not None:
            SETTINGS_WARNINGS[warning_key] = (
                f"Settings were recovered from {backup_path.name} because {path.name} was unreadable."
            )
            return normalise_ui_settings(backup)

        SETTINGS_WARNINGS[warning_key] = (
            f"{path.name} is unreadable and no valid backup exists; safe defaults are active."
        )
        return dict(DEFAULT_UI_SETTINGS)


def save_ui_settings(repo_root: Path, updates: dict[str, object]) -> dict[str, object]:
    """Persist nonsecret settings and store credentials with Windows DPAPI."""

    validate_ui_settings_updates(updates)
    settings_path = ui_settings_path(repo_root)
    with PERSISTENCE_LOCK:
        current = load_ui_settings_from_path(settings_path)
        for key, value in updates.items():
            if key in DEFAULT_UI_SETTINGS and key not in SECRET_SETTING_KEYS:
                current[key] = value
        secret_clear_flags = {
            "youtubeApiKey": "clearYouTubeApiKey",
            "huggingFaceToken": "clearHuggingFaceToken",
        }
        for key, clear_flag in secret_clear_flags.items():
            if setting_bool(updates.get(clear_flag), False):
                credential_store.delete_secret(settings_path, key)
                continue
            replacement = strip_env_value(str(updates.get(key) or ""))
            if replacement:
                credential_store.store_secret(settings_path, key, replacement)
        normalised = normalise_ui_settings(current)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        if settings_path.exists() and read_json_object(settings_path) is not None:
            atomic_write_text(
                settings_backup_path(settings_path),
                settings_path.read_text(encoding="utf-8-sig"),
            )
        atomic_write_text(
            settings_path,
            json.dumps(normalised, indent=2, ensure_ascii=False) + "\n",
        )
        SETTINGS_WARNINGS.pop(str(settings_path.resolve()), None)
        return normalised


def validate_ui_settings_updates(updates: dict[str, object]) -> None:
    """Reject blank, non-finite, or out-of-range resource limits."""

    numeric_ranges = {
        "maxCpuPercent": (10.0, 100.0),
        "maxGpuPercent": (10.0, 100.0),
        "maxRamPercent": (10.0, 95.0),
        "maxRamGb": (1.0, 1024.0),
        "resourcePollSeconds": (0.5, 30.0),
    }
    for key, (minimum, maximum) in numeric_ranges.items():
        if key not in updates:
            continue
        value = updates[key]
        if isinstance(value, bool) or value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"{key} is required and must be a number.")
        number = require_finite_number(value, key)
        if not minimum <= number <= maximum:
            raise ValueError(f"{key} must be between {minimum:g} and {maximum:g}.")

    integer_ranges = {
        "maxCpuCores": (0, 256),
        "nativeThreads": (1, 256),
    }
    for key, (minimum, maximum) in integer_ranges.items():
        if key not in updates:
            continue
        number = require_finite_number(updates[key], key)
        if not number.is_integer() or not minimum <= number <= maximum:
            raise ValueError(f"{key} must be a whole number between {minimum} and {maximum}.")

    if "resourceLimitsEnabled" in updates and not isinstance(updates["resourceLimitsEnabled"], bool):
        raise ValueError("resourceLimitsEnabled must be true or false.")
    if "ramLimitMode" in updates and str(updates["ramLimitMode"]).casefold() not in {"percent", "gb"}:
        raise ValueError("ramLimitMode must be percent or gb.")
    if "youtubeCookiesBrowser" in updates and str(updates["youtubeCookiesBrowser"]).casefold() not in {
        "",
        "edge",
        "chrome",
        "firefox",
    }:
        raise ValueError("youtubeCookiesBrowser is not supported.")


def read_json_object(path: Path) -> dict[str, object] | None:
    try:
        payload = read_control_json(
            path,
            label="launcher settings",
            max_bytes=MAX_SETTINGS_JSON_BYTES,
            max_items=MAX_SETTINGS_JSON_ITEMS,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def migrate_legacy_settings_secrets(path: Path) -> tuple[str, ...]:
    """Move legacy primary/backup JSON secrets into DPAPI, then scrub both files."""

    backup_path = settings_backup_path(path)
    primary = read_json_object(path) if path.exists() else None
    backup = read_json_object(backup_path) if backup_path.exists() else None
    sources = [candidate for candidate in (primary, backup) if isinstance(candidate, dict)]
    credentials: dict[str, str] = {}
    for key in SECRET_SETTING_KEYS:
        for source in sources:
            value = strip_env_value(str(source.get(key) or ""))
            if value:
                credentials[key] = value
                break

    # Store every discovered value successfully before rewriting either legacy file.
    for key, value in credentials.items():
        credential_store.store_secret(path, key, value)

    primary_needs_scrub = isinstance(primary, dict) and any(key in primary for key in SECRET_SETTING_KEYS)
    backup_needs_scrub = isinstance(backup, dict) and any(key in backup for key in SECRET_SETTING_KEYS)
    primary_invalid = path.exists() and primary is None
    backup_invalid = backup_path.exists() and backup is None
    if primary_needs_scrub or primary_invalid:
        source = primary if isinstance(primary, dict) else backup if isinstance(backup, dict) else {}
        atomic_write_text(path, json.dumps(normalise_ui_settings(source), indent=2, ensure_ascii=False) + "\n")
    if backup_needs_scrub or backup_invalid:
        source = backup if isinstance(backup, dict) else primary if isinstance(primary, dict) else {}
        atomic_write_text(
            backup_path,
            json.dumps(normalise_ui_settings(source), indent=2, ensure_ascii=False) + "\n",
        )
    purged: list[str] = []
    if primary_invalid:
        purged.append(path.name)
    if backup_invalid:
        purged.append(backup_path.name)
    return tuple(purged)


def file_mentions_legacy_secret(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_SETTINGS_JSON_BYTES + 1)
    except OSError:
        return False
    return any(key.encode("utf-8") in raw for key in SECRET_SETTING_KEYS)


def settings_backup_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.bak")


def atomic_write_text(path: Path, text: str) -> None:
    """Flush and atomically replace a small local state file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def normalise_ui_settings(data: dict[str, object]) -> dict[str, object]:
    cookies_browser = str(data.get("youtubeCookiesBrowser") or "").strip().casefold()
    if cookies_browser not in {"", "edge", "chrome", "firefox"}:
        cookies_browser = ""
    ram_limit_mode = str(data.get("ramLimitMode") or "percent").strip().casefold()
    if ram_limit_mode not in {"percent", "gb"}:
        ram_limit_mode = "percent"
    return {
        "youtubeCookiesBrowser": cookies_browser,
        "resourceLimitsEnabled": setting_bool(data.get("resourceLimitsEnabled"), True),
        "maxCpuPercent": bounded_setting_float(data.get("maxCpuPercent"), 90.0, 10.0, 100.0),
        "maxCpuCores": bounded_setting_int(data.get("maxCpuCores"), 0, 0, 256),
        "maxGpuPercent": bounded_setting_float(data.get("maxGpuPercent"), 95.0, 10.0, 100.0),
        "ramLimitMode": ram_limit_mode,
        "maxRamPercent": bounded_setting_float(data.get("maxRamPercent"), 90.0, 10.0, 95.0),
        "maxRamGb": bounded_setting_float(data.get("maxRamGb"), 16.0, 1.0, 1024.0),
        "nativeThreads": bounded_setting_int(data.get("nativeThreads"), 1, 1, 256),
        "resourcePollSeconds": bounded_setting_float(data.get("resourcePollSeconds"), 2.0, 0.5, 30.0),
    }


def setting_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    cleaned = str(value).strip().casefold()
    if cleaned in {"true", "1", "yes", "on"}:
        return True
    if cleaned in {"false", "0", "no", "off"}:
        return False
    return default


def bounded_setting_float(value: object, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if not parsed == parsed:
        parsed = default
    return max(minimum, min(maximum, parsed))


def bounded_setting_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def clean_speaker_resource_settings(settings: dict[str, object]) -> dict[str, float | int]:
    """Translate global resource settings into clean-speaker CLI safeguards."""

    normalized = normalise_ui_settings(settings)
    enabled = bool(normalized["resourceLimitsEnabled"])
    poll_seconds = float(normalized["resourcePollSeconds"])
    if not enabled:
        return {
            "resource_guard_percent": 0.0,
            "resource_poll_seconds": poll_seconds,
            "resource_guard_timeout_seconds": 0.0,
            "max_affinity_cores": 0,
            "native_threads": min(256, max(1, os.cpu_count() or 1)),
            "cpu_high_percent": 100.0,
            "cpu_low_percent": 95.0,
            "ram_high_percent": 100.0,
            "ram_low_percent": 95.0,
        }

    cpu_high = float(normalized["maxCpuPercent"])
    gpu_high = float(normalized["maxGpuPercent"])
    ram_high = (
        float(normalized["maxRamPercent"])
        if normalized["ramLimitMode"] == "percent"
        else 95.0
    )
    minimum_allowed_load = min(cpu_high, gpu_high, ram_high)
    return {
        "resource_guard_percent": max(0.0, 100.0 - minimum_allowed_load),
        "resource_poll_seconds": poll_seconds,
        "resource_guard_timeout_seconds": 900.0,
        "max_affinity_cores": int(normalized["maxCpuCores"]),
        "native_threads": int(normalized["nativeThreads"]),
        "cpu_high_percent": cpu_high,
        "cpu_low_percent": max(1.0, cpu_high - 5.0),
        "ram_high_percent": ram_high,
        "ram_low_percent": max(1.0, ram_high - 5.0),
    }


def mask_secret(value: str) -> str:
    """Return a status-only secret representation that is safe for the UI."""

    cleaned = strip_env_value(value)
    if not cleaned:
        return ""
    visible = cleaned[-4:] if len(cleaned) > 4 else ""
    return f"********{visible}"


def public_ui_settings(repo_root: Path) -> dict[str, object]:
    """Return settings without exposing locally stored credentials to JavaScript."""

    settings = load_ui_settings(repo_root)
    youtube_key = load_youtube_api_key(settings_path=ui_settings_path(repo_root))
    huggingface_token = load_huggingface_token(settings_path=ui_settings_path(repo_root))
    public = {key: value for key, value in settings.items() if key not in SECRET_SETTING_KEYS}
    public.update(
        {
            "youtubeApiKeyConfigured": bool(youtube_key),
            "youtubeApiKeyMasked": mask_secret(youtube_key),
            "huggingFaceTokenConfigured": bool(huggingface_token),
            "huggingFaceTokenMasked": mask_secret(huggingface_token),
            "resourceCapabilities": resource_capabilities(),
            "settingsWarning": SETTINGS_WARNINGS.get(str(ui_settings_path(repo_root).resolve()), ""),
        }
    )
    return public


def resource_capabilities() -> dict[str, object]:
    """Report which optional local resource controls can be enforced."""

    total_ram_gb: float | None = None
    if importlib.util.find_spec("psutil") is not None:
        try:
            import psutil

            total_ram_gb = round(float(psutil.virtual_memory().total) / (1024 ** 3), 1)
        except Exception:
            total_ram_gb = None
    return {
        "logicalCpuCount": os.cpu_count() or 1,
        "totalRamGb": total_ram_gb,
        "processMonitoring": importlib.util.find_spec("psutil") is not None,
        "nvidiaGpuTelemetry": shutil.which("nvidia-smi") is not None,
    }


def prepare_source_for_run(
    source_path: str | Path,
    repo_root: Path,
    *,
    logger: Callable[[str], None] | None = None,
) -> Path:
    """Return a stable local source path for subprocesses.

    OneDrive and SharePoint DOCX paths can scan successfully in the launcher
    but then fail in a child process as "Package not found" if the file is a
    cloud placeholder. Copying the file into the repo-local _local cache forces
    Windows to hydrate it once, and every later subprocess reads a normal file.
    """

    raw_source = clean_user_supplied_path(source_path)
    if run_docx_extractions.get_youtube_video_id(raw_source):
        return materialise_youtube_source_docx(raw_source, repo_root, logger=logger)

    source = Path(raw_source).expanduser().resolve()
    if source.suffix.casefold() != ".docx":
        return source
    if not source.exists():
        raise FileNotFoundError(f"DOCX does not exist: {source}")

    cache_folder = repo_root.expanduser().resolve() / "_local" / "docx_cache"
    if source.parent == cache_folder:
        run_docx_extractions.open_docx_document(source, logger=logger)
        return source

    stat = source.stat()
    safe_stem = run_docx_extractions.make_folder_name_safe(source.stem, max_length=48)
    cache_path = cache_folder / f"{safe_stem}_{stat.st_size}_{stat.st_mtime_ns}.docx"
    cache_folder.mkdir(parents=True, exist_ok=True)
    if not cache_path.exists() or cache_path.stat().st_size != stat.st_size:
        if logger:
            logger(f"Preparing local DOCX copy for run: {cache_path}")
        shutil.copy2(source, cache_path)

    run_docx_extractions.open_docx_document(cache_path, logger=logger)
    return cache_path


def materialise_youtube_source_docx(
    youtube_url: str,
    repo_root: Path,
    *,
    logger: Callable[[str], None] | None = None,
) -> Path:
    """Represent one pasted URL as a local DOCX for the established pipelines."""

    canonical_url = run_docx_extractions.normalise_youtube_url(youtube_url)
    video_id = run_docx_extractions.get_youtube_video_id(canonical_url or "")
    if not canonical_url or not video_id:
        raise ValueError("The supplied YouTube URL does not contain a valid video ID.")

    target_dir = repo_root.expanduser().resolve() / "_local" / "youtube_sources"
    target = target_dir / f"youtube_{video_id}.docx"
    target_dir.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        document = Document()
        table = document.add_table(rows=2, cols=2)
        table.rows[0].cells[0].text = "Link"
        table.rows[0].cells[1].text = "Speaker"
        table.rows[1].cells[0].text = canonical_url
        table.rows[1].cells[1].text = "YouTube"
        document.save(target)
        if logger:
            logger(f"Prepared direct YouTube source for run: {target}")
    run_docx_extractions.open_docx_document(target, logger=logger)
    return target


def youtube_license_label(raw_value: str) -> str:
    raw = str(raw_value or "").strip()
    if raw == "youtube":
        return "Standard YouTube License"
    if raw == "creativeCommon":
        return "Creative Commons Attribution (CC BY)"
    return raw or "Unknown"


def best_thumbnail_url(thumbnails: dict[str, Any]) -> str:
    if not isinstance(thumbnails, dict):
        return ""
    for key in ("maxres", "standard", "high", "medium", "default"):
        item = thumbnails.get(key)
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    return ""


def fetch_youtube_api_metadata(video_ids: Iterable[str], api_key: str, *, timeout: int = 20) -> dict[str, dict[str, object]]:
    """Fetch metadata in API-sized batches of up to 50 video IDs."""

    unique_ids = [video_id for video_id in dict.fromkeys(str(item or "").strip() for item in video_ids) if video_id]
    metadata: dict[str, dict[str, object]] = {}
    for index in range(0, len(unique_ids), 50):
        batch = unique_ids[index : index + 50]
        params = urllib.parse.urlencode(
            {
                "part": "snippet,contentDetails,status",
                "id": ",".join(batch),
                "key": api_key,
            }
        )
        request = urllib.request.Request(
            f"{YOUTUBE_VIDEOS_URL}?{params}",
            headers={"User-Agent": "procurement-ui/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"YouTube API request failed with HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"YouTube API request failed: {exc.reason}") from exc

        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("id") or "")
            snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
            content_details = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            metadata[video_id] = {
                "title": str(snippet.get("title") or ""),
                "duration_seconds": parse_youtube_iso8601_duration(str(content_details.get("duration") or "")),
                "upload_date": str(snippet.get("publishedAt") or "")[:10],
                "license": youtube_license_label(str(status.get("license") or "")),
                "thumbnail_url": best_thumbnail_url(snippet.get("thumbnails") if isinstance(snippet, dict) else {}),
                "youtube_language": str(
                    snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage") or ""
                ).strip(),
            }
    return metadata


def fetch_youtube_oembed_metadata(youtube_url: str, *, timeout: int = 10) -> dict[str, object]:
    """Fetch public title/thumbnail metadata without requiring an API key."""

    params = urllib.parse.urlencode({"url": youtube_url, "format": "json"})
    request = urllib.request.Request(
        f"{YOUTUBE_OEMBED_URL}?{params}",
        headers={"User-Agent": "procurement-ui/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        "title": str(payload.get("title") or ""),
        "thumbnail_url": str(payload.get("thumbnail_url") or ""),
    }


def fetch_youtube_ytdlp_metadata(youtube_url: str, *, timeout: int = 45) -> dict[str, object]:
    """Resolve direct-link details locally when the Data API is not configured."""

    if not yt_dlp_is_available():
        return {}
    ffmpeg = resolve_media_binary("ffmpeg")
    try:
        result = subprocess.run(
            build_yt_dlp_command(
                [
                "--dump-single-json",
                "--skip-download",
                "--no-warnings",
                "--no-playlist",
                youtube_url,
                ],
                ffmpeg_binary=ffmpeg,
            ),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=credential_free_media_environment(),
        )
        payload = json.loads(result.stdout)
    except (OSError, json.JSONDecodeError, subprocess.SubprocessError):
        return {}
    if not isinstance(payload, dict):
        return {}
    upload_date = str(payload.get("upload_date") or "")
    if len(upload_date) == 8 and upload_date.isdigit():
        upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    duration = payload.get("duration")
    return {
        "title": str(payload.get("title") or ""),
        "thumbnail_url": str(payload.get("thumbnail") or ""),
        "duration_seconds": float(duration) if isinstance(duration, (int, float)) else None,
        "upload_date": upload_date,
        "license": str(payload.get("license") or "Unknown"),
    }


def fetch_youtube_oembed_batch(items: Iterable[VideoItem], *, workers: int = 8) -> dict[str, dict[str, object]]:
    """Resolve missing titles concurrently while keeping the API-key path primary."""

    urls_by_id = {
        item.video_id: item.youtube_url
        for item in items
        if item.video_id and item.youtube_url and title_looks_like_youtube_reference(item.title)
    }
    if not urls_by_id:
        return {}
    worker_count = max(1, min(int(workers), len(urls_by_id)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = executor.map(fetch_youtube_oembed_metadata, urls_by_id.values())
        return {
            video_id: metadata
            for video_id, metadata in zip(urls_by_id, results)
            if metadata.get("title")
        }


def enrich_youtube_items(
    items: list[VideoItem],
    *,
    logger: Callable[[str], None] | None = None,
) -> list[VideoItem]:
    """Fill metadata using the Data API, with public title lookup as fallback."""

    log = logger or (lambda _message: None)
    video_ids = [item.video_id for item in items if item.video_id]
    unique_count = len(set(video_ids))
    if not unique_count:
        return apply_youtube_metadata(items, {})

    api_key = load_youtube_api_key()
    metadata: dict[str, dict[str, object]] = {}
    if api_key:
        log(f"Querying YouTube Data API for {unique_count} unique video IDs.")
        try:
            metadata = fetch_youtube_api_metadata(video_ids, api_key)
        except RuntimeError as exc:
            log(f"YouTube Data API enrichment skipped: {exc}")
        else:
            log(f"YouTube Data API returned metadata for {len(metadata)} videos.")
    else:
        log("No YouTube Data API key configured; using public title lookup.")

    unresolved = [
        item
        for item in items
        if item.video_id not in metadata or not str(metadata[item.video_id].get("title") or "")
    ]
    if unresolved:
        log(f"Resolving {len(unresolved)} missing YouTube titles with public metadata.")
        for video_id, public_metadata in fetch_youtube_oembed_batch(unresolved).items():
            combined = metadata.setdefault(video_id, {})
            for key, value in public_metadata.items():
                combined.setdefault(key, value)
    return apply_youtube_metadata(items, metadata)


def apply_youtube_metadata(
    items: list[VideoItem],
    metadata_by_id: dict[str, dict[str, object]],
) -> list[VideoItem]:
    updated: list[VideoItem] = []
    for item in items:
        metadata = metadata_by_id.get(item.video_id, {})
        title = item.title
        if title_looks_like_youtube_reference(title):
            title = str(metadata.get("title") or clean_display_title(title, item.youtube_url))

        duration = item.duration_seconds
        metadata_duration = metadata.get("duration_seconds")
        if duration is None and isinstance(metadata_duration, (int, float)):
            duration = float(metadata_duration)

        upload_date = item.upload_date or str(metadata.get("upload_date") or "")
        license_text = item.license
        if is_unknown_value(license_text):
            license_text = str(metadata.get("license") or license_text or "Unknown")

        thumbnail_url = str(metadata.get("thumbnail_url") or item.thumbnail_url or youtube_thumbnail_url(item.video_id))
        youtube_language = str(
            metadata.get("youtube_language")
            or metadata.get("defaultAudioLanguage")
            or metadata.get("defaultLanguage")
            or item.youtube_language
            or ""
        ).strip()
        updated.append(
            replace(
                item,
                title=title,
                duration_seconds=duration,
                upload_date=upload_date,
                license=license_text,
                thumbnail_url=thumbnail_url,
                youtube_language=youtube_language,
            )
        )
    return updated


def is_unknown_value(value: str | None) -> bool:
    cleaned = " ".join(str(value or "").strip().casefold().split())
    return cleaned in {"", "unknown", "missing", "not returned", "local file / unknown"}


def seconds_to_display(value: float | None) -> str:
    if value is None:
        return "Unknown"
    seconds = max(0, int(round(value)))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remainder = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{remainder:02d}"
    return f"{minutes}:{remainder:02d}"


def youtube_thumbnail_url(video_id: str | None) -> str:
    cleaned = str(video_id or "").strip()
    if not cleaned:
        return ""
    return f"https://i.ytimg.com/vi/{cleaned}/hqdefault.jpg"


def scan_result_to_json(result: ScanResult) -> dict[str, object]:
    """Convert dataclasses into JSON-ready dictionaries for the browser."""

    payload = asdict(result)
    for group in payload["groups"]:
        for video in group["videos"]:
            video["duration_display"] = seconds_to_display(video.get("duration_seconds"))
            if not video.get("thumbnail_url"):
                video["thumbnail_url"] = youtube_thumbnail_url(video.get("video_id"))
    return payload


def build_imotions_transcode_command(
    source: Path,
    target: Path,
    *,
    start_seconds: float | None = None,
    duration_seconds: float | None = None,
    ffmpeg_binary: Path | None = None,
) -> list[str]:
    """Build a quiet, timestamp-stable MP4 transcode for downstream iMotions use."""

    ffmpeg = ffmpeg_binary or resolve_media_binary(
        "ffmpeg",
        excluded_roots=(source.parent, target.parent),
    )
    command = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error"]
    if start_seconds is not None:
        command.extend(["-ss", f"{float(start_seconds):.3f}"])
    command.extend(["-i", str(source)])
    if duration_seconds is not None:
        command.extend(["-t", f"{float(duration_seconds):.3f}"])
    command.extend(
        [
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-fps_mode",
            "cfr",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            "-avoid_negative_ts",
            "make_zero",
            str(target),
        ]
    )
    return command


def build_imotions_concat_command(
    concat_list: Path,
    target: Path,
    *,
    ffmpeg_binary: Path | None = None,
) -> list[str]:
    """Join canonical clips while regenerating audio timestamps at boundaries."""

    ffmpeg = ffmpeg_binary or resolve_media_binary(
        "ffmpeg",
        excluded_roots=(concat_list.parent, target.parent),
    )
    return [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "+genpts",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-fps_mode",
        "cfr",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-avoid_negative_ts",
        "make_zero",
        str(target),
    ]


def append_catalog_clean_speaker_options(command: list[str], request: RunRequest) -> None:
    """Forward every existing Clean Speaker option to the catalog coordinator."""

    command.extend(
        [
            "--output-mode",
            str(request.beta_output_mode),
            "--min-clean-seconds",
            str(float(request.beta_min_clean_seconds)),
            "--gap-seconds",
            str(float(request.beta_gap_seconds)),
            "--identity-stills",
            str(int(request.beta_identity_stills)),
            "--scan-fps",
            str(float(request.beta_scan_fps)),
            "--validation-fps",
            str(float(request.beta_validation_fps)),
            "--face-confidence",
            str(float(request.beta_face_confidence)),
            "--speaker-confidence",
            str(float(request.beta_speaker_confidence)),
            "--workers",
            str(int(request.beta_worker_count)),
            "--device",
            str(request.beta_device),
            "--resource-guard-percent",
            str(float(request.beta_resource_guard_percent)),
            "--resource-poll-seconds",
            str(float(request.beta_resource_poll_seconds)),
            "--resource-guard-timeout-seconds",
            str(float(request.beta_resource_guard_timeout_seconds)),
            "--max-download-height",
            str(int(request.beta_max_download_height)),
            "--video-cooldown-seconds",
            str(float(request.beta_video_cooldown_seconds)),
            "--max-affinity-cores",
            str(int(request.beta_max_affinity_cores)),
            "--native-threads",
            str(int(request.beta_native_threads)),
            "--cpu-throttle-high-percent",
            str(float(request.beta_cpu_throttle_high_percent)),
            "--cpu-throttle-low-percent",
            str(float(request.beta_cpu_throttle_low_percent)),
            "--ram-throttle-high-percent",
            str(float(request.beta_ram_throttle_high_percent)),
            "--ram-throttle-low-percent",
            str(float(request.beta_ram_throttle_low_percent)),
        ]
    )
    for video_id in request.beta_only_video_ids or []:
        command.extend(["--only-video-id", str(video_id)])
    if request.beta_random_one:
        command.append("--random-one")
    if request.beta_random_seed:
        command.extend(["--random-seed", str(request.beta_random_seed)])
    if request.beta_isolated_video_processes:
        command.append("--isolated-video-processes")
    if request.beta_skip_first_videos > 0:
        command.extend(["--skip-first-videos", str(int(request.beta_skip_first_videos))])
    if request.beta_skip_completed_outputs:
        command.append("--skip-completed-outputs")
    if request.beta_parallel_detector_streams:
        command.append("--parallel-detectors")
    if request.beta_keep_debug:
        command.append("--keep-debug")
    if request.beta_reference_audio is not None:
        command.extend(["--reference-audio", str(request.beta_reference_audio.expanduser().resolve())])


def build_run_command(
    request: RunRequest,
    *,
    repo_root: Path,
    python_executable: Path | None = None,
) -> list[str]:
    """Translate procurement options into the existing command-line tools.

    Keeping this as a pure builder makes it easy to unit-test without starting
    downloads or touching the filesystem beyond path normalisation.
    """

    python_executable = python_executable or Path(sys.executable)
    validate_run_request(request)
    source = request.source_path.expanduser().resolve()
    output_root = request.output_root.expanduser().resolve()
    mode = request.mode

    if request.internal_youtube_source:
        allowed_internal_root = (repo_root.expanduser().resolve() / "_local" / "youtube_sources").resolve()
        if source.parent != allowed_internal_root or not re.fullmatch(r"youtube_[A-Za-z0-9_-]{11}\.docx", source.name):
            raise ValueError("Internal YouTube materialization is not a trusted launcher source.")
    is_catalog = source.suffix.casefold() in {".csv", ".docx"} and not request.internal_youtube_source
    if is_catalog:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", request.catalog_sha256):
            raise ValueError("Catalog runs require the launcher-validated catalog SHA-256.")
        selected_ids = list(request.selected_ids or [])
        if not selected_ids or len(selected_ids) != len(set(selected_ids)):
            raise ValueError("Catalog runs require unique selected source IDs.")
        human_stem = make_filename_safe(source.stem, max_length=60)
        unique_suffix = (
            f"catalog_{mode}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}_"
            f"{secrets.token_hex(4)}"
        )
        run_label = f"{human_stem}_{unique_suffix}"
        command = [
            str(python_executable),
            "-m",
            "procurement.catalog_runner",
            str(source),
            "--run-root",
            str(output_root / run_label),
            "--mode",
            mode,
            "--catalog-sha256",
            request.catalog_sha256.casefold(),
            "--percentage",
            str(float(request.percentage)),
            "--max-segment-seconds",
            str(int(request.max_segment_seconds)),
        ]
        for source_id in selected_ids:
            command.extend(["--source-id", source_id])
        if mode == "manual":
            if request.segment_manifest is None:
                raise ValueError("Manual catalog mode requires a segment manifest.")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", request.segment_manifest_sha256):
                raise ValueError("Manual catalog mode requires the launcher-validated manifest SHA-256.")
            if not str(request.segment_expected_source or "").strip():
                raise ValueError("Manual catalog mode requires the launcher-validated source identity.")
            command.extend(
                [
                    "--segments-json",
                    str(request.segment_manifest.expanduser().resolve()),
                    "--manifest-sha256",
                    request.segment_manifest_sha256.casefold(),
                    "--expected-source",
                    str(request.segment_expected_source),
                ]
            )
        if mode == "clean-speaker-beta":
            append_catalog_clean_speaker_options(command, request)
        return command

    if mode == "manual":
        if request.segment_manifest is None:
            raise ValueError("Manual segment mode requires a segment manifest.")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", request.segment_manifest_sha256):
            raise ValueError("Manual segment mode requires the launcher-validated manifest SHA-256.")
        if not str(request.segment_expected_source or "").strip():
            raise ValueError("Manual segment mode requires the launcher-validated source identity.")
        return [
            str(python_executable),
            "-m",
            "application.manual_segments",
            "--source",
            str(source),
            "--output-root",
            str(output_root),
            "--segments-json",
            str(request.segment_manifest.expanduser().resolve()),
            "--manifest-sha256",
            request.segment_manifest_sha256.casefold(),
            "--expected-source",
            str(request.segment_expected_source),
        ]

    if mode == "clean-speaker-beta":
        command = [
            str(python_executable),
            "-m",
            "procurement.procurement_beta.cli",
            "--source",
            str(source),
            "--output-root",
            str(output_root),
            "--output-mode",
            str(request.beta_output_mode),
            "--percentage",
            str(request.percentage),
            "--min-clean-seconds",
            str(float(request.beta_min_clean_seconds)),
            "--max-segment-seconds",
            str(int(request.max_segment_seconds)),
            "--gap-seconds",
            str(float(request.beta_gap_seconds)),
            "--identity-stills",
            str(int(request.beta_identity_stills)),
            "--scan-fps",
            str(float(request.beta_scan_fps)),
            "--validation-fps",
            str(float(request.beta_validation_fps)),
            "--face-confidence",
            str(float(request.beta_face_confidence)),
            "--speaker-confidence",
            str(float(request.beta_speaker_confidence)),
            "--workers",
            str(int(request.beta_worker_count)),
            "--device",
            str(request.beta_device),
            "--resource-guard-percent",
            str(float(request.beta_resource_guard_percent)),
            "--resource-poll-seconds",
            str(float(request.beta_resource_poll_seconds)),
            "--resource-guard-timeout-seconds",
            str(float(request.beta_resource_guard_timeout_seconds)),
            "--max-download-height",
            str(int(request.beta_max_download_height)),
            "--video-cooldown-seconds",
            str(float(request.beta_video_cooldown_seconds)),
            "--max-affinity-cores",
            str(int(request.beta_max_affinity_cores)),
            "--native-threads",
            str(int(request.beta_native_threads)),
            "--cpu-throttle-high-percent",
            str(float(request.beta_cpu_throttle_high_percent)),
            "--cpu-throttle-low-percent",
            str(float(request.beta_cpu_throttle_low_percent)),
            "--ram-throttle-high-percent",
            str(float(request.beta_ram_throttle_high_percent)),
            "--ram-throttle-low-percent",
            str(float(request.beta_ram_throttle_low_percent)),
        ]
        for speaker in request.selected_speakers or []:
            command.extend(["--speaker", str(speaker)])
        for video_id in request.beta_only_video_ids or []:
            command.extend(["--only-video-id", str(video_id)])
        if request.beta_random_one:
            command.append("--random-one")
        if request.beta_random_seed:
            command.extend(["--random-seed", str(request.beta_random_seed)])
        if request.beta_isolated_video_processes:
            command.append("--isolated-video-processes")
        if request.beta_skip_first_videos > 0:
            command.extend(["--skip-first-videos", str(int(request.beta_skip_first_videos))])
        if request.beta_skip_completed_outputs:
            command.append("--skip-completed-outputs")
        if request.beta_parallel_detector_streams:
            command.append("--parallel-detectors")
        if request.beta_keep_debug:
            command.append("--keep-debug")
        if request.beta_reference_audio is not None:
            command.extend(["--reference-audio", str(request.beta_reference_audio.expanduser().resolve())])
        return command

    if source.suffix.casefold() == ".docx":
        if mode == "standard":
            # Standard sampling does not need the YouTube licence-audit step.
            # Calling the long-standing DOCX sampler directly keeps the common
            # non-technical workflow usable even when no YouTube API key has
            # been configured yet.
            linked_docx = output_root / f"{source.stem}_with_extraction_links.docx"
            command = [
                str(python_executable),
                "-m",
                "procurement.video_sampling.run_docx_extractions",
                str(source),
                "--speaker-output-root",
                str(output_root),
                "--output",
                str(linked_docx),
                "--extractor-arg=--percentage",
                f"--extractor-arg={float(request.percentage)}",
                "--extractor-arg=--segment-length",
                f"--extractor-arg={int(request.max_segment_seconds)}",
            ]
            for speaker in request.selected_speakers or []:
                command.extend(["--speaker", str(speaker)])
            return command

        if mode == "full":
            command = [
                str(python_executable),
                "-m",
                "procurement.run_pipeline",
                str(source),
                "--output-root",
                str(output_root),
                "--manual-review-strategy",
                "full-video",
            ]
            for speaker in request.selected_speakers or []:
                command.extend(["--speaker", str(speaker)])
            return command

    if mode in {"standard", "full"}:
        command = [
            str(python_executable),
            "-m",
            "application.local_videos",
            "--source",
            str(source),
            "--output-root",
            str(output_root),
            "--mode",
            mode,
            "--percentage",
            str(request.percentage),
            "--max-segment-seconds",
            str(request.max_segment_seconds),
        ]
        for speaker in request.selected_speakers or []:
            command.extend(["--speaker", str(speaker)])
        return command

    raise ValueError(f"Unsupported run mode: {mode}")


def validate_run_request(request: RunRequest) -> None:
    """Reject invalid UI values before a long-running subprocess is started."""

    if request.mode not in {"standard", "full", "manual", "clean-speaker-beta"}:
        raise ValueError(f"Unsupported run mode: {request.mode}")
    percentage = require_finite_number(request.percentage, "Sample percentage")
    if not 0 < percentage <= 1:
        raise ValueError("Sample percentage must be greater than 0 and no more than 100%.")
    uses_max_segment = request.mode == "standard" or (
        request.mode == "clean-speaker-beta" and request.beta_output_mode == "percentage"
    )
    if uses_max_segment and not 1 <= int(request.max_segment_seconds) <= 3600:
        raise ValueError("Maximum segment length must be between 1 and 3600 seconds.")
    if request.mode != "clean-speaker-beta":
        return

    if request.beta_output_mode not in {"clean", "percentage"}:
        raise ValueError("Clean speaker output mode must be 'clean' or 'percentage'.")
    minimum_clean = require_finite_number(request.beta_min_clean_seconds, "Minimum clean overlap")
    gap_seconds = require_finite_number(request.beta_gap_seconds, "Black/silent gap")
    scan_fps = require_finite_number(request.beta_scan_fps, "Scan FPS")
    validation_fps = require_finite_number(request.beta_validation_fps, "Validation FPS")
    face_confidence = require_finite_number(request.beta_face_confidence, "Face confidence")
    speaker_confidence = require_finite_number(request.beta_speaker_confidence, "Speaker confidence")
    resource_guard = require_finite_number(request.beta_resource_guard_percent, "Resource guard")
    resource_poll = require_finite_number(request.beta_resource_poll_seconds, "Resource poll interval")
    resource_timeout = require_finite_number(request.beta_resource_guard_timeout_seconds, "Resource wait timeout")
    cooldown = require_finite_number(request.beta_video_cooldown_seconds, "Video cooldown")
    cpu_high = require_finite_number(request.beta_cpu_throttle_high_percent, "CPU pause threshold")
    cpu_low = require_finite_number(request.beta_cpu_throttle_low_percent, "CPU resume threshold")
    ram_high = require_finite_number(request.beta_ram_throttle_high_percent, "RAM pause threshold")
    ram_low = require_finite_number(request.beta_ram_throttle_low_percent, "RAM resume threshold")

    if minimum_clean <= 0:
        raise ValueError("Minimum clean overlap must be greater than 0 seconds.")
    if not 0 <= gap_seconds <= 60:
        raise ValueError("Black/silent gap must be between 0 and 60 seconds.")
    if not 1 <= int(request.beta_identity_stills) <= 200:
        raise ValueError("Identity still count must be between 1 and 200.")
    if not 0.1 <= scan_fps <= 10 or not 0.1 <= validation_fps <= 10:
        raise ValueError("Scan and validation FPS must be between 0.1 and 10.")
    if not 0 < face_confidence <= 1:
        raise ValueError("Face confidence must be greater than 0 and no more than 1.")
    if not 0 < speaker_confidence <= 1:
        raise ValueError("Speaker confidence must be greater than 0 and no more than 1.")
    if not 1 <= int(request.beta_worker_count) <= 64:
        raise ValueError("Worker count must be between 1 and 64.")
    if str(request.beta_device).casefold() not in {"auto", "cpu", "cuda"}:
        raise ValueError("Clean speaker model device must be auto, cpu, or cuda.")
    if not 0 <= resource_guard <= 95:
        raise ValueError("Resource guard must be between 0 and 95%.")
    if not 0.5 <= resource_poll <= 300:
        raise ValueError("Resource poll interval must be between 0.5 and 300 seconds.")
    if not 0 <= resource_timeout <= 86400:
        raise ValueError("Resource wait timeout must be between 0 and 86400 seconds.")
    if not 0 <= int(request.beta_max_download_height) <= 4320:
        raise ValueError("Maximum download height must be between 0 and 4320.")
    if not 0 <= int(request.beta_skip_first_videos) <= 10000:
        raise ValueError("Skip-first count must be between 0 and 10000.")
    if not 0 <= cooldown <= 3600:
        raise ValueError("Video cooldown must be between 0 and 3600 seconds.")
    if not 0 <= int(request.beta_max_affinity_cores) <= 256:
        raise ValueError("Maximum CPU cores must be between 0 and 256.")
    if not 1 <= int(request.beta_native_threads) <= 256:
        raise ValueError("Native thread count must be between 1 and 256.")
    for label, low, high in (
        ("CPU", cpu_low, cpu_high),
        ("RAM", ram_low, ram_high),
    ):
        if not 1 <= low <= high <= 100:
            raise ValueError(f"{label} resume threshold must be no greater than its pause threshold.")


def require_finite_number(value: object, label: str) -> float:
    """Return one finite number or raise a user-facing validation error."""

    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be a finite number.")
    return parsed


def build_audio_command(
    request: AudioRunRequest,
    *,
    repo_root: Path,
    python_executable: Path | None = None,
) -> list[str]:
    """Translate audio UI options into the audio analysis CLI command."""

    python_executable = python_executable or Path(sys.executable)
    mode = str(request.mode or "").casefold()
    if mode not in {"batch", "single"}:
        raise ValueError(f"Unsupported audio mode: {request.mode}")
    if not 0.5 <= float(request.window_seconds) <= 120:
        raise ValueError("Audio window length must be between 0.5 and 120 seconds.")
    if not 0.5 <= float(request.stride_seconds) <= 120:
        raise ValueError("Audio stride length must be between 0.5 and 120 seconds.")
    feature_set = str(request.opensmile_feature_set or "").casefold()
    if feature_set not in {"egemaps", "compare16", "compare"}:
        raise ValueError(f"Unsupported OpenSMILE feature set: {request.opensmile_feature_set}")
    device = str(request.device or "").casefold()
    if device not in {"auto", "cpu", "cuda"}:
        raise ValueError(f"Unsupported emotion model device: {request.device}")
    source_ids = tuple(str(source_id).strip() for source_id in request.selected_source_ids)
    catalog_sha256 = str(request.catalog_sha256 or "").strip().casefold()
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Selected audio SourceIDs must be unique.")
    if any(re.fullmatch(r"source-\d{4,6}", source_id) is None for source_id in source_ids):
        raise ValueError("Selected audio SourceIDs must use the source-0001 format.")
    if source_ids and mode != "batch":
        raise ValueError("Audio SourceID selection is available only for batch folders.")
    if source_ids and re.fullmatch(r"[0-9a-f]{64}", catalog_sha256) is None:
        raise ValueError("Selected audio SourceIDs require the chosen catalog run SHA-256.")
    if catalog_sha256 and not source_ids:
        raise ValueError("An audio catalog SHA-256 requires one or more selected SourceIDs.")

    command = [
        str(python_executable),
        str(repo_root.expanduser().resolve() / "processing" / "audio_analysis" / "run_audio_analysis.py"),
        mode,
        str(request.source_path.expanduser().resolve()),
        "--output",
        str(request.output_root.expanduser().resolve()),
        "--window-seconds",
        str(float(request.window_seconds)),
        "--stride-seconds",
        str(float(request.stride_seconds)),
        "--opensmile-feature-set",
        feature_set,
        "--device",
        device,
    ]
    if not request.include_emotions:
        command.append("--skip-emotion-models")
    if request.keep_temp_audio:
        command.append("--keep-temp-audio")
    if request.debug:
        command.append("--debug")
    if mode == "batch" and request.stop_on_error:
        command.append("--stop-on-error")
    if catalog_sha256:
        command.extend(["--catalog-sha256", catalog_sha256])
    for source_id in source_ids:
        command.extend(["--source-id", source_id])
    return command


def _validated_native_catalog_binding(
    source_ids_value: Iterable[str], catalog_sha256_value: object
) -> tuple[tuple[str, ...], str]:
    source_ids = tuple(str(source_id).strip() for source_id in source_ids_value)
    catalog_sha256 = str(catalog_sha256_value or "").strip().casefold()
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Selected SourceIDs must be unique.")
    if any(re.fullmatch(r"source-\d{4,6}", source_id) is None for source_id in source_ids):
        raise ValueError("Selected SourceIDs must use the source-0001 format.")
    if source_ids and re.fullmatch(r"[0-9a-f]{64}", catalog_sha256) is None:
        raise ValueError("Selected SourceIDs require the chosen catalog run SHA-256.")
    if catalog_sha256 and not source_ids:
        raise ValueError("A catalog SHA-256 requires one or more selected SourceIDs.")
    return source_ids, catalog_sha256


def build_face_processing_command(
    request: FaceProcessingRunRequest,
    *,
    repo_root: Path,
    python_executable: Path | None = None,
) -> list[str]:
    """Translate native Face UI options without resolving lexical child paths."""

    _ = repo_root
    python_executable = python_executable or Path(sys.executable)
    sample_fps = require_finite_number(request.sample_fps, "Face sample FPS")
    confidence = require_finite_number(request.confidence_threshold, "Face confidence threshold")
    if not 0 < sample_fps <= 120:
        raise ValueError("Face sample FPS must be greater than 0 and no more than 120.")
    if not 0 < confidence <= 1:
        raise ValueError("Face confidence threshold must be greater than 0 and no more than 1.")
    if not 1 <= int(request.batch_size) <= 1024:
        raise ValueError("Face batch size must be between 1 and 1024.")
    device = str(request.device or "").casefold()
    if device not in {"auto", "cpu", "cuda", "mps"}:
        raise ValueError("Face device must be auto, cpu, cuda, or mps.")
    source_ids, catalog_sha256 = _validated_native_catalog_binding(
        request.selected_source_ids, request.catalog_sha256
    )
    command = [
        str(python_executable),
        "-m",
        "processing.face_analysis",
        str(Path(os.path.abspath(request.source_path.expanduser()))),
        "--output-root",
        str(Path(os.path.abspath(request.output_root.expanduser()))),
        "--sample-fps",
        str(sample_fps),
        "--face-threshold",
        str(confidence),
        "--batch-size",
        str(int(request.batch_size)),
        "--device",
        device,
    ]
    if not request.recursive:
        command.append("--no-recursive")
    if request.overwrite:
        command.append("--overwrite")
    if request.debug:
        command.append("--debug")
    if catalog_sha256:
        command.extend(["--catalog-sha256", catalog_sha256])
    for source_id in source_ids:
        command.extend(["--source-id", source_id])
    return command


def build_face_readiness_command(
    *,
    device: str = "auto",
    prepare_models: bool = False,
    python_executable: Path | None = None,
) -> list[str]:
    """Build an offline readiness or explicitly authorized model-preparation command."""

    python_executable = python_executable or Path(sys.executable)
    clean_device = str(device or "").casefold()
    if clean_device not in {"auto", "cpu", "cuda", "mps"}:
        raise ValueError("Face device must be auto, cpu, cuda, or mps.")
    return [
        str(python_executable),
        "-m",
        "processing.face_analysis",
        "--prepare-models" if prepare_models else "--check",
        "--device",
        clean_device,
    ]


def face_processing_readiness(device: str = "auto") -> dict[str, object]:
    """Return the structured offline Face readiness report in-process."""

    from processing.face_analysis.health import check_readiness

    clean_device = str(device or "").casefold()
    if clean_device not in {"auto", "cpu", "cuda", "mps"}:
        raise ValueError("Face device must be auto, cpu, cuda, or mps.")
    return {"kind": "face-processing-readiness", **check_readiness(clean_device).to_dict()}


def text_processing_readiness(
    request: TextProcessingRunRequest,
    *,
    repo_root: Path,
) -> dict[str, object]:
    """Return structured Text readiness without exposing launcher credentials."""

    from processing.text_analysis.pipeline import (
        TextProcessingConfig,
        check_text_processing_readiness,
    )

    destination = Path(os.path.abspath(request.output_root.expanduser()))
    defaults = TextProcessingConfig()
    config = TextProcessingConfig(
        input_path=str(Path(os.path.abspath(request.source_path.expanduser()))),
        whisper_root=str(destination / "transcripts"),
        selected_whisper_root=str(destination / "selected_transcripts"),
        prepared_root=str(destination / "prepared_segments"),
        selected_csv_root=str(destination / "rocksteady" / "core"),
        extra_csv_root=str(destination / "rocksteady" / "all"),
        postprocessing_root=str(destination / "analysis"),
        whisper_model=request.whisper_model,
        whisper_device=request.whisper_device,
        whisper_language=request.whisper_language,
        default_language_variant=request.default_language_variant,
        dictionaries=request.dictionaries or defaults.dictionaries,
        dictionary_combination=request.dictionary_combination,
        categories=() if request.all_categories else request.categories,
        threads=request.threads,
        overwrite_rocksteady=request.force_rocksteady,
        write_graphs=request.write_graphs,
        source_ids=request.selected_source_ids,
        catalog_sha256=request.catalog_sha256,
    ).validate()
    _ = repo_root
    try:
        readiness = check_text_processing_readiness(config)
    except Exception as exc:
        return {
            "kind": "text-processing-readiness",
            "status": "not_ready",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    return {"kind": "text-processing-readiness", **readiness}


def build_text_processing_command(
    request: TextProcessingRunRequest,
    *,
    repo_root: Path,
    python_executable: Path | None = None,
    check: bool = False,
) -> list[str]:
    """Translate native Text UI options without resolving lexical child paths."""

    _ = repo_root
    python_executable = python_executable or Path(sys.executable)
    model = str(request.whisper_model or "").casefold()
    if model not in {"tiny", "base", "small", "medium", "large", "large-v2", "large-v3"}:
        raise ValueError(f"Unsupported Whisper model: {request.whisper_model}")
    device = str(request.whisper_device or "").casefold()
    if device not in {"auto", "cpu", "cuda"}:
        raise ValueError(f"Unsupported Whisper device: {request.whisper_device}")
    variant = str(request.default_language_variant or "").casefold()
    if variant not in {"original", "eng"}:
        raise ValueError("Text output language must be original or eng.")
    combination = str(request.dictionary_combination or "").casefold()
    if combination not in {"merge", "override"}:
        raise ValueError("Text dictionary combination must be merge or override.")
    if not 1 <= int(request.threads) <= 256:
        raise ValueError("Text thread count must be between 1 and 256.")
    dictionaries = tuple(str(value).strip() for value in request.dictionaries)
    categories = tuple(str(value).strip() for value in request.categories)
    if any(not value for value in dictionaries) or len({value.casefold() for value in dictionaries}) != len(dictionaries):
        raise ValueError("Text dictionaries must be nonblank and unique.")
    if any(not value for value in categories) or len({value.casefold() for value in categories}) != len(categories):
        raise ValueError("Text categories must be nonblank and unique.")
    if request.all_categories and categories:
        raise ValueError("Choose all categories or named categories, not both.")
    source_ids, catalog_sha256 = _validated_native_catalog_binding(
        request.selected_source_ids, request.catalog_sha256
    )
    command = [
        str(python_executable),
        "-m",
        "processing.text_analysis",
        str(Path(os.path.abspath(request.source_path.expanduser()))),
        "--output-root",
        str(Path(os.path.abspath(request.output_root.expanduser()))),
        "--whisper-model",
        model,
        "--whisper-device",
        device,
        "--default-language-variant",
        variant,
        "--dictionary-combination",
        combination,
        "--threads",
        str(int(request.threads)),
    ]
    language = str(request.whisper_language or "").strip()
    if language:
        command.extend(["--whisper-language", language])
    for dictionary in dictionaries:
        command.extend(["--dictionary", dictionary])
    if request.all_categories:
        command.append("--all-categories")
    else:
        for category in categories:
            command.extend(["--category", category])
    if request.force_rocksteady:
        command.append("--force-rocksteady")
    if not request.write_graphs:
        command.append("--no-graphs")
    if request.debug:
        command.append("--debug")
    if catalog_sha256:
        command.extend(["--catalog-sha256", catalog_sha256])
    for source_id in source_ids:
        command.extend(["--source-id", source_id])
    if check:
        command.append("--check")
    return command


def build_analysis_command(
    request: AnalysisRunRequest,
    *,
    repo_root: Path,
    python_executable: Path | None = None,
) -> list[str]:
    """Translate launcher analysis options into existing post-processing CLIs."""

    _ = repo_root
    python_executable = python_executable or Path(sys.executable)
    mode = str(request.mode or "").casefold()
    module_by_mode = {
        "audio": "analysis.audio",
        "native_face": "analysis.native_face",
        "face": "analysis.imotions",
        "imotions": "analysis.imotions",
        "raw": "analysis.imotions",
    }
    module = module_by_mode.get(mode)
    if module is None:
        raise ValueError(f"Unsupported analysis mode: {request.mode}")

    command = [
        str(python_executable),
        "-m",
        module,
        str(request.source_path.expanduser().resolve()),
        "--output-root",
        str(Path(os.path.abspath(request.output_root.expanduser()))),
    ]
    if not request.write_graphs:
        command.append("--no-graphs")
    if request.include_logscale:
        command.append("--logscale")
    if module == "analysis.imotions":
        if request.include_landmarks:
            command.append("--include-landmarks")
        if request.include_timing:
            command.append("--include-timing")
        if request.exclude_geometry:
            command.append("--exclude-geometry")
    return command


def build_analysis_workflow_command(
    request: AnalysisWorkflowRunRequest,
    *,
    repo_root: Path,
    python_executable: Path | None = None,
) -> list[str]:
    """Translate a combined analysis request into one workflow CLI command."""

    _ = repo_root
    python_executable = python_executable or Path(sys.executable)
    modalities = tuple(request.modalities)
    if not modalities:
        raise ValueError("Choose at least one Video / iMotions, Native Face, Audio, or Text modality.")
    if request.write_combined_workbook and not request.speaker_groups and request.analysis_profile is None:
        raise ValueError("Choose an output profile or at least one speaker group for the combined workbook.")
    if request.analysis_profile is not None and request.speaker_groups:
        raise ValueError("Use either an output profile or legacy speaker groups, not both.")
    profile_metadata = None
    resolved_profile = None
    if request.analysis_profile is not None:
        try:
            profile_metadata = load_source_metadata(
                request.analysis_profile.source_manifest,
                expected_sha256=request.analysis_profile.source_manifest_sha256,
            )
            resolved_profile = resolve_analysis_profile(
                profile_metadata,
                request.analysis_profile,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid Analysis output profile: {exc}") from exc
    confidence_level = require_finite_number(request.confidence_level, "Confidence level")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("Confidence level must be between 0 and 1.")
    headline_policy = str(request.headline_policy or "").casefold()
    if headline_policy not in {"weighted", "equal"}:
        raise ValueError("Speaker mean method must be weighted or equal.")

    command = [
        str(python_executable),
        "-m",
        "analysis.workflow",
        "--output-root",
        str(Path(os.path.abspath(request.output_root.expanduser()))),
    ]
    seen_modalities: set[str] = set()
    for modality in modalities:
        name = str(modality.name or "").casefold()
        if name not in {"imotions", "native_face", "audio", "text"}:
            raise ValueError(f"Unsupported analysis workflow modality: {modality.name}")
        if name in seen_modalities:
            raise ValueError(f"Duplicate analysis workflow modality: {name}")
        source_method = str(modality.source_method or "").casefold()
        if source_method not in {"run", "import"}:
            raise ValueError(f"Unsupported source method for {name}: {modality.source_method}")
        if name == "text" and source_method != "import":
            raise ValueError("Text results are import-only in the combined workflow.")
        seen_modalities.add(name)
        command.extend(
            [
                f"--{name}-source",
                str(modality.source_path.expanduser().resolve()),
                f"--{name}-method",
                source_method,
            ]
        )

    if request.analysis_profile is not None:
        try:
            validate_source_manifest_associations(
                tuple(modality.source_path for modality in modalities),
                request.analysis_profile.source_manifest,
                request.analysis_profile.source_manifest_sha256,
            )
        except (OSError, ValueError) as exc:
            raise ValueError(
                "Analysis output profile is not associated with the selected modality folders."
            ) from exc
        # Native SourceID-grain Text validates splits against its own manifest
        # during workflow execution. The legacy speaker-grain restriction is
        # retained there, after the actual Text grain is known.
        if "text" in seen_modalities:
            text_modality = next(modality for modality in modalities if modality.name.casefold() == "text")
            has_native_summary = any(text_modality.source_path.rglob("video_level_summary.csv"))
            if has_native_summary:
                try:
                    text_discovery = discover_text_results(text_modality.source_path)
                except TextResultsError as exc:
                    raise ValueError(f"Invalid imported Text results: {exc}") from exc
            else:
                text_discovery = None
            if text_discovery is None or text_discovery.grain == "speaker":
                try:
                    validate_text_profile_grouping(profile_metadata, resolved_profile)
                except ValueError as exc:
                    raise ValueError(str(exc)) from exc

    groups_payload: list[dict[str, object]] = []
    group_ids: set[str] = set()
    group_names: set[str] = set()
    assigned_speakers: set[str] = set()
    for group in request.speaker_groups:
        group_id = str(group.group_id or "").strip()
        group_name = str(group.name or "").strip()
        speaker_ids = canonical_analysis_speaker_ids(group.speaker_ids)
        if not group_id or not group_name or not speaker_ids or any(not speaker for speaker in speaker_ids):
            raise ValueError("Each speaker group needs a nonblank id, name, and at least one speaker.")
        if group_id in group_ids or group_name in group_names:
            raise ValueError("Speaker group ids and names must be unique.")
        if len(set(speaker_ids)) != len(speaker_ids) or assigned_speakers.intersection(speaker_ids):
            raise ValueError("Each speaker may belong to only one speaker group.")
        group_ids.add(group_id)
        group_names.add(group_name)
        assigned_speakers.update(speaker_ids)
        groups_payload.append({"id": group_id, "name": group_name, "speakerKeys": list(speaker_ids)})

    default_reference = require_finite_number(request.default_reference, "Default reference")
    overrides: dict[str, float] = {}
    for key, value in request.reference_overrides.items():
        clean_key = str(key).strip()
        if not clean_key:
            raise ValueError("Reference override names must be nonblank.")
        overrides[clean_key] = require_finite_number(value, "Reference overrides")
    if request.analysis_profile is not None:
        command.extend(
            [
                "--analysis-profile-json",
                json.dumps(profile_payload(request.analysis_profile), sort_keys=True),
            ]
        )
    else:
        command.extend(
            [
                "--speaker-groups-json",
                json.dumps(groups_payload, sort_keys=True),
            ]
        )
    command.extend(
        [
            "--default-reference",
            str(default_reference),
            "--reference-overrides-json",
            json.dumps(overrides, sort_keys=True),
            "--confidence-level",
            str(confidence_level),
            "--headline-policy",
            headline_policy,
        ]
    )
    if not request.write_combined_workbook:
        command.append("--no-combined-workbook")
    if not request.include_construct_comparison:
        command.append("--no-construct-comparison")
    if not request.include_probability_sheets:
        command.append("--no-probability-sheets")
    if not request.write_graphs:
        command.append("--no-graphs")
    if request.include_logscale:
        command.append("--logscale")
    if request.include_landmarks:
        command.append("--include-landmarks")
    if request.include_timing:
        command.append("--include-timing")
    if request.exclude_geometry:
        command.append("--exclude-geometry")
    return command


def canonical_analysis_speaker_ids(speaker_ids: Iterable[str]) -> tuple[str, ...]:
    """Resolve launcher speaker keys to the workflow's audited canonical IDs."""

    clean_speaker_ids = tuple(str(speaker).strip() for speaker in speaker_ids)
    if any(not speaker for speaker in clean_speaker_ids):
        raise ValueError("Speaker group speakers must be nonblank.")
    return tuple(resolve_speaker(speaker_id).speaker_id for speaker_id in clean_speaker_ids)


def default_output_root(repo_root: Path) -> Path:
    """Default location for procurement runs started from the launcher."""

    return repo_root / "procurement" / "output" / "ui_runs"


def default_audio_output_root(repo_root: Path) -> Path:
    """Default location for audio runs started from the launcher."""

    return repo_root / "processing" / "audio_analysis" / "output" / "ui_runs"


def default_face_output_root(repo_root: Path) -> Path:
    """Default location for native Py-Feat runs started from the launcher."""

    return repo_root / "processing" / "face_analysis" / "output" / "ui_runs"


def default_text_output_root(repo_root: Path) -> Path:
    """Default location for native Text runs started from the launcher."""

    return repo_root / "processing" / "text_analysis" / "output" / "ui_runs"


def default_analysis_output_root(repo_root: Path) -> Path:
    """Default report location for analysis runs started from the launcher."""

    return repo_root / "analysis" / "output" / "ui_runs"
