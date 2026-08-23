"""Coordinate Video, Audio, and imported Text results into one analysis workbook."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence

from analysis.audio import analyse_audio_folder
from analysis.combined_summary import (
    CombinedDiscoveryResult,
    DiscoveryEntry,
    SpeakerGroupDefinition,
    build_combined_workbook,
    discover_combined_sources_audited,
)
from analysis.imotions import analyse_imotions_folder
from analysis.native_face import analyse_native_face_folder
from analysis.inference import ReferenceResolution, add_probability_mirrors
from analysis.metadata import (
    load_source_metadata,
    resolve_analysis_profile,
    validate_source_manifest_associations,
    validate_text_profile_grouping,
)
from analysis.profile import (
    AnalysisProfile,
    profile_from_payload,
    profile_payload,
    write_analysis_profile,
)
from analysis.text_results import TextResultsError, discover_text_results
from analysis.video import (
    DetectedVideoSource,
    VideoOutputProvenance,
    detect_video_source,
    load_canonical_video,
    validate_video_reference_override_keys,
)
from analysis.video_contract import validate_video_provider_options
from analysis import __version__
from procurement.input_limits import (
    MAX_WORKFLOW_MANIFEST_JSON_BYTES,
    MAX_WORKFLOW_MANIFEST_JSON_ITEMS,
    read_control_json,
)
from processing.io_utils import atomic_write_csv


ProgressCallback = Callable[[str], None]


class WorkflowError(RuntimeError):
    """Raised when a workflow stage cannot complete."""

    def __init__(self, message: str, *, stage: str | None = None) -> None:
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True)
class ModalityRequest:
    name: Literal["video", "audio", "text"]
    source_method: Literal["run", "import"]
    source_path: Path
    write_graphs: bool = True
    include_logscale: bool = False
    include_landmarks: bool = False
    include_timing: bool = False
    exclude_geometry: bool = False


@dataclass(frozen=True)
class WorkflowRequest:
    output_root: Path
    modalities: tuple[ModalityRequest, ...]
    speaker_groups: tuple[SpeakerGroupDefinition, ...]
    write_combined_workbook: bool = True
    include_construct_comparison: bool = True
    include_probability_sheets: bool = True
    confidence_level: float = 0.95
    headline_policy: Literal["weighted", "equal"] = "weighted"
    default_reference: float = 0.0
    reference_overrides: Mapping[str, float] = field(default_factory=dict)
    analysis_profile: AnalysisProfile | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowResult:
    output_root: Path
    workbook_path: Path | None
    manifest_path: Path
    modality_roots: Mapping[str, Path]
    warnings: tuple[str, ...]
    analysis_profile_path: Path | None = None


@dataclass(frozen=True)
class _ModalityExecution:
    stage_root: Path
    discovery_root: Path


_MODALITIES: tuple[tuple[str, str, str], ...] = (
    ("video", "video", "Video"),
    ("audio", "audio", "Audio"),
    ("text", "text", "Text"),
)


def run_workflow(request: WorkflowRequest, *, progress: ProgressCallback | None = None) -> WorkflowResult:
    """Run requested modalities in a fixed order, then build one combined workbook."""

    requested = _validate_request(request)
    detected_video: DetectedVideoSource | None = None
    video_provenance: VideoOutputProvenance | None = None
    video_request = requested.get("video")
    if video_request is not None:
        try:
            detected_video = detect_video_source(
                video_request.source_path,
                video_request.source_method,
            )
            validate_video_provider_options(
                detected_video.provider,
                include_landmarks=video_request.include_landmarks,
                include_timing=video_request.include_timing,
                exclude_geometry=video_request.exclude_geometry,
            )
            canonical_video = load_canonical_video(detected_video)
            video_provenance = canonical_video.output_provenance(detected_video)
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkflowError(f"Video source detection failed: {exc}") from exc
    output_root = Path(os.path.abspath(Path(request.output_root).expanduser()))
    _require_path_components_no_reparse(output_root, "Analysis output root")
    output_root.mkdir(parents=True, exist_ok=True)
    _require_no_reparse(output_root, "Analysis output root")
    history = output_root / "combined_analysis_history"
    manifest_path = output_root / "combined_analysis_manifest.json"
    started_at = _timestamp()
    modality_roots: dict[str, Path] = {}
    warnings: list[str] = list(request.warnings)
    if detected_video is not None:
        warnings.extend(detected_video.warnings)
    accepted_reports: list[DiscoveryEntry] = []
    rejected_reports: list[DiscoveryEntry] = []
    sources_by_modality = {}
    text_summaries = ()
    workbook_path: Path | None = None
    analysis_profile_path: Path | None = None
    reference_resolutions: tuple[ReferenceResolution, ...] = ()
    video_manifest_payload: Mapping[str, object] | None = None
    video_column_manifest_rows: tuple[dict[str, str], ...] = ()
    current_stage = "initialization"
    stale_artifact_policy: dict[str, object] = {
        "policy": "archive_fixed_outputs_before_run",
        "archive_directory": None,
        "archived_previous_workbook": None,
        "archived_previous_manifest": None,
        "archived_previous_workbook_sha256": None,
        "archived_previous_profile": None,
    }
    archive_preflight_complete = False

    try:
        stale_artifact_policy = _archive_fixed_outputs(output_root, started_at)
        archive_preflight_complete = True
        if request.analysis_profile is not None:
            analysis_profile_path = write_analysis_profile(request.analysis_profile, output_root)
        for name, combined_name, label in _MODALITIES:
            modality = requested.get(name)
            if modality is None:
                continue
            stage_label = "Text import" if name == "text" else f"{label} analysis"
            current_stage = stage_label
            _emit(progress, f"Starting {stage_label}")
            execution = _run_modality(
                modality,
                output_root,
                combined_name,
                detected_video=detected_video if name == "video" else None,
            )
            modality_roots[combined_name] = execution.stage_root
            if name == "text":
                try:
                    text_discovery = discover_text_results(execution.discovery_root)
                except TextResultsError as exc:
                    raise WorkflowError(f"Text import is invalid: {exc}") from exc
                text_summaries = text_discovery.summaries
                if request.analysis_profile is not None and text_discovery.grain == "speaker":
                    metadata = load_source_metadata(
                        request.analysis_profile.source_manifest,
                        expected_sha256=request.analysis_profile.source_manifest_sha256,
                    )
                    validate_text_profile_grouping(
                        metadata,
                        resolve_analysis_profile(metadata, request.analysis_profile),
                    )
                accepted_reports.extend(
                    DiscoveryEntry(
                        "text",
                        summary.speaker_id,
                        summary.display_name,
                        text_discovery.summary_path,
                        "accepted imported transcript construct summary",
                    )
                    for summary in text_summaries
                )
                _emit(progress, f"Completed {stage_label}: {execution.stage_root}")
                continue
            discovery_modality = (
                "native_face"
                if name == "video"
                and detected_video is not None
                and detected_video.provider == "pyfeat_native_face"
                else combined_name
            )
            discovery = _discover_stage_sources(execution.discovery_root, discovery_modality, label)
            if name == "video" and video_provenance is not None:
                normalized_sources = tuple(
                    replace(
                        source,
                        modality="video",
                        video_provenance=video_provenance,
                    )
                    for source in discovery.sources
                )
                discovery = replace(
                    discovery,
                    sources=normalized_sources,
                    accepted=tuple(replace(entry, modality="video") for entry in discovery.accepted),
                    rejected=tuple(replace(entry, modality="video") for entry in discovery.rejected),
                )
            sources_by_modality[combined_name] = discovery.sources
            accepted_reports.extend(discovery.accepted)
            rejected_reports.extend(discovery.rejected)
            if discovery.errors:
                details = "; ".join(discovery.errors)
                raise WorkflowError(f"{label} analysis produced invalid combined reports: {details}")
            if not discovery.sources:
                raise WorkflowError(f"{label} analysis produced no speaker-level combined reports")
            _emit(progress, f"Completed {label} analysis: {execution.stage_root}")

        if request.write_combined_workbook:
            current_stage = "combined workbook"
            _emit(progress, "Starting combined workbook")
            try:
                workbook_result = build_combined_workbook(
                    sources_by_modality,
                    output_root / "combined_analysis.xlsx",
                    headline_policy=request.headline_policy,
                    analysis_profile=request.analysis_profile,
                    speaker_groups=None if request.analysis_profile is not None else request.speaker_groups,
                    include_construct_comparison=request.include_construct_comparison,
                    text_summaries=text_summaries,
                )
                warnings.extend(workbook_result.warnings)
                workbook_path = workbook_result.workbook_path
                if video_provenance is not None:
                    video_manifest_payload = workbook_result.video_manifest_payload
                    video_column_manifest_rows = workbook_result.video_column_manifest_rows
                if request.include_probability_sheets and workbook_result.source_cells:
                    inference_result = add_probability_mirrors(
                        workbook_path,
                        workbook_result.source_cells,
                        default_reference=request.default_reference,
                        reference_overrides=request.reference_overrides,
                        confidence_level=request.confidence_level,
                    )
                    reference_resolutions = inference_result.reference_resolutions
                elif request.include_probability_sheets:
                    warnings.append(
                        "Probability sheets were skipped because imported Text constructs are not "
                        "calibrated as Video or Audio inference inputs."
                    )
            except Exception as exc:
                raise WorkflowError(f"Combined workbook failed: {exc}") from exc
            _emit(progress, "Completed combined workbook")
        elif video_provenance is not None:
            video_manifest_payload = {
                "requested_modality": "video",
                "sources": [video_provenance.to_manifest_payload()],
            }
            video_column_manifest_rows = video_provenance.to_column_manifest_rows()
        current_stage = "complete"

        if video_column_manifest_rows:
            atomic_write_csv(
                output_root / "video_column_manifest.csv",
                video_column_manifest_rows,
                tuple(video_column_manifest_rows[0]),
            )

        result = WorkflowResult(
            output_root,
            workbook_path,
            manifest_path,
            dict(modality_roots),
            tuple(warnings),
            analysis_profile_path,
        )
        _write_manifest(
            manifest_path,
            status="complete",
            started_at=started_at,
            request=request,
            modality_roots=modality_roots,
            accepted_reports=accepted_reports,
            rejected_reports=rejected_reports,
            workbook_path=workbook_path,
            warnings=warnings,
            reference_resolutions=reference_resolutions,
            stale_artifact_policy=stale_artifact_policy,
            video_manifest_payload=video_manifest_payload,
            video_column_manifest_rows=video_column_manifest_rows,
        )
        return result
    except Exception as exc:
        error = _sanitize_error(exc)
        if not archive_preflight_complete:
            raise WorkflowError(
                f"Archive preflight failed: {error}", stage="initialization"
            ) from exc
        stale_artifact_policy["archived_failed_workbook"] = _archive_failed_workbook(
            output_root,
            started_at,
            history,
        )
        _write_manifest(
            manifest_path,
            status="failed",
            started_at=started_at,
            request=request,
            modality_roots=modality_roots,
            accepted_reports=accepted_reports,
            rejected_reports=rejected_reports,
            workbook_path=None,
            warnings=warnings,
            reference_resolutions=reference_resolutions,
            stale_artifact_policy=stale_artifact_policy,
            video_manifest_payload=video_manifest_payload,
            video_column_manifest_rows=video_column_manifest_rows,
            failed_stage=current_stage,
            error=error,
        )
        if isinstance(exc, WorkflowError):
            raise WorkflowError(error, stage=current_stage) from exc
        raise WorkflowError(f"Workflow failed: {error}", stage=current_stage) from exc


def _validate_request(request: WorkflowRequest) -> dict[str, ModalityRequest]:
    modalities = tuple(request.modalities)
    profile_metadata = None
    resolved_profile = None
    if not modalities:
        raise WorkflowError("At least one Video, Audio, or Text modality is required")
    if request.write_combined_workbook and not request.speaker_groups and request.analysis_profile is None:
        raise WorkflowError("A profile or at least one speaker group is required for a combined workbook")
    if request.analysis_profile is not None:
        if request.speaker_groups:
            raise WorkflowError("Use either an Analysis profile or legacy speaker groups, not both")
        if not request.write_combined_workbook:
            raise WorkflowError("An Analysis profile requires the combined workbook")
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
            raise WorkflowError(f"Analysis profile source manifest is invalid: {exc}") from exc
    if request.headline_policy not in {"weighted", "equal"}:
        raise WorkflowError("Headline policy must be weighted or equal")
    try:
        confidence_level = float(request.confidence_level)
    except (TypeError, ValueError) as exc:
        raise WorkflowError("Confidence level must be between 0 and 1") from exc
    if not math.isfinite(confidence_level) or not 0.0 < confidence_level < 1.0:
        raise WorkflowError("Confidence level must be between 0 and 1")
    try:
        default_reference = float(request.default_reference)
    except (TypeError, ValueError) as exc:
        raise WorkflowError("Default reference must be finite") from exc
    if not math.isfinite(default_reference):
        raise WorkflowError("Default reference must be finite")
    for value in request.reference_overrides.values():
        try:
            finite = math.isfinite(float(value))
        except (TypeError, ValueError) as exc:
            raise WorkflowError("Reference overrides must be finite") from exc
        if not finite:
            raise WorkflowError("Reference overrides must be finite")

    requested: dict[str, ModalityRequest] = {}
    for modality in modalities:
        if modality.name not in {"video", "audio", "text"}:
            raise WorkflowError(f"Unsupported modality: {modality.name!r}")
        if modality.name in requested:
            raise WorkflowError(f"Duplicate modality: {modality.name}")
        if modality.source_method not in {"run", "import"}:
            raise WorkflowError(f"Unsupported source method for {modality.name}: {modality.source_method!r}")
        if modality.name == "text" and modality.source_method != "import":
            raise WorkflowError("Text results are import-only in the combined workflow")
        source = Path(modality.source_path).expanduser().resolve()
        if not source.is_dir():
            raise WorkflowError(f"{modality.name} source folder does not exist: {source}")
        requested[modality.name] = modality

    output_root = Path(os.path.abspath(Path(request.output_root).expanduser()))
    for modality in requested.values():
        source = Path(modality.source_path).expanduser().resolve()
        if modality.source_method == "run" and (
            _is_within(output_root, source) or _is_within(source, output_root)
        ):
            raise WorkflowError(
                f"Output root and {modality.name} run source must not overlap"
            )
        if modality.source_method == "import" and _is_within(output_root, source):
            raise WorkflowError("Output root must not be inside an imported report folder")
    if request.analysis_profile is not None:
        try:
            validate_source_manifest_associations(
                tuple(modality.source_path for modality in requested.values()),
                request.analysis_profile.source_manifest,
                request.analysis_profile.source_manifest_sha256,
            )
        except (OSError, ValueError) as exc:
            raise WorkflowError(
                "Analysis profile source manifest is not associated with the selected "
                "modality folders"
            ) from exc
        text_request = requested.get("text")
        if text_request is not None and not any(
            Path(text_request.source_path).rglob("video_level_summary.csv")
        ):
            try:
                validate_text_profile_grouping(profile_metadata, resolved_profile)
            except ValueError as exc:
                raise WorkflowError(str(exc)) from exc
    try:
        validate_video_reference_override_keys(tuple(request.reference_overrides))
    except ValueError as exc:
        raise WorkflowError(str(exc)) from exc
    return requested


def _run_modality(
    modality: ModalityRequest,
    output_root: Path,
    combined_name: str,
    *,
    detected_video: DetectedVideoSource | None = None,
) -> _ModalityExecution:
    if modality.source_method == "import":
        source = Path(modality.source_path).expanduser().resolve()
        return _ModalityExecution(source, source)

    stage_root = output_root / combined_name
    try:
        if modality.name == "video":
            if detected_video is None:
                raise WorkflowError("Canonical Video provider was not resolved")
            if detected_video.provider == "imotions_affdex":
                analysis_result = analyse_imotions_folder(
                    modality.source_path,
                    output_root=stage_root,
                    write_graphs=modality.write_graphs,
                    include_logscale=modality.include_logscale,
                    include_landmarks=modality.include_landmarks,
                    include_timing=modality.include_timing,
                    exclude_geometry=modality.exclude_geometry,
                )
            else:
                analysis_result = analyse_native_face_folder(
                    modality.source_path,
                    output_root=stage_root,
                    write_graphs=modality.write_graphs,
                    include_logscale=modality.include_logscale,
                )
        else:
            analysis_result = analyse_audio_folder(
                modality.source_path,
                output_root=stage_root,
                write_graphs=modality.write_graphs,
                include_logscale=modality.include_logscale,
            )
    except Exception as exc:
        label = "Video" if modality.name == "video" else "Audio"
        raise WorkflowError(f"{label} analysis failed: {exc}") from exc
    stage_root = stage_root.resolve()
    discovery_root = analysis_result.domain_output_dirs.get("emotion", analysis_result.output_dir).resolve()
    return _ModalityExecution(stage_root, discovery_root)


def _discover_stage_sources(root: Path, modality: str, label: str) -> CombinedDiscoveryResult:
    try:
        return discover_combined_sources_audited(root, modality)
    except Exception as exc:
        raise WorkflowError(f"{label} analysis produced invalid combined reports: {exc}") from exc


def _write_manifest(
    path: Path,
    *,
    status: str,
    started_at: str,
    request: WorkflowRequest,
    modality_roots: Mapping[str, Path],
    accepted_reports: list[DiscoveryEntry],
    rejected_reports: list[DiscoveryEntry],
    workbook_path: Path | None,
    warnings: list[str],
    reference_resolutions: tuple[ReferenceResolution, ...],
    stale_artifact_policy: Mapping[str, object],
    video_manifest_payload: Mapping[str, object] | None = None,
    video_column_manifest_rows: Sequence[Mapping[str, str]] = (),
    failed_stage: str | None = None,
    error: str | None = None,
) -> None:
    payload = {
        "schema_version": 2,
        "software": {
            "name": "Multimodal Emotion Analysis Tool",
            "version": __version__,
            "git_revision": _git_revision(),
        },
        "status": status,
        "started_at": started_at,
        "finished_at": _timestamp(),
        "request": {
            "output_root": str(Path(request.output_root).expanduser().resolve()),
            "modalities": [
                {
                    "name": modality.name,
                    "source_method": modality.source_method,
                    "source_path": str(Path(modality.source_path).expanduser().resolve()),
                    "write_graphs": modality.write_graphs,
                    "include_logscale": modality.include_logscale,
                    "include_landmarks": modality.include_landmarks,
                    "include_timing": modality.include_timing,
                    "exclude_geometry": modality.exclude_geometry,
                }
                for modality in request.modalities
            ],
            "speaker_groups": [
                {"id": group.group_id, "name": group.name, "speaker_ids": list(group.speaker_ids)}
                for group in request.speaker_groups
            ],
            "write_combined_workbook": request.write_combined_workbook,
            "include_construct_comparison": request.include_construct_comparison,
            "include_probability_sheets": request.include_probability_sheets,
            "confidence_level": request.confidence_level,
            "headline_policy": request.headline_policy,
            "default_reference": request.default_reference,
            "reference_overrides": dict(request.reference_overrides),
            **(
                {"analysis_profile": profile_payload(request.analysis_profile)}
                if request.analysis_profile is not None
                else {}
            ),
        },
        "modality_roots": {name: str(root) for name, root in modality_roots.items()},
        "accepted_reports": [_discovery_payload(entry) for entry in accepted_reports],
        "rejected_reports": [_discovery_payload(entry) for entry in rejected_reports],
        "workbook_path": str(workbook_path) if workbook_path else None,
        **(
            {"analysis_profile_path": str(path.parent / "analysis_profile.json")}
            if request.analysis_profile is not None
            else {}
        ),
        "warnings": warnings,
        "reference_resolutions": [
            {
                "original_key": item.original_key,
                "matched_scope": item.matched_scope,
                "matched_source": item.matched_source,
                "resolved_reference": item.resolved_reference,
            }
            for item in reference_resolutions
        ],
        "stale_artifact_policy": dict(stale_artifact_policy),
        "video": dict(video_manifest_payload) if video_manifest_payload is not None else None,
        "video_column_manifest_path": (
            str((path.parent / "video_column_manifest.csv").resolve())
            if video_column_manifest_rows
            else None
        ),
        "video_column_manifest_rows": [dict(row) for row in video_column_manifest_rows],
        "failed_stage": failed_stage,
        "error": error,
    }
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _archive_fixed_outputs(output_root: Path, started_at: str) -> dict[str, object]:
    """Stage and verify a complete prior result before changing fixed paths."""

    output_root = Path(os.path.abspath(Path(output_root).expanduser()))
    history = _validated_history_directory(output_root)
    workbook = output_root / "combined_analysis.xlsx"
    manifest = output_root / "combined_analysis_manifest.json"
    profile = output_root / "analysis_profile.json"
    video_column_manifest = output_root / "video_column_manifest.csv"
    result: dict[str, object] = {
        "policy": "archive_fixed_outputs_before_run",
        "archive_directory": None,
        "archived_previous_workbook": None,
        "archived_previous_manifest": None,
        "archived_previous_workbook_sha256": None,
        "archived_previous_profile": None,
        "archived_previous_video_column_manifest": None,
        "quarantined_failed_directory": None,
        "quarantined_failed_workbook": None,
        "quarantined_failed_manifest": None,
        "quarantined_failed_profile": None,
        "quarantined_failed_video_column_manifest": None,
    }
    if not any(
        path.exists() for path in (workbook, manifest, profile, video_column_manifest)
    ):
        return result
    history = _validated_history_directory(output_root, history, create=True)

    for path in (workbook, manifest, profile, video_column_manifest):
        if path.exists():
            _require_regular_archive_file(path)
    if not manifest.exists():
        raise WorkflowError(
            "A prior Analysis result must contain both combined_analysis.xlsx and its manifest."
        )
    try:
        loaded = read_control_json(
            manifest,
            label="workflow manifest",
            max_bytes=MAX_WORKFLOW_MANIFEST_JSON_BYTES,
            max_items=MAX_WORKFLOW_MANIFEST_JSON_ITEMS,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError("The prior Analysis manifest cannot be archived safely.") from exc
    if not isinstance(loaded, dict) or loaded.get("status") not in {"complete", "failed"}:
        raise WorkflowError("The prior Analysis manifest has an unsupported status.")
    if loaded.get("status") == "failed":
        return _quarantine_failed_fixed_outputs(
            history,
            started_at,
            workbook=workbook,
            manifest=manifest,
            profile=profile,
            video_column_manifest=video_column_manifest,
            result=result,
            previous_manifest=loaded,
        )
    if not workbook.exists():
        raise WorkflowError(
            "A prior Analysis result must contain both combined_analysis.xlsx and its manifest."
        )
    previous_manifest = dict(loaded)
    recorded_workbook = Path(
        str(previous_manifest.get("workbook_path") or "")
    ).expanduser().resolve()
    if recorded_workbook != workbook.resolve():
        raise WorkflowError("The prior Analysis manifest does not identify the fixed workbook.")
    profile_expected = "analysis_profile_path" in previous_manifest
    if profile_expected != profile.exists():
        raise WorkflowError("The prior Analysis profile and manifest are incomplete.")
    if profile_expected and (
        Path(str(previous_manifest["analysis_profile_path"])).expanduser().resolve()
        != profile.resolve()
    ):
        raise WorkflowError("The prior Analysis manifest does not identify the fixed profile.")
    video_column_manifest_expected = bool(
        previous_manifest.get("video_column_manifest_path")
    )
    if video_column_manifest_expected != video_column_manifest.exists():
        raise WorkflowError("The prior Video column manifest and workflow manifest are incomplete.")
    if video_column_manifest_expected and (
        Path(str(previous_manifest["video_column_manifest_path"])).expanduser().resolve()
        != video_column_manifest.resolve()
    ):
        raise WorkflowError(
            "The prior workflow manifest does not identify the fixed Video column manifest."
        )

    previous_started_at = (
        str(previous_manifest.get("started_at"))
        if previous_manifest.get("started_at")
        else started_at
    )
    run_stamp = re.sub(r"[^0-9]", "", previous_started_at)[:20] or "unknown"
    archive_directory = _unused_history_path(history, f"run_{run_stamp}")
    staging = _unused_history_path(
        history,
        f".{archive_directory.name}.staging-{os.getpid()}",
    )
    staging.mkdir()
    _require_no_reparse(staging, "Analysis history staging directory")

    archived_workbook = archive_directory / workbook.name
    archived_profile = archive_directory / profile.name
    archived_manifest = archive_directory / manifest.name
    archived_video_column_manifest = archive_directory / video_column_manifest.name
    staged_workbook = staging / workbook.name
    staged_profile = staging / profile.name
    staged_manifest = staging / manifest.name
    staged_video_column_manifest = staging / video_column_manifest.name
    workbook_hash: str | None = None
    profile_hash: str | None = None
    video_column_manifest_hash: str | None = None
    committed = False
    try:
        workbook_hash = _file_sha256(workbook)
        profile_hash = _file_sha256(profile) if profile_expected else None
        video_column_manifest_hash = (
            _file_sha256(video_column_manifest)
            if video_column_manifest_expected
            else None
        )
        _copy_archive_file(workbook, staged_workbook)
        if _file_sha256(staged_workbook) != workbook_hash:
            raise WorkflowError("Staged Analysis workbook verification failed.")
        if profile_expected:
            _copy_archive_file(profile, staged_profile)
            if _file_sha256(staged_profile) != profile_hash:
                raise WorkflowError("Staged Analysis profile verification failed.")
        if video_column_manifest_expected:
            _copy_archive_file(video_column_manifest, staged_video_column_manifest)
            if _file_sha256(staged_video_column_manifest) != video_column_manifest_hash:
                raise WorkflowError("Staged Video column manifest verification failed.")

        previous_manifest["workbook_path"] = str(archived_workbook.resolve())
        if profile_expected:
            previous_manifest["analysis_profile_path"] = str(archived_profile.resolve())
        if video_column_manifest_expected:
            previous_manifest["video_column_manifest_path"] = str(
                archived_video_column_manifest.resolve()
            )
        archive_metadata: dict[str, object] = {
            "archived_at": started_at,
            "archive_directory": str(archive_directory.resolve()),
            "original_workbook_path": str(workbook.resolve()),
            "workbook_sha256": workbook_hash,
        }
        if profile_hash is not None:
            archive_metadata.update(
                {
                    "original_analysis_profile_path": str(profile.resolve()),
                    "analysis_profile_sha256": profile_hash,
                }
            )
        if video_column_manifest_hash is not None:
            archive_metadata.update(
                {
                    "original_video_column_manifest_path": str(
                        video_column_manifest.resolve()
                    ),
                    "video_column_manifest_sha256": video_column_manifest_hash,
                }
            )
        previous_manifest["archive"] = archive_metadata
        staged_manifest.write_text(
            json.dumps(previous_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verified_manifest = read_control_json(
            staged_manifest,
            label="staged workflow manifest",
            max_bytes=MAX_WORKFLOW_MANIFEST_JSON_BYTES,
            max_items=MAX_WORKFLOW_MANIFEST_JSON_ITEMS,
        )
        if (
            not isinstance(verified_manifest, dict)
            or verified_manifest.get("archive") != archive_metadata
        ):
            raise WorkflowError("Staged Analysis manifest verification failed.")

        os.replace(staging, archive_directory)
        committed = True
    finally:
        if not committed and staging.exists():
            shutil.rmtree(staging)

    if workbook_hash is None:
        raise WorkflowError("Staged Analysis workbook verification failed.")

    # The verified archive is durable before the fixed trio changes. Move the
    # whole trio into one retirement directory with rollback so a Windows
    # delete-sharing lock cannot split the root result.
    retirement = _unused_history_path(
        history,
        f".{archive_directory.name}.retiring-{os.getpid()}",
    )
    retirement.mkdir()
    _require_no_reparse(retirement, "Analysis history retirement directory")
    fixed_moves = [(workbook, retirement / workbook.name)]
    if profile_expected:
        fixed_moves.append((profile, retirement / profile.name))
    if video_column_manifest_expected:
        fixed_moves.append(
            (video_column_manifest, retirement / video_column_manifest.name)
        )
    fixed_moves.append((manifest, retirement / manifest.name))
    try:
        _move_files_with_rollback(fixed_moves)
    except Exception:
        if retirement.exists():
            shutil.rmtree(retirement)
        if archive_directory.exists():
            shutil.rmtree(archive_directory)
        raise
    try:
        shutil.rmtree(retirement)
    except OSError:
        result["retained_originals_directory"] = str(retirement)

    result["archive_directory"] = str(archive_directory.resolve())
    result["archived_previous_workbook"] = str(archived_workbook.resolve())
    result["archived_previous_workbook_sha256"] = workbook_hash
    result["archived_previous_manifest"] = str(archived_manifest.resolve())
    if profile_expected:
        result["archived_previous_profile"] = str(archived_profile.resolve())
    if video_column_manifest_expected:
        result["archived_previous_video_column_manifest"] = str(
            archived_video_column_manifest.resolve()
        )
    return result


def _quarantine_failed_fixed_outputs(
    history: Path,
    started_at: str,
    *,
    workbook: Path,
    manifest: Path,
    profile: Path,
    video_column_manifest: Path,
    result: dict[str, object],
    previous_manifest: Mapping[str, object],
) -> dict[str, object]:
    """Move a failed fixed state aside as one rollback-safe set for retry."""

    previous_started_at = str(previous_manifest.get("started_at") or started_at)
    run_stamp = re.sub(r"[^0-9]", "", previous_started_at)[:20] or "unknown"
    quarantine = _unused_history_path(history, f"failed_run_{run_stamp}")
    quarantine.mkdir()
    _require_no_reparse(quarantine, "Failed Analysis quarantine directory")
    existing = tuple(
        path
        for path in (workbook, profile, video_column_manifest, manifest)
        if path.exists()
    )
    moves = tuple((path, quarantine / path.name) for path in existing)
    try:
        _move_files_with_rollback(moves)
    except Exception:
        if quarantine.exists():
            shutil.rmtree(quarantine)
        raise
    result["quarantined_failed_directory"] = str(quarantine)
    if workbook in existing:
        result["quarantined_failed_workbook"] = str(quarantine / workbook.name)
    if manifest in existing:
        result["quarantined_failed_manifest"] = str(quarantine / manifest.name)
    if profile in existing:
        result["quarantined_failed_profile"] = str(quarantine / profile.name)
    if video_column_manifest in existing:
        result["quarantined_failed_video_column_manifest"] = str(
            quarantine / video_column_manifest.name
        )
    return result


def _validated_history_directory(
    output_root: Path,
    expected: Path | None = None,
    *,
    create: bool = False,
) -> Path:
    """Return the lexical in-root history directory after reparse checks."""

    output_root = Path(os.path.abspath(Path(output_root).expanduser()))
    _require_no_reparse(output_root, "Analysis output root")
    history = output_root / "combined_analysis_history"
    if expected is not None and Path(os.path.abspath(expected)) != history:
        raise WorkflowError("Analysis history directory does not match the validated output root.")
    if history.exists():
        _require_no_reparse(history, "Analysis history directory")
    elif create:
        history.mkdir()
        _require_no_reparse(history, "Analysis history directory")
    return history


def _unused_history_path(history: Path, base_name: str) -> Path:
    candidate = history / base_name
    suffix = 2
    while candidate.exists():
        if _is_reparse_point(candidate):
            raise WorkflowError(f"Analysis history entry is a junction or reparse point: {candidate.name}")
        candidate = history / f"{base_name}-{suffix}"
        suffix += 1
    return candidate


def _move_files_with_rollback(moves: Sequence[tuple[Path, Path]]) -> None:
    moved: list[tuple[Path, Path]] = []
    try:
        for source, destination in moves:
            os.replace(source, destination)
            moved.append((source, destination))
    except Exception as exc:
        rollback_error: OSError | None = None
        for source, destination in reversed(moved):
            try:
                os.replace(destination, source)
            except OSError as rollback_exc:
                rollback_error = rollback_exc
        if rollback_error is not None:
            raise WorkflowError(
                "Analysis fixed-output cleanup failed and could not restore the prior complete set."
            ) from rollback_error
        raise exc


def _copy_archive_file(source: Path, destination: Path) -> None:
    """Copy one preflight-validated artifact into the private staging directory."""

    shutil.copyfile(source, destination)


def _require_regular_archive_file(path: Path) -> None:
    if _is_reparse_point(path) or not path.is_file():
        raise WorkflowError(f"Analysis archive source must be a regular non-reparse file: {path.name}")


def _require_no_reparse(path: Path, label: str) -> None:
    lexical = Path(os.path.abspath(path))
    _require_path_components_no_reparse(lexical, label)
    if not lexical.is_dir():
        raise WorkflowError(f"{label} must be a regular directory without junctions or reparse points.")


def _require_path_components_no_reparse(path: Path, label: str) -> None:
    """Reject a reparse point in an existing or not-yet-created path boundary."""

    lexical = Path(os.path.abspath(path))
    for component in (lexical, *lexical.parents):
        if _is_reparse_point(component):
            raise WorkflowError(
                f"{label} must not pass through a junction or reparse point: {component}"
            )


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive_failed_workbook(
    output_root: Path,
    started_at: str,
    history: Path | None = None,
) -> str | None:
    """Move a partial workbook out of the fixed success location after failure."""

    output_root = Path(os.path.abspath(Path(output_root).expanduser()))
    history = _validated_history_directory(output_root, history, create=True)
    workbook = output_root / "combined_analysis.xlsx"
    if not workbook.exists():
        return None
    _require_regular_archive_file(workbook)
    run_stamp = re.sub(r"[^0-9]", "", started_at)[:20]
    destination = history / f"combined_analysis_failed_{run_stamp}.xlsx"
    suffix = 2
    while destination.exists():
        if _is_reparse_point(destination):
            raise WorkflowError("Failed-workbook history entry is a junction or reparse point.")
        destination = history / f"combined_analysis_failed_{run_stamp}_{suffix}.xlsx"
        suffix += 1
    os.replace(workbook, destination)
    return str(destination.resolve())


def _sanitize_error(exc: BaseException) -> str:
    """Return one safe line for manifests and launcher output."""

    message = re.sub(r"\s+", " ", str(exc)).strip() or exc.__class__.__name__
    message = re.sub(
        r"(?i)(authorization|api[_ -]?key|token)\s*[=:]\s*\S+",
        r"\1=[redacted]",
        message,
    )
    message = re.sub(r"\bhf_[A-Za-z0-9_-]{4,}\b", "[redacted]", message)
    return message[:1000]


def _discovery_payload(entry: DiscoveryEntry) -> dict[str, object]:
    return {
        "modality": entry.modality,
        "normalized_speaker": entry.normalized_speaker,
        "display_speaker": entry.display_speaker,
        "path": str(entry.path),
        "reason": entry.reason,
    }


def _git_revision() -> str | None:
    """Return the checkout revision when Git metadata is available."""

    repository = Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = completed.stdout.strip()
    return revision if completed.returncode == 0 and re.fullmatch(r"[0-9a-fA-F]{40}", revision) else None


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)
    else:
        print(message, flush=True)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _parse_json(value: str, option: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"{option} must be valid JSON") from exc


def _speaker_groups_from_json(value: str) -> tuple[SpeakerGroupDefinition, ...]:
    payload = _parse_json(value, "--speaker-groups-json")
    if not isinstance(payload, list):
        raise WorkflowError("--speaker-groups-json must contain a list")
    groups: list[SpeakerGroupDefinition] = []
    for item in payload:
        if not isinstance(item, dict):
            raise WorkflowError("Each speaker group must be an object")
        group_id = item.get("id", item.get("group_id"))
        name = item.get("name")
        speaker_ids = item.get("speaker_ids", item.get("speakerKeys", item.get("speaker_keys")))
        if not isinstance(group_id, str) or not isinstance(name, str) or not isinstance(speaker_ids, list):
            raise WorkflowError("Each speaker group needs id, name, and speaker_ids")
        if not all(isinstance(speaker, str) for speaker in speaker_ids):
            raise WorkflowError("Each speaker group speaker_ids entry must be text")
        groups.append(SpeakerGroupDefinition(group_id, name, tuple(speaker_ids)))
    return tuple(groups)


def _mapping_from_json(value: str) -> Mapping[str, float]:
    payload = _parse_json(value, "--reference-overrides-json")
    if not isinstance(payload, dict):
        raise WorkflowError("--reference-overrides-json must contain an object")
    overrides: dict[str, float] = {}
    for key, number in payload.items():
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise WorkflowError("Reference override values must be finite numbers")
        converted = float(number)
        if not math.isfinite(converted):
            raise WorkflowError("Reference override values must be finite numbers")
        overrides[str(key)] = converted
    return overrides


def _finite_cli_number(value: object, option: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkflowError(f"{option} must be a finite number") from exc
    if not math.isfinite(number):
        raise WorkflowError(f"{option} must be a finite number")
    return number


class _WorkflowArgumentParser(argparse.ArgumentParser):
    """Prevent argparse from echoing malformed submitted values or exiting noisily."""

    def error(self, message: str) -> None:
        raise WorkflowError("Invalid command-line arguments")


def build_parser() -> argparse.ArgumentParser:
    parser = _WorkflowArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    for name in ("video", "imotions", "native_face", "audio", "text"):
        parser.add_argument(f"--{name}-source", type=Path)
        parser.add_argument(f"--{name}-method", choices=("run", "import"))
    parser.add_argument("--no-combined-workbook", action="store_true")
    parser.add_argument("--no-construct-comparison", action="store_true")
    parser.add_argument("--no-probability-sheets", action="store_true")
    parser.add_argument("--confidence-level", default="0.95")
    parser.add_argument("--headline-policy", choices=("weighted", "equal"), default="weighted")
    parser.add_argument("--default-reference", default="0.0")
    parser.add_argument("--reference-overrides-json", default="{}")
    parser.add_argument("--speaker-groups-json", default="[]")
    parser.add_argument("--analysis-profile-json", default="")
    parser.add_argument("--no-graphs", action="store_true")
    parser.add_argument("--logscale", action="store_true")
    parser.add_argument("--include-landmarks", action="store_true")
    parser.add_argument("--include-timing", action="store_true")
    parser.add_argument("--exclude-geometry", action="store_true")
    return parser


def request_from_cli(argv: list[str] | None = None) -> WorkflowRequest:
    """Parse canonical and one-release compatibility flags into one request."""

    args = build_parser().parse_args(argv)
    modalities: list[ModalityRequest] = []
    request_warnings: list[str] = []

    alias_components = {
        name: (getattr(args, f"{name}_source"), getattr(args, f"{name}_method"))
        for name in ("imotions", "native_face")
    }
    if all(any(values) for values in alias_components.values()):
        raise WorkflowError("Video provider aliases cannot be combined; supply one Video source")

    video_candidates: list[tuple[str, Path, str]] = []
    for name in ("video", "imotions", "native_face"):
        source = getattr(args, f"{name}_source")
        method = getattr(args, f"{name}_method")
        if bool(source) != bool(method):
            raise WorkflowError(f"--{name}-source and --{name}-method must be supplied together")
        if source:
            video_candidates.append((name, source, method))
    if len(video_candidates) > 1:
        raise WorkflowError("Supply exactly one Video source; canonical and provider aliases cannot be combined")
    if video_candidates:
        name, source, method = video_candidates[0]
        modalities.append(
            ModalityRequest(
                name="video",
                source_method=method,
                source_path=source,
                write_graphs=not args.no_graphs,
                include_logscale=args.logscale,
                include_landmarks=args.include_landmarks,
                include_timing=args.include_timing,
                exclude_geometry=args.exclude_geometry,
            )
        )
        if name != "video":
            request_warnings.append(
                f"--{name}-source and --{name}-method are deprecated compatibility aliases; "
                "use --video-source and --video-method."
            )

    for name in ("audio", "text"):
        source = getattr(args, f"{name}_source")
        method = getattr(args, f"{name}_method")
        if bool(source) != bool(method):
            raise WorkflowError(f"--{name}-source and --{name}-method must be supplied together")
        if source:
            modalities.append(
                ModalityRequest(
                    name=name,
                    source_method=method,
                    source_path=source,
                    write_graphs=not args.no_graphs,
                    include_logscale=args.logscale,
                    include_landmarks=args.include_landmarks,
                    include_timing=args.include_timing,
                    exclude_geometry=args.exclude_geometry,
                )
            )
    return WorkflowRequest(
        output_root=args.output_root,
        modalities=tuple(modalities),
        speaker_groups=_speaker_groups_from_json(args.speaker_groups_json),
        write_combined_workbook=not args.no_combined_workbook,
        include_construct_comparison=not args.no_construct_comparison,
        include_probability_sheets=not args.no_probability_sheets,
        confidence_level=_finite_cli_number(args.confidence_level, "--confidence-level"),
        headline_policy=args.headline_policy,
        default_reference=_finite_cli_number(args.default_reference, "--default-reference"),
        reference_overrides=_mapping_from_json(args.reference_overrides_json),
        analysis_profile=(
            profile_from_payload(
                _parse_json(args.analysis_profile_json, "--analysis-profile-json")
            )
            if args.analysis_profile_json
            else None
        ),
        warnings=tuple(request_warnings),
    )


def main(argv: list[str] | None = None) -> int:
    try:
        request = request_from_cli(argv)
        for warning in request.warnings:
            print(f"DeprecationWarning: {warning}", file=sys.stderr, flush=True)
        run_workflow(request)
    except Exception as exc:
        if not isinstance(exc, WorkflowError):
            exc = WorkflowError("Invalid workflow request")
        stage = f" [{exc.stage}]" if exc.stage else ""
        print(f"WorkflowError{stage}: {_sanitize_error(exc)}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
