from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence

from spreadsheet_safety import SpreadsheetSafeWriter
from processing.io_utils import assert_no_output_path_aliases, assert_safe_output_path

from . import config
from .emotion_models import EmotionModelBundle, EmotionModels, load_debug_fallback_emotion_models
from .full_stack import export_batch_to_analysis_audio_outputs
from .pipeline import ProgressCallback, SingleVideoResult, emit_progress, run_single_video
from .source_context import copy_run_sidecars, load_source_context


STITCHED_VIDEO_NAME = "stitched_imotions.mp4"
CATALOG_INTERNAL_DIRECTORIES = frozenset({"_clean_speaker_beta_cache", "_downloads"})
MAX_AUDIO_BATCH_FILES = 10_000
MAX_AUDIO_BATCH_BYTES = 100 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class VideoJob:
    input_video: Path
    relative_output_dir: Path
    source_context: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class BatchResult:
    output_root: Path
    manifest_csv: Path
    run_log: Path
    processed_count: int
    failed_count: int


def discover_videos(
    input_path: Path,
    *,
    selected_source_ids: Sequence[str] | None = None,
) -> list[VideoJob]:
    """Find the videos this stage should analyse, preserving folder structure."""

    input_path = input_path.expanduser().resolve()
    if input_path.is_file():
        if input_path.suffix.lower() != ".mp4":
            raise ValueError(f"Input file is not an MP4: {input_path}")
        jobs = [
            VideoJob(
                input_video=input_path,
                relative_output_dir=Path(input_path.stem),
                source_context=load_source_context(input_path),
            )
        ]
        return _filter_source_ids(jobs, selected_source_ids)

    if not input_path.exists() or not input_path.is_dir():
        raise NotADirectoryError(f"Input folder does not exist: {input_path}")

    jobs: list[VideoJob] = []
    seen_inputs: set[Path] = set()
    canonical_parents: set[Path] = set()
    for path in sorted(input_path.rglob(STITCHED_VIDEO_NAME), key=lambda item: str(item).casefold()):
        if is_catalog_internal(path, input_path):
            continue
        jobs.append(
            VideoJob(
                input_video=path,
                relative_output_dir=path.parent.relative_to(input_path),
                source_context=load_source_context(path, boundary=input_path),
            )
        )
        seen_inputs.add(path.resolve())
        canonical_parents.add(path.parent.resolve())

    for path in sorted(input_path.rglob("*.mp4"), key=lambda item: str(item).casefold()):
        if is_catalog_internal(path, input_path):
            continue
        if path.resolve() in seen_inputs:
            continue
        if path.parent.resolve() in canonical_parents:
            continue
        if any(part.casefold() == "raw_clips" for part in path.parts):
            continue
        if is_generated_intermediate(path):
            continue
        relative_path = path.relative_to(input_path)
        jobs.append(
            VideoJob(
                input_video=path,
                relative_output_dir=relative_path.with_suffix(""),
                source_context=load_source_context(path, boundary=input_path),
            )
        )
    return _filter_source_ids(jobs, selected_source_ids)


def _filter_source_ids(
    jobs: list[VideoJob],
    selected_source_ids: Sequence[str] | None,
) -> list[VideoJob]:
    if selected_source_ids is None:
        return jobs
    requested = [str(source_id) for source_id in selected_source_ids]
    if len(set(requested)) != len(requested):
        raise ValueError("Selected audio SourceIDs must be unique")
    available = {
        str(job.source_context.get("source_id") or "")
        for job in jobs
        if job.source_context.get("source_id")
    }
    unknown = sorted(set(requested) - available)
    if unknown:
        raise ValueError(f"Unknown audio SourceID selection: {', '.join(unknown)}")
    selected = set(requested)
    return [job for job in jobs if str(job.source_context.get("source_id") or "") in selected]


def is_generated_intermediate(path: Path) -> bool:
    """Exclude clips that are inputs to a canonical stitched video."""

    name = path.name.casefold()
    return (
        name == "_black_silent_gap.mp4"
        or name.startswith("segment_")
        or name.startswith("focus_segment_")
        or name.startswith("clean_segment_")
        or name.endswith("_normalised.mp4")
    )


def is_catalog_internal(path: Path, input_root: Path) -> bool:
    """Return whether a media path belongs to procurement's private cache."""

    relative = path.relative_to(input_root)
    return any(part.casefold() in CATALOG_INTERNAL_DIRECTORIES for part in relative.parts[:-1])


def validate_source_context_coverage(input_path: Path, jobs: Sequence[VideoJob]) -> None:
    """Require every non-cache catalog context to own exactly one discovered video."""

    if not input_path.is_dir():
        return
    context_paths = {
        path
        for path in input_path.rglob("source_context.json")
        if not is_catalog_internal(path, input_path)
    }
    used_paths: list[Path] = []
    for job in jobs:
        if not job.source_context:
            continue
        context_path = _nearest_source_context_path(job.input_video, input_path)
        if context_path is None:
            raise ValueError(f"Catalog audio input has no source context: {job.input_video}")
        used_paths.append(context_path)
    if len(used_paths) != len(set(used_paths)):
        raise ValueError("One audio source context is shared by multiple discovered videos.")
    orphaned = sorted(context_paths - set(used_paths), key=lambda path: str(path).casefold())
    if orphaned:
        raise ValueError(f"Orphan audio source context has no discovered video: {orphaned[0]}")


def _nearest_source_context_path(video: Path, boundary: Path) -> Path | None:
    directory = video.parent
    while directory == boundary or boundary in directory.parents:
        candidate = directory / "source_context.json"
        try:
            candidate.lstat()
        except FileNotFoundError:
            pass
        else:
            return candidate
        if directory == boundary:
            break
        directory = directory.parent
    return None


def run_batch(
    input_path: Path,
    output_root: Path,
    *,
    window_seconds: float = 10.0,
    stride_seconds: float = 5.0,
    opensmile_feature_set: str = "egemaps",
    continue_on_error: bool = True,
    skip_emotion_models: bool = False,
    device: str = "auto",
    keep_temp_audio: bool = False,
    debug: bool = False,
    selected_source_ids: Sequence[str] | None = None,
    expected_catalog_sha256: str = "",
    progress: ProgressCallback | None = None,
) -> BatchResult:
    """Run OpenSMILE audio analysis over a procurement downloads folder."""

    input_path = assert_no_output_path_aliases(
        input_path, description="Audio input"
    ).resolve(strict=True)
    output_root = assert_safe_output_path(
        output_root,
        protected_sources=(input_path,),
        description="Audio output",
    )
    if input_path.is_dir() and (output_root == input_path or input_path in output_root.parents):
        raise ValueError("Choose an audio output directory outside the input folder.")
    emit_progress(progress, f"Input folder: {input_path}")
    emit_progress(progress, f"Output folder: {output_root}")
    emit_progress(progress, "Scanning for analysis .mp4 files.")
    all_jobs = discover_videos(input_path)
    validate_source_context_coverage(input_path, all_jobs)
    jobs = _filter_source_ids(all_jobs, selected_source_ids)
    if not jobs:
        raise ValueError(f"No analysis .mp4 files found under {input_path}")
    if len(jobs) > MAX_AUDIO_BATCH_FILES:
        raise ValueError(
            f"Audio batch exceeds the {MAX_AUDIO_BATCH_FILES} file limit."
        )
    total_input_bytes = sum(job.input_video.stat().st_size for job in jobs)
    if total_input_bytes > MAX_AUDIO_BATCH_BYTES:
        raise ValueError(
            f"Audio batch exceeds the {MAX_AUDIO_BATCH_BYTES} byte limit."
        )
    emit_progress(progress, f"Found {len(jobs)} video(s) to analyse.")
    long_path_warnings = path_length_warnings(input_path, output_root, jobs)
    for warning in long_path_warnings:
        emit_progress(progress, warning)
    sidecars_copied = copy_run_sidecars(
        input_path,
        output_root,
        expected_source_ids={
            str(job.source_context.get("source_id") or "")
            for job in all_jobs
            if job.source_context.get("source_id")
        },
        source_bindings=[(job.input_video, job.source_context) for job in all_jobs],
        expected_catalog_sha256=expected_catalog_sha256,
    )
    if any(job.source_context for job in all_jobs) and not sidecars_copied:
        raise ValueError("Catalog audio source contexts require an immutable top-level source sidecar pair.")
    output_root.mkdir(parents=True, exist_ok=True)
    emit_progress(progress, "Loading shared emotion model bundle.")
    emotion_models = EmotionModelBundle.load(skip=skip_emotion_models, device=device)
    if getattr(emotion_models, "skipped", False):
        emit_progress(progress, "Emotion models skipped for this batch.")
    else:
        emit_progress(progress, f"Emotion models loaded once for batch on {getattr(emotion_models, 'device', '')}.")
        for error in getattr(emotion_models, "errors", []):
            emit_progress(progress, f"Model warning: {error}")
        unavailable = []
        if not getattr(emotion_models, "categorical_available", False):
            unavailable.append("categorical")
        if not getattr(emotion_models, "dimensional_available", False):
            unavailable.append("dimensional")
        if unavailable:
            details = " | ".join(getattr(emotion_models, "errors", []) or [])
            suffix = f" Details: {details}" if details else ""
            raise RuntimeError(
                f"Emotion analysis was requested, but the {', '.join(unavailable)} model layer(s) are unavailable."
                f"{suffix}"
            )
    debug_fallback_models = None
    if debug and not skip_emotion_models:
        emit_progress(progress, "Debug mode: loading fallback categorical model once for batch.")
        debug_fallback_models = load_debug_fallback_emotion_models(device=device)
        emit_progress(progress, f"Debug fallback model: {model_label(debug_fallback_models, 'categorical')}")
    elif debug:
        emit_progress(progress, "Debug fallback skipped because emotion models are skipped for this batch.")

    manifest_rows: list[dict[str, object]] = []
    log_lines = [
        f"Run started: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Input: {input_path}",
        f"Output: {output_root.resolve()}",
        f"Videos discovered: {len(jobs)}",
        *long_path_warnings,
        f"Categorical model: {model_label(emotion_models, 'categorical')}",
        f"Dimensional model: {model_label(emotion_models, 'dimensional')}",
        f"Model device: {getattr(emotion_models, 'device', '')}",
        f"Emotion models skipped: {getattr(emotion_models, 'skipped', False)}",
        f"Categorical available: {getattr(emotion_models, 'categorical_available', False)}",
        f"Dimensional available: {getattr(emotion_models, 'dimensional_available', False)}",
        f"Model errors: {' | '.join(getattr(emotion_models, 'errors', []) or [])}",
        f"Debug fallback enabled: {debug and debug_fallback_models is not None}",
        f"Debug fallback model: {model_label(debug_fallback_models, 'categorical') if debug_fallback_models is not None else ''}",
        "",
    ]
    processed = 0
    failed = 0

    for index, job in enumerate(jobs, start=1):
        video_output_dir = output_root / job.relative_output_dir
        relative_input = job.input_video.relative_to(input_path) if input_path.is_dir() else job.input_video.name
        emit_progress(progress, f"[{index}/{len(jobs)}] Analysing {relative_input}")
        emit_progress(progress, f"[{index}/{len(jobs)}] Output: {video_output_dir}")
        try:
            result = run_single_video(
                job.input_video,
                video_output_dir,
                window_seconds=window_seconds,
                stride_seconds=stride_seconds,
                opensmile_feature_set=opensmile_feature_set,
                emotion_models=emotion_models,
                keep_temp_audio=keep_temp_audio,
                debug=debug,
                debug_fallback_emotion_models=debug_fallback_models,
                source_context=job.source_context,
                progress=indented_progress(progress),
            )
            processed += 1
            manifest_rows.append(success_row(input_path, job, result, emotion_models))
            log_lines.append(f"OK: {job.input_video}")
            emit_progress(progress, f"[{index}/{len(jobs)}] Finished.")
        except Exception as exc:
            failed += 1
            manifest_rows.append(failure_row(input_path, job, video_output_dir, exc, emotion_models))
            log_lines.append(f"FAILED: {job.input_video} -> {exc}")
            emit_progress(progress, f"[{index}/{len(jobs)}] ERROR: {exc}")
            if not continue_on_error:
                break

    manifest_csv = output_root / "audio_analysis_manifest.csv"
    run_log = output_root / "run_log.txt"
    emit_progress(progress, "Writing batch manifest and run log.")
    write_manifest_csv(manifest_csv, manifest_rows)
    if getattr(config, "Full_Stack_Deployment", False):
        exported_root = export_batch_to_analysis_audio_outputs(
            output_root,
            run_name=batch_run_name(input_path),
            progress=progress,
        )
        log_lines.append(f"Full stack audio outputs: {exported_root}")
    completion_line = f"Batch complete: {processed} processed, {failed} failed."
    log_lines.append(completion_line)
    run_log.write_text("\n".join(log_lines) + "\n", encoding="utf-8-sig")
    emit_progress(progress, completion_line)

    return BatchResult(
        output_root=output_root,
        manifest_csv=manifest_csv,
        run_log=run_log,
        processed_count=processed,
        failed_count=failed,
    )


def indented_progress(progress: ProgressCallback | None) -> ProgressCallback | None:
    if progress is None:
        return None

    def emit(message: str) -> None:
        progress(f"  {message}")

    return emit


def model_label(emotion_models: EmotionModels, model_type: str) -> str:
    if model_type == "categorical":
        name = getattr(emotion_models, "categorical_model_name", "")
        version = getattr(emotion_models, "categorical_model_version", "")
    else:
        name = getattr(emotion_models, "dimensional_model_name", "")
        version = getattr(emotion_models, "dimensional_model_version", "")
    if not name:
        return "skipped"
    availability_attr = "categorical_available" if model_type == "categorical" else "dimensional_available"
    suffix = "" if getattr(emotion_models, availability_attr, False) else " (unavailable)"
    label = f"{name}@{version}" if version else name
    return f"{label}{suffix}"


def success_row(input_root: Path, job: VideoJob, result: SingleVideoResult, emotion_models: EmotionModels) -> dict[str, object]:
    source_metadata = job.source_context.get("user_metadata")
    if not isinstance(source_metadata, dict):
        source_metadata = {}
    return {
        "status": "ok",
        "speaker": str(job.source_context.get("speaker") or "") if job.source_context else first_part(job.relative_output_dir),
        "source_id": str(job.source_context.get("source_id") or ""),
        "source_speaker": str(job.source_context.get("speaker") or ""),
        "source_metadata": json.dumps(source_metadata, ensure_ascii=False, sort_keys=True),
        "video_folder": str(job.relative_output_dir),
        "input_video": str(job.input_video),
        "relative_input_video": str(job.input_video.relative_to(input_root)) if input_root.is_dir() else job.input_video.name,
        "output_folder": str(result.output_dir),
        "audio_analysis_csv": str(result.audio_analysis_csv),
        "opensmile_features_csv": str(result.opensmile_csv),
        "per_video_manifest": str(result.manifest_path),
        "window_count": result.window_count,
        "categorical_model": model_label(emotion_models, "categorical"),
        "dimensional_model": model_label(emotion_models, "dimensional"),
        "error": "",
    }


def failure_row(input_root: Path, job: VideoJob, output_dir: Path, exc: Exception, emotion_models: EmotionModels) -> dict[str, object]:
    source_metadata = job.source_context.get("user_metadata")
    if not isinstance(source_metadata, dict):
        source_metadata = {}
    return {
        "status": "failed",
        "speaker": str(job.source_context.get("speaker") or "") if job.source_context else first_part(job.relative_output_dir),
        "source_id": str(job.source_context.get("source_id") or ""),
        "source_speaker": str(job.source_context.get("speaker") or ""),
        "source_metadata": json.dumps(source_metadata, ensure_ascii=False, sort_keys=True),
        "video_folder": str(job.relative_output_dir),
        "input_video": str(job.input_video),
        "relative_input_video": str(job.input_video.relative_to(input_root)) if input_root.is_dir() else job.input_video.name,
        "output_folder": str(output_dir),
        "audio_analysis_csv": "",
        "opensmile_features_csv": "",
        "per_video_manifest": "",
        "window_count": "",
        "categorical_model": model_label(emotion_models, "categorical"),
        "dimensional_model": model_label(emotion_models, "dimensional"),
        "error": str(exc),
    }


def write_manifest_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    fields = [
        "status",
        "speaker",
        "source_id",
        "source_speaker",
        "source_metadata",
        "video_folder",
        "input_video",
        "relative_input_video",
        "output_folder",
        "audio_analysis_csv",
        "opensmile_features_csv",
        "per_video_manifest",
        "window_count",
        "categorical_model",
        "dimensional_model",
        "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = SpreadsheetSafeWriter(csv.DictWriter(handle, fieldnames=fields))
        writer.writeheader()
        writer.writerows(rows)
    return path


def clean_batch_outputs(output_root: Path) -> None:
    """Remove only top-level control files owned by a previous batch run.

    Per-video outputs are overwritten in place after input/model validation.
    Recursive filename-based deletion is intentionally avoided because users
    may keep archived analyses beneath the selected output root.
    """

    for filename in ("audio_analysis_manifest.csv", "run_log.txt"):
        path = output_root / filename
        if path.exists():
            path.unlink()


def first_part(path: Path) -> str:
    return path.parts[0] if path.parts else ""


def batch_run_name(input_path: Path) -> str:
    if input_path.name.casefold() == "downloads" and input_path.parent.name:
        return input_path.parent.name
    return input_path.stem if input_path.is_file() else input_path.name


def path_length_warnings(input_path: Path, output_root: Path, jobs: list[VideoJob]) -> list[str]:
    warnings: list[str] = []
    threshold = 240
    for job in jobs:
        output_dir = output_root / job.relative_output_dir
        for label, path in (("input", job.input_video), ("output", output_dir)):
            text = str(path)
            if len(text) >= threshold:
                warnings.append(
                    f"WARNING: long Windows {label} path ({len(text)} chars) may need long-path support: {text}"
                )
    return warnings
