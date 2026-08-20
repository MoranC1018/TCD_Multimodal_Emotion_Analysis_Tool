"""Coordinate Video, Audio, and imported Text results into one analysis workbook."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal, Mapping

from analysis.audio import analyse_audio_folder
from analysis.combined_summary import (
    CombinedDiscoveryResult,
    DiscoveryEntry,
    SpeakerGroupDefinition,
    build_combined_workbook,
    discover_combined_sources_audited,
)
from analysis.imotions import analyse_imotions_folder
from analysis.inference import ReferenceResolution, add_probability_mirrors
from analysis.text_results import TextResultsError, discover_text_results
from analysis import __version__
from procurement.input_limits import (
    MAX_WORKFLOW_MANIFEST_JSON_BYTES,
    MAX_WORKFLOW_MANIFEST_JSON_ITEMS,
    read_control_json,
)


ProgressCallback = Callable[[str], None]


class WorkflowError(RuntimeError):
    """Raised when a workflow stage cannot complete."""

    def __init__(self, message: str, *, stage: str | None = None) -> None:
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True)
class ModalityRequest:
    name: Literal["imotions", "audio", "text"]
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


@dataclass(frozen=True)
class WorkflowResult:
    output_root: Path
    workbook_path: Path | None
    manifest_path: Path
    modality_roots: Mapping[str, Path]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _ModalityExecution:
    stage_root: Path
    discovery_root: Path


_MODALITIES: tuple[tuple[str, str, str], ...] = (
    ("imotions", "video", "Video / iMotions"),
    ("audio", "audio", "Audio"),
    ("text", "text", "Text"),
)


def run_workflow(request: WorkflowRequest, *, progress: ProgressCallback | None = None) -> WorkflowResult:
    """Run requested modalities in a fixed order, then build one combined workbook."""

    requested = _validate_request(request)
    output_root = Path(request.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "combined_analysis_manifest.json"
    started_at = _timestamp()
    modality_roots: dict[str, Path] = {}
    warnings: list[str] = []
    accepted_reports: list[DiscoveryEntry] = []
    rejected_reports: list[DiscoveryEntry] = []
    sources_by_modality = {}
    text_summaries = ()
    workbook_path: Path | None = None
    reference_resolutions: tuple[ReferenceResolution, ...] = ()
    current_stage = "initialization"
    stale_artifact_policy: dict[str, object] = {
        "policy": "archive_fixed_outputs_before_run",
        "archive_directory": None,
        "archived_previous_workbook": None,
        "archived_previous_manifest": None,
        "archived_previous_workbook_sha256": None,
    }

    try:
        stale_artifact_policy = _archive_fixed_outputs(output_root, started_at)
        for name, combined_name, label in _MODALITIES:
            modality = requested.get(name)
            if modality is None:
                continue
            stage_label = "Text import" if name == "text" else f"{label} analysis"
            current_stage = stage_label
            _emit(progress, f"Starting {stage_label}")
            execution = _run_modality(modality, output_root, combined_name)
            modality_roots[combined_name] = execution.stage_root
            if name == "text":
                try:
                    text_discovery = discover_text_results(execution.discovery_root)
                except TextResultsError as exc:
                    raise WorkflowError(f"Text import is invalid: {exc}") from exc
                text_summaries = text_discovery.summaries
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
            discovery = _discover_stage_sources(execution.discovery_root, combined_name, label)
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
                    speaker_groups=request.speaker_groups,
                    headline_policy=request.headline_policy,
                    include_construct_comparison=request.include_construct_comparison,
                    text_summaries=text_summaries,
                )
                warnings.extend(workbook_result.warnings)
                workbook_path = workbook_result.workbook_path
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
        current_stage = "complete"

        result = WorkflowResult(output_root, workbook_path, manifest_path, dict(modality_roots), tuple(warnings))
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
        )
        return result
    except Exception as exc:
        error = _sanitize_error(exc)
        stale_artifact_policy["archived_failed_workbook"] = _archive_failed_workbook(
            output_root,
            started_at,
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
            failed_stage=current_stage,
            error=error,
        )
        if isinstance(exc, WorkflowError):
            raise WorkflowError(error, stage=current_stage) from exc
        raise WorkflowError(f"Workflow failed: {error}", stage=current_stage) from exc


def _validate_request(request: WorkflowRequest) -> dict[str, ModalityRequest]:
    modalities = tuple(request.modalities)
    if not modalities:
        raise WorkflowError("At least one Video / iMotions, Audio, or Text modality is required")
    if request.write_combined_workbook and not request.speaker_groups:
        raise WorkflowError("At least one speaker group is required for a combined workbook")
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
        if modality.name not in {"imotions", "audio", "text"}:
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

    output_root = Path(request.output_root).expanduser().resolve()
    for modality in requested.values():
        source = Path(modality.source_path).expanduser().resolve()
        if modality.source_method == "import":
            if _is_within(output_root, source):
                raise WorkflowError("Output root must not be inside an imported report folder")
    return requested


def _run_modality(modality: ModalityRequest, output_root: Path, combined_name: str) -> _ModalityExecution:
    if modality.source_method == "import":
        source = Path(modality.source_path).expanduser().resolve()
        return _ModalityExecution(source, source)

    stage_root = output_root / combined_name
    try:
        if modality.name == "imotions":
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
            analysis_result = analyse_audio_folder(
                modality.source_path,
                output_root=stage_root,
                write_graphs=modality.write_graphs,
                include_logscale=modality.include_logscale,
            )
    except Exception as exc:
        label = "Video / iMotions" if modality.name == "imotions" else "Audio"
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
        },
        "modality_roots": {name: str(root) for name, root in modality_roots.items()},
        "accepted_reports": [_discovery_payload(entry) for entry in accepted_reports],
        "rejected_reports": [_discovery_payload(entry) for entry in rejected_reports],
        "workbook_path": str(workbook_path) if workbook_path else None,
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
        "failed_stage": failed_stage,
        "error": error,
    }
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _archive_fixed_outputs(output_root: Path, started_at: str) -> dict[str, object]:
    """Move a prior fixed-name result into one self-contained history directory."""

    workbook = output_root / "combined_analysis.xlsx"
    manifest = output_root / "combined_analysis_manifest.json"
    result: dict[str, object] = {
        "policy": "archive_fixed_outputs_before_run",
        "archive_directory": None,
        "archived_previous_workbook": None,
        "archived_previous_manifest": None,
        "archived_previous_workbook_sha256": None,
    }
    if not workbook.exists() and not manifest.exists():
        return result

    previous_manifest: dict[str, object] | None = None
    if manifest.exists():
        try:
            loaded = read_control_json(
                manifest,
                label="workflow manifest",
                max_bytes=MAX_WORKFLOW_MANIFEST_JSON_BYTES,
                max_items=MAX_WORKFLOW_MANIFEST_JSON_ITEMS,
            )
        except (OSError, json.JSONDecodeError):
            loaded = None
        if isinstance(loaded, dict):
            previous_manifest = loaded

    history = output_root / "combined_analysis_history"
    history.mkdir(parents=True, exist_ok=True)
    previous_started_at = (
        str(previous_manifest.get("started_at"))
        if previous_manifest and previous_manifest.get("started_at")
        else started_at
    )
    run_stamp = re.sub(r"[^0-9]", "", previous_started_at)[:20] or "unknown"
    archive_directory = history / f"run_{run_stamp}"
    suffix = 2
    while archive_directory.exists():
        archive_directory = history / f"run_{run_stamp}_{suffix}"
        suffix += 1
    archive_directory.mkdir()
    result["archive_directory"] = str(archive_directory.resolve())

    archived_workbook = archive_directory / workbook.name
    workbook_hash: str | None = None
    if workbook.exists():
        workbook_hash = _file_sha256(workbook)
        os.replace(workbook, archived_workbook)
        result["archived_previous_workbook"] = str(archived_workbook.resolve())
        result["archived_previous_workbook_sha256"] = workbook_hash

    if manifest.exists():
        archived_manifest = archive_directory / manifest.name
        os.replace(manifest, archived_manifest)
        if previous_manifest is not None:
            previous_manifest["workbook_path"] = (
                str(archived_workbook.resolve()) if archived_workbook.exists() else None
            )
            previous_manifest["archive"] = {
                "archived_at": started_at,
                "archive_directory": str(archive_directory.resolve()),
                "original_workbook_path": str(workbook.resolve()),
                "workbook_sha256": workbook_hash,
            }
            temporary = archived_manifest.with_name(f".{archived_manifest.name}.tmp")
            temporary.write_text(
                json.dumps(previous_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, archived_manifest)
        result["archived_previous_manifest"] = str(archived_manifest.resolve())
    return result


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive_failed_workbook(output_root: Path, started_at: str) -> str | None:
    """Move a partial workbook out of the fixed success location after failure."""

    workbook = output_root / "combined_analysis.xlsx"
    if not workbook.exists():
        return None
    history = output_root / "combined_analysis_history"
    history.mkdir(parents=True, exist_ok=True)
    run_stamp = re.sub(r"[^0-9]", "", started_at)[:20]
    destination = history / f"combined_analysis_failed_{run_stamp}.xlsx"
    suffix = 2
    while destination.exists():
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
    for name in ("imotions", "audio", "text"):
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
    parser.add_argument("--no-graphs", action="store_true")
    parser.add_argument("--logscale", action="store_true")
    parser.add_argument("--include-landmarks", action="store_true")
    parser.add_argument("--include-timing", action="store_true")
    parser.add_argument("--exclude-geometry", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        modalities: list[ModalityRequest] = []
        for name in ("imotions", "audio", "text"):
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
        request = WorkflowRequest(
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
        )
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
