from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from procurement.procurement_beta.intervals import Interval
from procurement.procurement_beta.model_integrity import MODEL_REVISIONS, MODEL_SHA256
from procurement.procurement_beta.pipeline import PlannedSegment, ProcurementBetaOptions, SegmentPlan, build_segment_plan
from procurement.procurement_beta.resources import wait_for_resource_headroom
from procurement.procurement_beta.review import write_review_html
from procurement.video_sampling.naming import make_video_output_folder_name
from procurement.video_sampling.full_video_download import make_filename_safe
from procurement.external_tools import credential_free_media_environment, resolve_media_binary
from procurement.input_limits import (
    MAX_CLEAN_SPEAKER_JSON_BYTES,
    MAX_CLEAN_SPEAKER_JSON_ITEMS,
    read_control_json,
)


@dataclass(frozen=True)
class DetectionResult:
    """Intervals and audit information from one detector track."""

    intervals: list[Interval]
    method: str
    artifacts: list[Path]
    warnings: list[str]


@dataclass(frozen=True)
class VideoWorkItem:
    """Normalised video input consumed by the beta runner."""

    speaker: str
    title: str
    source_path: Path
    youtube_url: str
    video_id: str
    duration_seconds: float
    source_id: str = ""
    source_metadata: dict[str, str] = field(default_factory=dict)
    youtube_language: str = ""


@dataclass(frozen=True)
class VideoRunResult:
    """Summary for one processed video."""

    status: str
    input_video: Path
    output_dir: Path
    output_video: Path
    message: str


class Analyzer(Protocol):
    def analyze(self, video_path: Path, output_dir: Path, options: ProcurementBetaOptions) -> DetectionResult:
        ...


Stitcher = Callable[[Path, Path, list[Interval], float], None]
MAX_FINAL_VALIDATION_REPAIR_PASSES = 3
PROCUREMENT_BETA_CACHE_VERSION = 20
FFMPEG_TIMEOUT_SECONDS = 1800


def process_video_file(
    item: VideoWorkItem,
    *,
    run_root: Path,
    options: ProcurementBetaOptions,
    face_analyzer: Analyzer,
    voice_analyzer: Analyzer,
    stitcher: Stitcher,
) -> VideoRunResult:
    """Run face/voice analysis for one local video and write auditable outputs."""

    output_dir = output_directory_for_item(run_root, item)
    cache_context = cache_context_for_analyzers(options=options, voice_analyzer=voice_analyzer)
    cached = find_cached_result(item, run_root=run_root, options=options, cache_context=cache_context)
    if cached is not None:
        return cached
    output_dir.mkdir(parents=True, exist_ok=True)
    wait_for_resource_headroom(
        min_free_percent=options.resource_guard_percent,
        output_path=output_dir,
        poll_seconds=options.resource_poll_seconds,
        timeout_seconds=options.resource_guard_timeout_seconds,
        logger=lambda message: print(message, flush=True),
        stage=f"analysis for {item.speaker}/{item.title}",
    )
    stills_dir = output_dir / "identity_stills"

    # Process one video completely before moving to the next. The safe default
    # runs face and voice sequentially so weaker research laptops do not pin CPU,
    # RAM, and GPU at the same time. Advanced users can opt into parallel streams.
    timings: dict[str, float] = {}
    if options.parallel_detector_streams:
        with ThreadPoolExecutor(max_workers=2) as executor:
            face_future = executor.submit(timed_analyze, "face_analysis", face_analyzer, item.source_path, stills_dir, options)
            voice_future = executor.submit(timed_analyze, "voice_analysis", voice_analyzer, item.source_path, output_dir, options)
            face_label, face, face_seconds = face_future.result()
            voice_label, voice, voice_seconds = voice_future.result()
        timings[face_label] = round(face_seconds, 3)
        timings[voice_label] = round(voice_seconds, 3)
        timings["detector_wall_time"] = round(max(face_seconds, voice_seconds), 3)
    else:
        face_label, face, face_seconds = timed_analyze("face_analysis", face_analyzer, item.source_path, stills_dir, options)
        wait_for_resource_headroom(
            min_free_percent=options.resource_guard_percent,
            output_path=output_dir,
            poll_seconds=options.resource_poll_seconds,
            timeout_seconds=options.resource_guard_timeout_seconds,
            logger=lambda message: print(message, flush=True),
            stage=f"voice analysis for {item.speaker}/{item.title}",
        )
        voice_label, voice, voice_seconds = timed_analyze("voice_analysis", voice_analyzer, item.source_path, output_dir, options)
        timings[face_label] = round(face_seconds, 3)
        timings[voice_label] = round(voice_seconds, 3)
        timings["detector_wall_time"] = round(face_seconds + voice_seconds, 3)

    plan_start = time.perf_counter()
    plan = build_segment_plan(
        face_intervals=face.intervals,
        voice_intervals=voice.intervals,
        video_duration_seconds=item.duration_seconds,
        options=options,
    )
    timings["segment_planning"] = round(time.perf_counter() - plan_start, 3)

    validation_start = time.perf_counter()
    validation = validate_candidate_face_segments(face_analyzer, item.source_path, output_dir, plan, options)
    if validation is not None:
        face = merge_face_validation_result(face, validation)
        plan = build_segment_plan(
            face_intervals=face.intervals,
            voice_intervals=voice.intervals,
            video_duration_seconds=item.duration_seconds,
            options=options,
        )
    timings["face_segment_validation"] = round(time.perf_counter() - validation_start, 3)

    write_detection_outputs(output_dir, "face_visibility_intervals", face)
    write_detection_outputs(output_dir, "voice_activity_intervals", voice)
    write_plan_outputs(output_dir, plan)
    review_path = write_review_html(output_dir, title=item.title, duration_seconds=item.duration_seconds, plan=plan)

    output_video = output_dir / "stitched_imotions.mp4"
    selected = [segment.interval for segment in plan.selected_segments]
    stitched_validation: dict[str, Any] | None = None
    repair_history: list[dict[str, Any]] = []
    repair_rejected_all_segments = False
    clip_files_match_selected = True
    if selected:
        wait_for_resource_headroom(
            min_free_percent=options.resource_guard_percent,
            output_path=output_dir,
            poll_seconds=options.resource_poll_seconds,
            timeout_seconds=options.resource_guard_timeout_seconds,
            logger=lambda message: print(message, flush=True),
            stage=f"stitching for {item.speaker}/{item.title}",
        )
        stitch_start = time.perf_counter()
        stitcher(item.source_path, output_video, selected, options.gap_seconds)
        timings["stitching"] = round(time.perf_counter() - stitch_start, 3)
        if options.skip_final_output_validation:
            stitched_validation = {
                "skipped": True,
                "reason": "Final stitched-output validation was disabled to preserve selected clean segments.",
            }
            timings["stitched_output_validation"] = 0.0
            failure_count = 0
        else:
            validation_start = time.perf_counter()
            stitched_validation = validate_stitched_output(face_analyzer, output_video, output_dir, options)
            stitched_validation = ignore_gap_validation_failures(stitched_validation, selected, gap_seconds=options.gap_seconds)
            timings["stitched_output_validation"] = round(time.perf_counter() - validation_start, 3)
            failure_count = validation_failure_count(stitched_validation)
        if failure_count:
            repair_history.append(repair_history_entry(0, selected, stitched_validation))

        repair_round = 0
        while failure_count and repair_round < MAX_FINAL_VALIDATION_REPAIR_PASSES:
            previous_selected = selected
            repaired_selected = remove_failed_stitched_segments(selected, stitched_validation, gap_seconds=options.gap_seconds)
            if not repaired_selected:
                repair_rejected_all_segments = True
                selected = []
                plan = plan_with_selected_intervals(plan, selected)
                write_plan_outputs(output_dir, plan)
                review_path = write_review_html(output_dir, title=item.title, duration_seconds=item.duration_seconds, plan=plan)
                break
            if len(repaired_selected) == len(selected):
                break

            repair_round += 1
            removed_count = len(selected) - len(repaired_selected)
            print(
                f"Final validation: removing {removed_count} suspect segment(s) and stitching again "
                f"(repair {repair_round}/{MAX_FINAL_VALIDATION_REPAIR_PASSES}).",
                flush=True,
            )
            selected = repaired_selected
            plan = plan_with_selected_intervals(plan, selected)
            write_plan_outputs(output_dir, plan)
            review_path = write_review_html(output_dir, title=item.title, duration_seconds=item.duration_seconds, plan=plan)

            repair_start = time.perf_counter()
            reused_clips = False
            if clip_files_match_selected and stitcher is stitch_with_ffmpeg:
                reused_clips = restitch_from_existing_clips(
                    item.source_path,
                    output_video,
                    previous_selected,
                    selected,
                    options.gap_seconds,
                )
            if not reused_clips:
                stitcher(item.source_path, output_video, selected, options.gap_seconds)
            clip_files_match_selected = not reused_clips
            timings[f"stitching_repair_{repair_round}"] = round(time.perf_counter() - repair_start, 3)
            validation_start = time.perf_counter()
            stitched_validation = validate_stitched_output(face_analyzer, output_video, output_dir, options)
            stitched_validation = ignore_gap_validation_failures(stitched_validation, selected, gap_seconds=options.gap_seconds)
            timings[f"stitched_output_repair_validation_{repair_round}"] = round(time.perf_counter() - validation_start, 3)
            failure_count = validation_failure_count(stitched_validation)
            if failure_count:
                repair_history.append(repair_history_entry(repair_round, selected, stitched_validation))

        if repair_rejected_all_segments:
            status = "no_clean_segments"
            message = "Final validation rejected every selected segment."
        elif failure_count:
            status = "needs_review"
            message = f"{len(selected)} segments stitched, but final face validation found {failure_count} suspect sampled frames."
        else:
            status = "ok"
            message = f"{len(selected)} clean segments stitched."
    else:
        timings["stitching"] = 0.0
        status = "no_clean_segments"
        message = "No overlapping face and voice segments met the minimum duration."

    write_run_manifest(
        output_dir,
        item,
        options,
        face,
        voice,
        plan,
        output_video,
        status,
        message,
        timings=timings,
        review_path=review_path,
        stitched_validation=stitched_validation,
        repair_history=repair_history,
        cache_context=cache_context,
    )
    if status == "ok" and not options.keep_debug:
        cleanup_stitch_intermediates(output_dir)
    return VideoRunResult(status=status, input_video=item.source_path, output_dir=output_dir, output_video=output_video, message=message)



def repair_history_entry(
    repair_round: int,
    selected: list[Interval],
    validation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep failed final-QA evidence after a later repair overwrites the artifact."""

    payload = validation or {}
    return {
        "repair_round": int(repair_round),
        "selected_count": len(selected),
        "failure_count": validation_failure_count(payload),
        "failures": validation_failure_records(payload)[:100],
        "ignored_failures": list(payload.get("ignored_failures") or [])[:100],
    }

def remove_failed_stitched_segments(
    segments: list[Interval],
    validation: dict[str, Any] | None,
    *,
    gap_seconds: float,
) -> list[Interval]:
    """Drop source segments that produced suspect frames in the final stitched output."""

    failed_indices: set[int] = set()
    for failure in validation_failure_records(validation):
        try:
            timestamp = float(failure.get("timestamp"))
        except (AttributeError, TypeError, ValueError):
            continue
        index = stitched_segment_index_for_timestamp(segments, timestamp, gap_seconds=gap_seconds)
        if index is not None:
            failed_indices.add(index)

    if not failed_indices:
        return segments
    return [segment for index, segment in enumerate(segments) if index not in failed_indices]


def stitched_segment_index_for_timestamp(segments: list[Interval], timestamp: float, *, gap_seconds: float) -> int | None:
    """Map a stitched-output timestamp back to the selected source segment index."""

    cursor = 0.0
    for index, segment in enumerate(segments):
        duration = trim_segment_for_stitching(segment).duration
        if cursor <= timestamp < cursor + duration:
            return index
        cursor += duration
        if index < len(segments) - 1:
            if cursor <= timestamp < cursor + max(0.0, gap_seconds):
                return None
            cursor += max(0.0, gap_seconds)
    return None


def plan_with_selected_intervals(plan: SegmentPlan, selected: list[Interval]) -> SegmentPlan:
    """Return a plan whose selected list matches final-validation pruning."""

    selected_keys = {interval_key(segment) for segment in selected}
    kept: list[PlannedSegment] = []
    removed: list[PlannedSegment] = []
    for segment in plan.selected_segments:
        if interval_key(segment.interval) in selected_keys:
            kept.append(segment)
        else:
            removed.append(PlannedSegment(segment.interval, "removed_by_final_output_validation"))
    return SegmentPlan(
        overlap_segments=plan.overlap_segments,
        clean_segments=plan.clean_segments,
        rejected_segments=[*plan.rejected_segments, *removed],
        selected_segments=kept,
    )


def interval_key(interval: Interval) -> tuple[float, float]:
    return (round(float(interval.start), 6), round(float(interval.end), 6))



def validation_failure_records(validation: dict[str, Any] | None) -> list[dict[str, object]]:
    """Return all final-QA failure records, including compact timestamp-only overflow."""

    payload = validation or {}
    records: list[dict[str, object]] = []
    seen: set[float] = set()
    for failure in payload.get("failures") or []:
        record = dict(failure)
        timestamp = failure_timestamp(record)
        if timestamp is not None:
            seen.add(round(timestamp, 6))
        records.append(record)
    for timestamp in payload.get("failure_timestamps") or []:
        try:
            rounded = round(float(timestamp), 6)
        except (TypeError, ValueError):
            continue
        if rounded not in seen:
            records.append({"timestamp": float(timestamp)})
            seen.add(rounded)
    return records

def validation_failure_count(validation: dict[str, Any] | None) -> int:
    """Return final QA failures after any intentional gap samples are ignored."""

    return int((validation or {}).get("failure_count") or 0)


def ignore_gap_validation_failures(
    validation: dict[str, Any] | None,
    segments: list[Interval],
    *,
    gap_seconds: float,
) -> dict[str, Any] | None:
    """Ignore final-QA samples that landed inside inserted black/silent gaps."""

    if not validation or gap_seconds <= 0.0:
        return validation
    failures = validation_failure_records(validation)
    if not failures:
        return validation

    kept: list[dict[str, object]] = []
    ignored: list[dict[str, object]] = []
    for failure in validation_failure_records(validation):
        timestamp = failure_timestamp(failure)
        if timestamp is not None and timestamp_is_inserted_gap(segments, timestamp, gap_seconds=gap_seconds):
            ignored_failure = dict(failure)
            ignored_failure["ignored_reason"] = "timestamp fell inside an inserted black/silent gap"
            ignored.append(ignored_failure)
        else:
            kept.append(failure)

    if not ignored:
        return validation

    updated = dict(validation)
    updated["failures"] = kept
    updated["failure_count"] = len(kept)
    updated["failure_timestamps"] = [failure_timestamp(item) for item in kept if failure_timestamp(item) is not None]
    updated["ignored_failures"] = [*(updated.get("ignored_failures") or []), *ignored]
    persist_stitched_validation_payload(updated)
    return updated


def failure_timestamp(failure: object) -> float | None:
    """Read a validation timestamp without letting malformed records crash repair."""

    try:
        return float(failure.get("timestamp"))  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        return None


def timestamp_is_inserted_gap(segments: list[Interval], timestamp: float, *, gap_seconds: float) -> bool:
    """Return true when a stitched timestamp falls inside an inserted gap."""

    cursor = 0.0
    for index, segment in enumerate(segments):
        cursor += trim_segment_for_stitching(segment).duration
        if index >= len(segments) - 1:
            continue
        gap = max(0.0, gap_seconds)
        if cursor <= timestamp < cursor + gap:
            return True
        cursor += gap
    return False


def persist_stitched_validation_payload(payload: dict[str, Any]) -> None:
    """Keep the JSON validation artifact aligned with gap-filtered results."""

    artifact = payload.get("artifact")
    if not artifact:
        return
    Path(str(artifact)).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
def validate_stitched_output(
    face_analyzer: Analyzer,
    output_video: Path,
    output_dir: Path,
    options: ProcurementBetaOptions,
) -> dict[str, Any] | None:
    """Run optional final face QA over the stitched video before calling it clean."""

    validator = getattr(face_analyzer, "validate_stitched_output", None)
    if not callable(validator):
        return None
    try:
        return validator(output_video, output_dir, options)
    except Exception as exc:
        return {"available": False, "failure_count": 1, "failures": [{"reason": f"stitched validation failed: {exc}"}]}


def validate_candidate_face_segments(
    face_analyzer: Analyzer,
    video_path: Path,
    output_dir: Path,
    plan: SegmentPlan,
    options: ProcurementBetaOptions,
) -> DetectionResult | None:
    """Ask capable face analyzers to refine clean candidates before stitching."""

    validator = getattr(face_analyzer, "validate_segments", None)
    if not callable(validator):
        return None

    candidate_intervals = [segment.interval for segment in plan.clean_segments]
    if not candidate_intervals:
        return None
    return validator(video_path, output_dir, candidate_intervals, options)


def merge_face_validation_result(face: DetectionResult, validation: DetectionResult) -> DetectionResult:
    """Keep first-pass artifacts while replacing intervals with validated ones."""

    return DetectionResult(
        intervals=validation.intervals,
        method=f"{face.method}+{validation.method}",
        artifacts=[*face.artifacts, *validation.artifacts],
        warnings=[*face.warnings, *validation.warnings],
    )


def timed_analyze(
    label: str,
    analyzer: Analyzer,
    video_path: Path,
    output_dir: Path,
    options: ProcurementBetaOptions,
) -> tuple[str, DetectionResult, float]:
    """Run one analyzer and return elapsed seconds for manifest profiling."""

    started = time.perf_counter()
    result = analyzer.analyze(video_path, output_dir, options)
    return label, result, time.perf_counter() - started


def find_cached_result(
    item: VideoWorkItem,
    *,
    run_root: Path,
    options: ProcurementBetaOptions,
    cache_context: dict[str, object] | None = None,
) -> VideoRunResult | None:
    """Return a cached result when the existing manifest matches this input/options."""

    output_dir = output_directory_for_item(run_root, item)
    manifest_path = output_dir / "clean_speaker_beta_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = read_control_json(
            manifest_path,
            label="clean speaker manifest",
            max_bytes=MAX_CLEAN_SPEAKER_JSON_BYTES,
            max_items=MAX_CLEAN_SPEAKER_JSON_ITEMS,
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    if manifest.get("pipeline_version") != PROCUREMENT_BETA_CACHE_VERSION:
        return None
    if manifest.get("options") != asdict(options):
        return None
    if manifest.get("cache_context", {}) != (cache_context or {}):
        return None
    if str(manifest.get("status") or "") != "ok":
        return None
    source = manifest.get("input", {}).get("source_path")
    if source and str(Path(source)) != str(item.source_path):
        return None
    if manifest.get("input", {}).get("source_identity") != file_cache_identity(item.source_path):
        return None
    output_video = Path(str(manifest.get("output_video") or output_dir / "stitched_imotions.mp4"))
    if not video_file_is_usable(output_video):
        return None
    return VideoRunResult(
        status="cached",
        input_video=item.source_path,
        output_dir=output_dir,
        output_video=output_video,
        message=str(manifest.get("message") or "Reused cached clean speaker beta output."),
    )


def cache_context_for_analyzers(
    *,
    options: ProcurementBetaOptions,
    voice_analyzer: Analyzer,
) -> dict[str, object]:
    """Return cache-affecting analyzer state that is not part of user options."""

    reference_audio = getattr(voice_analyzer, "reference_audio", None)
    reference_identity = file_cache_identity(reference_audio)
    context: dict[str, object] = {}
    if reference_identity:
        context["reference_audio"] = reference_identity
    face_reference_dir = str(options.face_reference_dir or "").strip()
    if face_reference_dir:
        context["reference_face"] = file_cache_identity(Path(face_reference_dir) / "reference_embedding.json")
    return context


def file_cache_identity(path: object) -> dict[str, object]:
    """Identify a local file well enough to avoid stale cached model output."""

    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    payload: dict[str, object] = {"path": str(resolved)}
    try:
        stat = resolved.stat()
    except OSError:
        payload["exists"] = False
        return payload
    payload.update({"exists": True, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return payload


def output_directory_for_item(run_root: Path, item: VideoWorkItem) -> Path:
    root = run_root.expanduser().resolve()
    parent = root / safe_name(item.speaker) if item.speaker else root
    identifier = item.source_id or item.video_id
    if not identifier:
        path_hash = hashlib.sha256(str(item.source_path.expanduser().resolve()).encode("utf-8")).hexdigest()[:10]
        identifier = f"{item.source_path.stem}-{path_hash}"
    folder_name = make_video_output_folder_name(item.title or item.source_path.stem, identifier)
    candidate = (parent / folder_name).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("Clean speaker output mapping escapes the selected run root.")
    return candidate


def write_detection_outputs(output_dir: Path, stem: str, result: DetectionResult) -> None:
    payload = {
        "method": result.method,
        "warnings": result.warnings,
        "artifacts": [str(path) for path in result.artifacts],
        "intervals": [interval_to_dict(item) for item in result.intervals],
    }
    (output_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_interval_csv(output_dir / f"{stem}.csv", result.intervals)


def write_plan_outputs(output_dir: Path, plan: SegmentPlan) -> None:
    (output_dir / "clean_overlap_segments.json").write_text(json.dumps(plan.to_dict(), indent=2) + "\n", encoding="utf-8")
    write_interval_csv(output_dir / "clean_overlap_segments.csv", [segment.interval for segment in plan.clean_segments])
    selected_payload = {
        "selected_segments": [segment.to_dict() for segment in plan.selected_segments],
        "rejected_segments": [segment.to_dict() for segment in plan.rejected_segments],
    }
    (output_dir / "selected_segments.json").write_text(json.dumps(selected_payload, indent=2) + "\n", encoding="utf-8")


def write_run_manifest(
    output_dir: Path,
    item: VideoWorkItem,
    options: ProcurementBetaOptions,
    face: DetectionResult,
    voice: DetectionResult,
    plan: SegmentPlan,
    output_video: Path,
    status: str,
    message: str,
    timings: dict[str, float] | None = None,
    review_path: Path | None = None,
    stitched_validation: dict[str, Any] | None = None,
    repair_history: list[dict[str, Any]] | None = None,
    cache_context: dict[str, object] | None = None,
) -> None:
    manifest = {
        "pipeline_version": PROCUREMENT_BETA_CACHE_VERSION,
        "status": status,
        "message": message,
        "input": {
            "source_id": item.source_id,
            "speaker": item.speaker,
            "title": item.title,
            "source_path": str(item.source_path),
            "source_identity": file_cache_identity(item.source_path),
            "youtube_url": item.youtube_url,
            "video_id": item.video_id,
            "duration_seconds": item.duration_seconds,
            "source_metadata": item.source_metadata,
            "youtube_language": item.youtube_language,
        },
        "options": asdict(options),
        "model_revisions": dict(MODEL_REVISIONS),
        "model_sha256": dict(MODEL_SHA256),
        "cache_context": cache_context or {},
        "face_method": face.method,
        "voice_method": voice.method,
        "face_warnings": face.warnings,
        "voice_warnings": voice.warnings,
        "output_video": str(output_video),
        "review_html": str(review_path) if review_path else "",
        "timings_seconds": timings or {},
        "stitched_output_validation": stitched_validation or {},
        "stitched_output_repair_history": repair_history or [],
        "segment_plan": plan.to_dict(),
    }
    (output_dir / "clean_speaker_beta_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def write_interval_csv(path: Path, intervals: list[Interval]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["start", "end", "duration", "confidence"])
        writer.writeheader()
        for interval in intervals:
            writer.writerow(interval_to_dict(interval))


def interval_to_dict(interval: Interval) -> dict[str, float]:
    return {
        "start": interval.start,
        "end": interval.end,
        "duration": interval.duration,
        "confidence": interval.confidence,
    }


def stitch_with_ffmpeg(source_video: Path, target_path: Path, segments: list[Interval], gap_seconds: float) -> None:
    """Cut selected segments and stitch them, inserting black/silent gaps if requested."""

    target_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = resolve_media_binary(
        "ffmpeg",
        excluded_roots=(source_video.parent, target_path.parent),
    )
    clip_files: list[Path] = []
    print(f"Stitch: cutting {len(segments)} selected clean segments.", flush=True)
    for index, segment in enumerate(segments, start=1):
        clip = target_path.parent / f"clean_segment_{index:03d}.mp4"
        print(
            f"Stitch: cutting segment {index}/{len(segments)} at {segment.start:.2f}s for {segment.duration:.2f}s.",
            flush=True,
        )
        run_command(segment_cut_command(source_video, clip, segment, ffmpeg_binary=ffmpeg))
        clip_files.append(clip)

    concat_inputs = add_gap_clips(target_path.parent, source_video, clip_files, gap_seconds)
    if len(concat_inputs) == 1:
        shutil.copy2(concat_inputs[0], target_path)
        return

    print(f"Stitch: concatenating {len(concat_inputs)} clips into {target_path}.", flush=True)
    concat_list = target_path.parent / "_concat_clean_speaker_segments.txt"
    concat_list.write_text("".join(concat_file_line(item) for item in concat_inputs), encoding="utf-8")
    run_command([str(ffmpeg), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(target_path)])


def restitch_from_existing_clips(
    source_video: Path,
    target_path: Path,
    previous_segments: list[Interval],
    repaired_segments: list[Interval],
    gap_seconds: float,
) -> bool:
    """Rebuild a repaired stitch from already-cut clips when interval mapping is exact."""

    target_dir = target_path.parent
    clip_by_interval: dict[tuple[float, float], Path] = {}
    for index, segment in enumerate(previous_segments, start=1):
        clip = target_dir / f"clean_segment_{index:03d}.mp4"
        if not clip.exists() or clip.stat().st_size <= 0:
            return False
        clip_by_interval[interval_key(segment)] = clip

    clip_files: list[Path] = []
    for segment in repaired_segments:
        clip = clip_by_interval.get(interval_key(segment))
        if clip is None:
            return False
        clip_files.append(clip)
    if not clip_files:
        return False

    print(f"Stitch repair: reusing {len(clip_files)} existing clean segment clips.", flush=True)
    concat_inputs = add_gap_clips(target_dir, source_video, clip_files, gap_seconds)
    if len(concat_inputs) == 1:
        shutil.copy2(concat_inputs[0], target_path)
        return True

    concat_list = target_dir / "_concat_clean_speaker_segments.txt"
    concat_list.write_text("".join(concat_file_line(item) for item in concat_inputs), encoding="utf-8")
    ffmpeg = resolve_media_binary(
        "ffmpeg",
        excluded_roots=(source_video.parent, target_path.parent),
    )
    run_command([str(ffmpeg), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(target_path)])
    return True

def cleanup_stitch_intermediates(output_dir: Path) -> None:
    """Remove temporary segment clips after the final audited output is written."""

    for pattern in ("clean_segment_*.mp4", "_black_silent_gap.mp4", "_concat_clean_speaker_segments.txt"):
        for path in output_dir.glob(pattern):
            try:
                path.unlink()
            except OSError:
                pass


def segment_cut_command(
    source_video: Path,
    clip: Path,
    segment: Interval,
    *,
    ffmpeg_binary: Path | None = None,
) -> list[str]:
    """Build a fast, accurate ffmpeg cut command for one selected segment."""

    pre_roll_seconds = min(3.0, max(0.0, segment.start))
    coarse_start = max(0.0, segment.start - pre_roll_seconds)
    fine_seek = segment.start - coarse_start
    ffmpeg = ffmpeg_binary or resolve_media_binary(
        "ffmpeg",
        excluded_roots=(source_video.parent, clip.parent),
    )
    return [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{coarse_start:.3f}",
        "-i",
        str(source_video),
        "-ss",
        f"{fine_seek:.3f}",
        "-t",
        f"{segment.duration:.3f}",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        str(clip),
    ]



def trim_segment_for_stitching(segment: Interval) -> Interval:
    """Return the audited interval unchanged.

    Earlier versions silently removed 0.25 seconds from each edge of longer
    clips while persisting the original timestamps. Exact source/output
    mapping is more important than that undocumented trim.
    """

    return segment


def video_file_is_usable(path: Path) -> bool:
    """Require a non-empty, decodable video before accepting cached output."""

    try:
        if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            return False
        result = subprocess.run(
            [
                str(resolve_media_binary("ffprobe", excluded_roots=(path.parent,))),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=index",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
            env=credential_free_media_environment(),
        )
        payload = json.loads(result.stdout)
        duration = float((payload.get("format") or {}).get("duration") or 0)
        return bool(payload.get("streams")) and duration > 0
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
        return False

def add_gap_clips(target_dir: Path, source_video: Path, clip_files: list[Path], gap_seconds: float) -> list[Path]:
    if gap_seconds <= 0 or len(clip_files) < 2:
        return clip_files

    profile = ffprobe_video_profile(source_video)
    gap_file = target_dir / "_black_silent_gap.mp4"
    run_command(
        [
            str(resolve_media_binary(
                "ffmpeg",
                excluded_roots=(source_video.parent, target_dir),
            )),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={profile['width']}x{profile['height']}:r={profile['fps']}:d={gap_seconds:.3f}",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=stereo:sample_rate={profile['sample_rate']}",
            "-t",
            f"{gap_seconds:.3f}",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(gap_file),
        ]
    )
    with_gaps: list[Path] = []
    for index, clip in enumerate(clip_files):
        if index:
            with_gaps.append(gap_file)
        with_gaps.append(clip)
    return with_gaps


def ffprobe_video_profile(source_video: Path) -> dict[str, object]:
    default = {"width": 1280, "height": 720, "fps": 25, "sample_rate": 44100}
    try:
        video = subprocess.run(
            [
                str(resolve_media_binary("ffprobe", excluded_roots=(source_video.parent,))),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate",
                "-of",
                "json",
                str(source_video),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
            env=credential_free_media_environment(),
        )
        data = json.loads(video.stdout)
        stream = (data.get("streams") or [{}])[0]
        width = int(stream.get("width") or default["width"])
        height = int(stream.get("height") or default["height"])
        fps = parse_fps(str(stream.get("r_frame_rate") or default["fps"]))
        return {"width": width, "height": height, "fps": fps, "sample_rate": default["sample_rate"]}
    except Exception:
        return default


def parse_fps(value: str) -> float:
    if "/" not in value:
        return max(1.0, float(value))
    numerator, denominator = value.split("/", 1)
    bottom = float(denominator or 1)
    if bottom == 0:
        return 25.0
    return max(1.0, float(numerator) / bottom)


def run_command(command: list[str]) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=FFMPEG_TIMEOUT_SECONDS,
        env=credential_free_media_environment(),
    )
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, flush=True)
        result.check_returncode()


def concat_file_line(path: Path) -> str:
    """Return one ffmpeg concat-list line using an absolute escaped path."""

    escaped = str(path.resolve()).replace("\\", "/").replace("'", "'\\''")
    return f"file '{escaped}'\n"


def safe_name(value: str) -> str:
    without_controls = "".join("_" if ord(char) < 32 else char for char in str(value or ""))
    cleaned = make_filename_safe(without_controls, max_length=80)
    stem = cleaned.split(".", 1)[0].casefold()
    if stem in {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }:
        cleaned = f"_{cleaned}"
    return cleaned

