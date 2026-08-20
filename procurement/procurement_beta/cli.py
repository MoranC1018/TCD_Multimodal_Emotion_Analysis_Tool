from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import queue
import random
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from procurement.procurement_beta.resources import (
    avoid_logical_cpus,
    configure_low_impact_native_threads,
    limit_current_process_affinity,
    lower_current_process_priority,
    wait_for_busy_thresholds,
    wait_for_resource_headroom,
)

# The launcher sets this before Python imports detector libraries. Direct CLI
# runs keep their existing environment until parsed arguments are available.
_early_native_threads = str(os.getenv("MEA_NATIVE_THREADS") or "").strip()
if _early_native_threads:
    try:
        configure_low_impact_native_threads(thread_count=max(1, int(_early_native_threads)))
    except ValueError:
        pass

from procurement.procurement_beta.detectors import FaceVisibilityAnalyzer, MainVoiceAnalyzer
from procurement.procurement_beta.pipeline import ProcurementBetaOptions
from procurement.procurement_beta.runner import (
    PROCUREMENT_BETA_CACHE_VERSION,
    VideoRunResult,
    VideoWorkItem,
    file_cache_identity,
    output_directory_for_item,
    process_video_file,
    stitch_with_ffmpeg,
    video_file_is_usable,
)
from application import backend
from procurement.video_sampling import run_docx_extractions
from procurement.external_tools import build_yt_dlp_command, credential_free_media_environment, resolve_media_binary
from procurement.input_limits import (
    MAX_CLEAN_SPEAKER_JSON_BYTES,
    MAX_CLEAN_SPEAKER_JSON_ITEMS,
    read_control_json,
)


DOWNLOAD_CACHE_LOCK = threading.Lock()
YOUTUBE_DOWNLOAD_TIMEOUT_SECONDS = 3600
ISOLATED_CHILD_TIMEOUT_SECONDS = 12 * 60 * 60
MAX_CATALOG_CONTEXT_BYTES = 256 * 1024 * 1024
MAX_CATALOG_CONTEXT_ITEMS = 50_000
SOURCE_ID_PATTERN = re.compile(r"source-\d{4,6}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Experimental clean speaker segment procurement.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--source-context",
        type=Path,
        default=None,
        help="Immutable source_context.json supplied by the catalog coordinator.",
    )
    parser.add_argument(
        "--source-id",
        action="append",
        default=[],
        help="Catalog SourceID to process. May be repeated.",
    )
    parser.add_argument("--output-mode", choices=["clean", "percentage"], default="clean")
    parser.add_argument("--percentage", type=float, default=0.10)
    parser.add_argument("--min-clean-seconds", type=float, default=10.0)
    parser.add_argument("--max-segment-seconds", type=float, default=30.0)
    parser.add_argument("--gap-seconds", type=float, default=0.5)
    parser.add_argument("--identity-stills", type=int, default=20)
    parser.add_argument("--scan-fps", type=float, default=1.0)
    parser.add_argument(
        "--validation-fps",
        type=float,
        default=4.0,
        help="Second-pass FPS used only on candidate clean segments before stitching.",
    )
    parser.add_argument("--face-confidence", type=float, default=0.65)
    parser.add_argument("--speaker-confidence", type=float, default=0.65)
    parser.add_argument("--workers", type=int, default=1, help="Number of videos to process concurrently. Keep at 1 on weaker machines.")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--keep-debug", action="store_true")
    parser.add_argument("--resource-guard-percent", type=float, default=15.0, help="Wait when RAM/disk/GPU free headroom drops below this percentage or CPU free headroom drops below it. Use 0 to disable.")
    parser.add_argument("--resource-poll-seconds", type=float, default=15.0, help="Seconds between resource-guard checks while waiting.")
    parser.add_argument("--resource-guard-timeout-seconds", type=float, default=900.0, help="Maximum seconds to wait for resource headroom before failing clearly. Use 0 to wait indefinitely.")
    parser.add_argument("--isolated-video-processes", action="store_true", help="Run each selected video in a fresh child Python process for safer long batches.")
    parser.add_argument("--skip-first-videos", type=int, default=0, help="Resume helper: skip this many selected videos before running.")
    parser.add_argument("--skip-completed-outputs", action="store_true", help="Resume helper: skip videos with an existing clean beta manifest in the stable cache.")
    parser.add_argument("--video-cooldown-seconds", type=float, default=60.0, help="Seconds to rest between isolated video jobs.")
    parser.add_argument("--max-affinity-cores", type=int, default=2, help="Windows-only process affinity cap. Use 0 to leave affinity unchanged.")
    parser.add_argument("--native-threads", type=int, default=1, help="Thread cap for native math libraries used by detector dependencies.")
    parser.add_argument("--cpu-throttle-high-percent", type=float, default=95.0, help="Pause before the next video when CPU busy reaches this percentage.")
    parser.add_argument("--cpu-throttle-low-percent", type=float, default=90.0, help="Resume after CPU busy cools to this percentage.")
    parser.add_argument("--ram-throttle-high-percent", type=float, default=95.0, help="Pause before the next video when RAM busy reaches this percentage.")
    parser.add_argument("--ram-throttle-low-percent", type=float, default=90.0, help="Resume after RAM busy cools to this percentage.")
    parser.add_argument("--parallel-detectors", action="store_true", help="Run face and voice analysis at the same time. Faster, but heavier on the machine.")
    parser.add_argument("--run-final-output-validation", action="store_true", help="Run the final stitched-output QA repair pass. Disabled by default because it can prune valid selected segments.")
    parser.add_argument("--avoid-logical-cpu", type=int, action="append", default=[], help="Exclude a Windows logical CPU index from the long-running process. May be repeated.")
    parser.add_argument("--only-video-id", action="append", default=[], help="Process only this YouTube video id from a DOCX scan. May be repeated.")
    parser.add_argument("--speaker", action="append", default=[], help="Process only this scanned speaker group. May be repeated.")
    parser.add_argument("--random-one", action="store_true", help="After any filters, process one randomly selected video from the source.")
    parser.add_argument("--random-seed", default="", help="Optional seed for reproducible --random-one validation runs.")
    parser.add_argument("--reference-audio", type=Path, default=None)
    parser.add_argument("--reference-face-dir", type=Path, default=None, help="Folder containing a curated reference_embedding.json for the target face.")
    parser.add_argument("--max-download-height", type=int, default=720, help="Maximum YouTube video height to download. Use 0 for best available quality.")
    parser.add_argument("--single-video-json", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--child-result-json", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--child-run-root", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--child-index", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--child-total", type=int, default=1, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def options_from_args(args: argparse.Namespace) -> ProcurementBetaOptions:
    return ProcurementBetaOptions(
        output_mode=args.output_mode,
        percentage=max(0.0, float(args.percentage)),
        min_clean_seconds=max(0.0, float(args.min_clean_seconds)),
        max_segment_seconds=max(0.1, float(args.max_segment_seconds)),
        gap_seconds=max(0.0, float(args.gap_seconds)),
        identity_stills=max(0, int(args.identity_stills)),
        scan_fps=max(0.1, float(args.scan_fps)),
        face_confidence=max(0.0, min(1.0, float(args.face_confidence))),
        speaker_confidence=max(0.0, min(1.0, float(args.speaker_confidence))),
        worker_count=max(1, int(args.workers)),
        device=str(args.device),
        keep_debug=bool(args.keep_debug),
        validation_fps=max(0.1, float(args.validation_fps)),
        resource_guard_percent=max(0.0, min(95.0, float(args.resource_guard_percent))),
        resource_poll_seconds=max(1.0, float(args.resource_poll_seconds)),
        resource_guard_timeout_seconds=max(0.0, float(args.resource_guard_timeout_seconds)),
        parallel_detector_streams=bool(args.parallel_detectors),
        skip_final_output_validation=not bool(args.run_final_output_validation),
        face_reference_dir=str(args.reference_face_dir or ""),
    )


def summary_options_from_args(args: argparse.Namespace) -> dict[str, object]:
    """Return CLI options in a JSON-safe form for run manifests."""

    payload: dict[str, object] = {}
    for key, value in vars(args).items():
        payload[key] = str(value) if isinstance(value, Path) else value
    return payload


def format_result_line(result: VideoRunResult) -> str:
    """Return an honest one-line status message for a processed video."""

    if result.status == "ok":
        return f"Clean speaker beta output: {result.output_video}"
    if result.status == "cached":
        return f"Clean speaker beta cached: {result.output_video}"
    if result.status == "needs_review":
        return f"Clean speaker beta needs review: {result.message}"
    if result.status == "cached_needs_review":
        return f"Clean speaker beta cached needs review: {result.message}"
    if result.status == "cached_no_clean_segments":
        return f"Clean speaker beta cached skip: {result.message}"
    return f"Clean speaker beta skipped: {result.message}"


def cache_root_from_output_root(output_root: Path) -> Path:
    """Use a stable cache folder so repeated runs can reuse per-video outputs."""

    return output_root / "_clean_speaker_beta_cache"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    options = options_from_args(args)
    apply_runtime_limits(args)
    if args.single_video_json is not None:
        return run_single_video_child(args)
    output_root = args.output_root.expanduser().resolve()
    if args.source_context is not None and args.source_context.expanduser().resolve().parent != output_root:
        raise ValueError("Catalog source context must be stored at the selected output root.")
    ensure_output_outside_source(args.source, output_root)
    run_root = output_root / f"clean_speaker_beta_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    cache_root = cache_root_from_output_root(output_root)
    run_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)

    if args.source_context is not None:
        catalog_video = catalog_video_from_context(
            args.source,
            args.source_context,
            selected_source_ids=args.source_id,
        )
        source, videos = str(args.source), [catalog_video]
    else:
        source, videos = videos_from_source_input(
            args.source,
            logger=lambda message: print(f"Scan: {message}", flush=True),
        )
    scanned_count = len(videos)
    videos = deduplicate_videos(
        select_videos(
            videos,
            only_video_ids=args.only_video_id,
            selected_speakers=args.speaker,
            selected_source_ids=args.source_id,
        )
    )
    ensure_unique_output_destinations(videos, cache_root)
    if args.random_one:
        videos = choose_random_video(videos, seed=args.random_seed)
    print(f"Source: {source}", flush=True)
    print(f"Output folder: {run_root}", flush=True)
    print(f"Clean speaker beta scan found {scanned_count} videos; selected {len(videos)} for this run.", flush=True)
    if not videos:
        print("Clean speaker beta has no videos to process after filters.", flush=True)
        return 1

    all_indexed_videos = list(enumerate(videos, start=1))
    indexed_videos = apply_resume_filters(all_indexed_videos, args=args)
    if not indexed_videos:
        print("Clean speaker beta has no videos to process after resume filters.", flush=True)
        return 0
    if args.isolated_video_processes:
        return run_isolated_parent(
            args=args,
            options=options,
            source=source,
            scanned_count=scanned_count,
            indexed_videos=indexed_videos,
            total_videos=len(all_indexed_videos),
            output_root=output_root,
            run_root=run_root,
            cache_root=cache_root,
        )

    results: list[VideoRunResult] = []
    failures = 0

    worker_count = max(1, min(options.worker_count, len(indexed_videos)))
    print(f"Clean speaker beta concurrent video workers: {worker_count}", flush=True)

    if worker_count == 1:
        completed_runs = [
            process_selected_video(index, len(indexed_videos), args, options, video, output_root, cache_root)
            for index, (_, video) in enumerate(indexed_videos, start=1)
        ]
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(process_selected_video, index, len(indexed_videos), args, options, video, output_root, cache_root)
                for index, (_, video) in enumerate(indexed_videos, start=1)
            ]
            completed_runs = [future.result() for future in as_completed(futures)]

    for processed_count, (index, result, error) in enumerate(sorted(completed_runs, key=lambda item: item[0]), start=1):
        if error:
            failures += 1
            print(error, flush=True)
        elif result is not None:
            results.append(result)
            print(format_result_line(result), flush=True)
        print(f"Clean speaker beta processed videos: {processed_count}", flush=True)

    # Downloads live in the stable cache so reruns can reuse the same local file
    # instead of paying the network and face-analysis cost again.

    unusable = count_unusable_results(results)
    published_output = publish_catalog_media(
        args=args,
        results=results,
        output_root=output_root,
        cache_root=cache_root,
    )
    summary = {
        "source": str(source),
        "output_root": str(run_root),
        "cache_root": str(cache_root),
        "options": summary_options_from_args(args),
        "processed": len(results),
        "failed": failures,
        "unusable": unusable,
        "published_output": str(published_output) if published_output is not None else "",
        "results": [
            {
                "status": result.status,
                "input_video": str(result.input_video),
                "output_dir": str(result.output_dir),
                "output_video": str(result.output_video),
                "message": result.message,
            }
            for result in results
        ],
    }
    (run_root / "clean_speaker_beta_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Clean speaker beta complete: {len(results)} processed, {failures} failed, {unusable} unusable.", flush=True)
    return 1 if failures or unusable else 0






def apply_runtime_limits(args: argparse.Namespace) -> None:
    """Apply process-level safety limits before importing heavy model work."""

    logger = lambda message: print(message, flush=True)
    configure_low_impact_native_threads(thread_count=max(1, int(args.native_threads)), logger=logger)
    lower_current_process_priority(logger=logger)
    limit_current_process_affinity(int(args.max_affinity_cores), logger=logger)
    avoid_logical_cpus(args.avoid_logical_cpu, logger=logger)


def apply_resume_filters(
    indexed_videos: list[tuple[int, backend.VideoItem]],
    *,
    args: argparse.Namespace,
) -> list[tuple[int, backend.VideoItem]]:
    """Apply skip-first resume semantics while preserving original video numbers."""

    skip_count = max(0, int(args.skip_first_videos))
    if skip_count <= 0:
        return indexed_videos
    skipped = indexed_videos[:skip_count]
    for index, video in skipped:
        print(f"Skipping resume video {index}: {video.speaker}/{video.title}", flush=True)
    return indexed_videos[skip_count:]


def process_selected_video(
    index: int,
    total: int,
    args: argparse.Namespace,
    options: ProcurementBetaOptions,
    video: backend.VideoItem,
    output_root: Path,
    cache_root: Path,
) -> tuple[int, VideoRunResult | None, str]:
    """Process one selected video and return a sortable result tuple."""

    try:
        result = run_video_item(index, total, args, options, video, output_root, cache_root)
        return index, result, ""
    except Exception as exc:
        gc.collect()
        return index, None, f"ERROR processing {video.title}: {exc}"


def run_video_item(
    index: int,
    total: int,
    args: argparse.Namespace,
    options: ProcurementBetaOptions,
    video: backend.VideoItem,
    output_root: Path,
    cache_root: Path,
) -> VideoRunResult:
    """Run the existing beta detector stack for one video item."""

    temp_root = cache_root / "_downloads"
    temp_root.mkdir(parents=True, exist_ok=True)
    print(f"Preparing video {index}/{total}: {video.speaker}/{video.title}", flush=True)
    wait_for_busy_thresholds(
        cpu_high_percent=args.cpu_throttle_high_percent,
        cpu_low_percent=args.cpu_throttle_low_percent,
        ram_high_percent=args.ram_throttle_high_percent,
        ram_low_percent=args.ram_throttle_low_percent,
        poll_seconds=options.resource_poll_seconds,
        timeout_seconds=options.resource_guard_timeout_seconds,
        logger=lambda message: print(message, flush=True),
        stage=f"video {index}/{total}",
    )
    wait_for_resource_headroom(
        min_free_percent=options.resource_guard_percent,
        output_path=output_root,
        poll_seconds=options.resource_poll_seconds,
        timeout_seconds=options.resource_guard_timeout_seconds,
        logger=lambda message: print(message, flush=True),
        stage=f"download for video {index}/{total}",
    )
    item = prepare_work_item(video, temp_root, max_download_height=args.max_download_height)
    print(f"Processing {item.speaker}/{item.title}", flush=True)
    result = process_video_file(
        item,
        run_root=cache_root,
        options=options,
        face_analyzer=FaceVisibilityAnalyzer(),
        voice_analyzer=MainVoiceAnalyzer(reference_audio=args.reference_audio),
        stitcher=stitch_with_ffmpeg,
    )
    gc.collect()
    return result


def run_single_video_child(args: argparse.Namespace) -> int:
    """Child-process entrypoint used by the safe isolated batch mode."""

    options = options_from_args(args)
    output_root = args.output_root.expanduser().resolve()
    cache_root = args.child_run_root.expanduser().resolve() if args.child_run_root else cache_root_from_output_root(output_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    video = video_item_from_json(args.single_video_json)
    print(
        f"Processing isolated global video {args.child_index}/{args.child_total}: {video.speaker}/{video.title}",
        flush=True,
    )
    try:
        result = run_video_item(args.child_index, args.child_total, args, options, video, output_root, cache_root)
        if args.child_result_json is not None:
            write_json(args.child_result_json, {"ok": True, "result": result_to_payload(result)})
        print(format_result_line(result), flush=True)
        return 0
    except Exception as exc:
        if args.child_result_json is not None:
            write_json(args.child_result_json, {"ok": False, "error": str(exc), "video": asdict(video)})
        print(f"ERROR processing {video.title}: {exc}", flush=True)
        return 1
    finally:
        gc.collect()


def run_isolated_parent(
    *,
    args: argparse.Namespace,
    options: ProcurementBetaOptions,
    source: str,
    scanned_count: int,
    indexed_videos: list[tuple[int, backend.VideoItem]],
    total_videos: int,
    output_root: Path,
    run_root: Path,
    cache_root: Path,
) -> int:
    """Run each selected video in a fresh Python process so memory is released."""

    isolated_root = run_root / "_isolated_items"
    isolated_root.mkdir(parents=True, exist_ok=True)
    results: list[VideoRunResult] = []
    failures = 0
    skipped_completed = 0
    processed_count = 0
    print("Clean speaker beta safe isolated mode enabled: one child process per video.", flush=True)

    for global_index, video in indexed_videos:
        if args.skip_completed_outputs:
            manifest_path = existing_completed_manifest(cache_root, video, options=options, args=args)
            if manifest_path is not None:
                skipped_completed += 1
                processed_count += 1
                results.append(cached_result_from_manifest(manifest_path, video))
                print(
                    f"Skipping completed global video {global_index}/{total_videos}: {video.speaker}/{video.title}",
                    flush=True,
                )
                print(f"Clean speaker beta processed videos: {processed_count}", flush=True)
                continue

        wait_for_busy_thresholds(
            cpu_high_percent=args.cpu_throttle_high_percent,
            cpu_low_percent=args.cpu_throttle_low_percent,
            ram_high_percent=args.ram_throttle_high_percent,
            ram_low_percent=args.ram_throttle_low_percent,
            poll_seconds=max(1.0, float(args.resource_poll_seconds)),
            timeout_seconds=max(0.0, float(args.resource_guard_timeout_seconds)),
            logger=lambda message: print(message, flush=True),
            stage=f"isolated child {global_index}/{total_videos}",
        )
        item_json = isolated_root / f"video_{global_index:04d}.json"
        result_json = isolated_root / f"video_{global_index:04d}_result.json"
        write_json(item_json, asdict(video))
        command = isolated_child_command(args, item_json, result_json, cache_root, global_index, total_videos)
        print(
            f"Starting isolated child for global video {global_index}/{total_videos}: {video.speaker}/{video.title}",
            flush=True,
        )
        returncode = run_child_process(command, args=args)
        child_payload = read_json(result_json)
        if returncode != 0 or not child_payload.get("ok"):
            failures += 1
            error = child_payload.get("error") or f"child exited with code {returncode}"
            print(f"ERROR isolated video {global_index}/{total_videos}: {error}", flush=True)
        else:
            results.append(result_from_payload(child_payload["result"]))
        processed_count += 1
        print(f"Clean speaker beta processed videos: {processed_count}", flush=True)
        cooldown = max(0.0, float(args.video_cooldown_seconds))
        if cooldown > 0 and processed_count < len(indexed_videos):
            print(f"Resource guard: cooling down for {cooldown:.0f}s before the next video.", flush=True)
            time.sleep(cooldown)
        gc.collect()

    unusable = count_unusable_results(results)
    published_output = publish_catalog_media(
        args=args,
        results=results,
        output_root=output_root,
        cache_root=cache_root,
    )
    summary = {
        "source": str(source),
        "scanned": scanned_count,
        "output_root": str(run_root),
        "cache_root": str(cache_root),
        "options": summary_options_from_args(args),
        "processed": len(results),
        "failed": failures,
        "skipped_completed": skipped_completed,
        "unusable": unusable,
        "published_output": str(published_output) if published_output is not None else "",
        "results": [result_to_payload(result) for result in results],
    }
    (run_root / "clean_speaker_beta_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Clean speaker beta complete: {len(results)} processed, {failures} failed, {unusable} unusable.", flush=True)
    return 1 if failures or unusable else 0


def isolated_child_command(
    args: argparse.Namespace,
    item_json: Path,
    result_json: Path,
    cache_root: Path,
    index: int,
    total: int,
) -> list[str]:
    """Build the child command explicitly so parent-only resume flags do not recurse."""

    command = [
        sys.executable,
        "-m",
        "procurement.procurement_beta.cli",
        "--source",
        str(args.source),
        "--output-root",
        str(args.output_root),
        "--output-mode",
        str(args.output_mode),
        "--percentage",
        str(args.percentage),
        "--min-clean-seconds",
        str(args.min_clean_seconds),
        "--max-segment-seconds",
        str(args.max_segment_seconds),
        "--gap-seconds",
        str(args.gap_seconds),
        "--identity-stills",
        str(args.identity_stills),
        "--scan-fps",
        str(args.scan_fps),
        "--validation-fps",
        str(args.validation_fps),
        "--face-confidence",
        str(args.face_confidence),
        "--speaker-confidence",
        str(args.speaker_confidence),
        "--workers",
        "1",
        "--device",
        str(args.device),
        "--resource-guard-percent",
        str(args.resource_guard_percent),
        "--resource-poll-seconds",
        str(args.resource_poll_seconds),
        "--resource-guard-timeout-seconds",
        str(args.resource_guard_timeout_seconds),
        "--video-cooldown-seconds",
        "0",
        "--max-affinity-cores",
        str(args.max_affinity_cores),
        "--native-threads",
        str(args.native_threads),
        "--cpu-throttle-high-percent",
        str(args.cpu_throttle_high_percent),
        "--cpu-throttle-low-percent",
        str(args.cpu_throttle_low_percent),
        "--ram-throttle-high-percent",
        str(args.ram_throttle_high_percent),
        "--ram-throttle-low-percent",
        str(args.ram_throttle_low_percent),
        "--max-download-height",
        str(args.max_download_height),
        "--single-video-json",
        str(item_json),
        "--child-result-json",
        str(result_json),
        "--child-run-root",
        str(cache_root),
        "--child-index",
        str(index),
        "--child-total",
        str(total),
    ]
    if args.keep_debug:
        command.append("--keep-debug")
    if args.parallel_detectors:
        command.append("--parallel-detectors")
    if args.run_final_output_validation:
        command.append("--run-final-output-validation")
    if args.reference_audio is not None:
        command.extend(["--reference-audio", str(args.reference_audio)])
    if args.reference_face_dir is not None:
        command.extend(["--reference-face-dir", str(args.reference_face_dir)])
    for cpu_index in args.avoid_logical_cpu or []:
        command.extend(["--avoid-logical-cpu", str(cpu_index)])
    return command


def run_child_process(command: list[str], *, args: argparse.Namespace) -> int:
    """Run one isolated child while streaming logs back to the launcher."""

    env = os.environ.copy()
    for name in tuple(env):
        if name.casefold() == "youtube_api_key":
            env.pop(name, None)
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "ONNX_NUM_THREADS", "ORT_NUM_THREADS"):
        env[name] = str(max(1, int(args.native_threads)))
    env["MEA_NATIVE_THREADS"] = str(max(1, int(args.native_threads)))
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    assert process.stdout is not None
    output_queue: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        try:
            for line in process.stdout:
                output_queue.put(line)
        finally:
            output_queue.put(None)

    reader = threading.Thread(
        target=read_output,
        daemon=True,
        name=f"clean-speaker-child-output-{process.pid}",
    )
    reader.start()
    deadline = time.monotonic() + ISOLATED_CHILD_TIMEOUT_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(
                f"ERROR: isolated child exceeded {ISOLATED_CHILD_TIMEOUT_SECONDS} seconds; terminating it.",
                flush=True,
            )
            terminate_child_tree(process)
            reader.join(timeout=1)
            return 124
        try:
            line = output_queue.get(timeout=min(0.5, remaining))
        except queue.Empty:
            continue
        if line is None:
            break
        print(line.rstrip("\r\n"), flush=True)
    reader.join(timeout=1)
    return process.wait()


def existing_completed_manifest(
    cache_root: Path,
    video: backend.VideoItem,
    *,
    options: ProcurementBetaOptions,
    args: argparse.Namespace,
) -> Path | None:
    """Find a verified successful manifest for the same source and options."""

    target_id = normalise_video_id(video.video_id or video.youtube_url or video.id)
    target_source = Path(video.source_path).expanduser().resolve() if video.source_path else None
    expected_context = expected_cache_context(options=options, args=args)
    for manifest_path in cache_root.glob("*/*/clean_speaker_beta_manifest.json"):
        payload = read_json(manifest_path)
        if payload.get("pipeline_version") != PROCUREMENT_BETA_CACHE_VERSION:
            continue
        if str(payload.get("status") or "") != "ok":
            continue
        if payload.get("options") != asdict(options):
            continue
        if payload.get("cache_context", {}) != expected_context:
            continue
        input_payload = payload.get("input", {}) if isinstance(payload.get("input"), dict) else {}
        if target_id:
            prior_id = normalise_video_id(str(input_payload.get("video_id") or input_payload.get("youtube_url") or ""))
            if prior_id != target_id:
                continue
        elif target_source is not None:
            prior_source = Path(str(input_payload.get("source_path") or "")).expanduser().resolve()
            if prior_source != target_source:
                continue
            if input_payload.get("source_identity") != file_cache_identity(target_source):
                continue
        else:
            continue
        output_video = Path(str(payload.get("output_video") or ""))
        if video_file_is_usable(output_video):
            return manifest_path
    return None


def expected_cache_context(
    *,
    options: ProcurementBetaOptions,
    args: argparse.Namespace,
) -> dict[str, object]:
    context: dict[str, object] = {}
    if args.reference_audio is not None:
        context["reference_audio"] = file_cache_identity(args.reference_audio)
    if options.face_reference_dir:
        context["reference_face"] = file_cache_identity(
            Path(options.face_reference_dir) / "reference_embedding.json"
        )
    return context


def cached_result_from_manifest(manifest_path: Path, video: backend.VideoItem) -> VideoRunResult:
    payload = read_json(manifest_path)
    return VideoRunResult(
        status="cached",
        input_video=Path(str((payload.get("input") or {}).get("source_path") or video.source_path)),
        output_dir=manifest_path.parent,
        output_video=Path(str(payload.get("output_video") or "")),
        message="Reused verified cached clean speaker output.",
    )


def terminate_child_tree(process: subprocess.Popen[str]) -> None:
    """Stop an isolated child and descendants after its wall-clock deadline."""

    try:
        import psutil

        parent = psutil.Process(process.pid)
        processes = [parent, *parent.children(recursive=True)]
        for item in reversed(processes):
            try:
                item.terminate()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
        _, alive = psutil.wait_procs(processes, timeout=10)
        for item in alive:
            try:
                item.kill()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
    except (ImportError, OSError):
        process.terminate()


def video_item_from_json(path: Path) -> backend.VideoItem:
    if path.is_symlink():
        raise ValueError(f"Isolated video control must not be a symlink: {path}")
    payload = read_control_json(
        path,
        label="isolated catalog video control",
        max_bytes=MAX_CATALOG_CONTEXT_BYTES,
        max_items=MAX_CATALOG_CONTEXT_ITEMS,
    )
    if not isinstance(payload, dict):
        raise ValueError("Isolated video control must be a JSON object.")
    speaker = str(payload["speaker"]) if "speaker" in payload else "Unknown Speaker"
    return backend.VideoItem(
        id=str(payload.get("id") or ""),
        title=str(payload.get("title") or ""),
        speaker=speaker,
        source_path=str(payload.get("source_path") or ""),
        source_kind=str(payload.get("source_kind") or "folder"),
        youtube_url=str(payload.get("youtube_url") or ""),
        video_id=str(payload.get("video_id") or ""),
        duration_seconds=payload.get("duration_seconds") if payload.get("duration_seconds") is not None else None,
        upload_date=str(payload.get("upload_date") or ""),
        license=str(payload.get("license") or "Unknown"),
        relative_path=str(payload.get("relative_path") or ""),
        thumbnail_url=str(payload.get("thumbnail_url") or ""),
        source_id=str(payload.get("source_id") or ""),
        metadata={
            str(key): str(value)
            for key, value in (payload.get("metadata") or {}).items()
        } if isinstance(payload.get("metadata"), dict) else {},
        youtube_language=str(payload.get("youtube_language") or ""),
    )


def result_to_payload(result: VideoRunResult) -> dict[str, object]:
    return {
        "status": result.status,
        "input_video": str(result.input_video),
        "output_dir": str(result.output_dir),
        "output_video": str(result.output_video),
        "message": result.message,
    }


def result_from_payload(payload: dict[str, object]) -> VideoRunResult:
    return VideoRunResult(
        status=str(payload.get("status") or "failed"),
        input_video=Path(str(payload.get("input_video") or "")),
        output_dir=Path(str(payload.get("output_dir") or "")),
        output_video=Path(str(payload.get("output_video") or "")),
        message=str(payload.get("message") or ""),
    )


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, object]:
    try:
        payload = read_control_json(
            path,
            label="clean speaker control",
            max_bytes=MAX_CLEAN_SPEAKER_JSON_BYTES,
            max_items=MAX_CLEAN_SPEAKER_JSON_ITEMS,
        )
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def count_unusable_results(results: list[VideoRunResult]) -> int:
    """Count outputs that completed technically but are not safe to use."""

    usable_statuses = {"ok", "cached"}
    return sum(1 for result in results if result.status not in usable_statuses)


def publish_catalog_media(
    *,
    args: argparse.Namespace,
    results: list[VideoRunResult],
    output_root: Path,
    cache_root: Path,
) -> Path | None:
    """Publish the one usable catalog result beside its source context."""

    if args.source_context is None:
        return None
    usable = [result for result in results if result.status in {"ok", "cached"}]
    if not usable:
        return None
    if len(usable) != 1:
        raise ValueError("A catalog source context must bind to exactly one clean speaker output.")

    result = usable[0]
    source = Path(result.output_video).expanduser()
    try:
        source_details = source.lstat()
        resolved_source = source.resolve(strict=True)
        resolved_cache = cache_root.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Clean speaker catalog output is unavailable for publication.") from exc
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0)
    attributes = int(getattr(source_details, "st_file_attributes", 0) or 0)
    if stat.S_ISLNK(source_details.st_mode) or (reparse_flag and attributes & reparse_flag):
        raise ValueError("Clean speaker catalog output must not be a symlink or reparse point.")
    if (
        not stat.S_ISREG(source_details.st_mode)
        or resolved_source.name != "stitched_imotions.mp4"
        or resolved_source == resolved_cache
        or resolved_cache not in resolved_source.parents
    ):
        raise ValueError("Clean speaker catalog output is not a canonical cache artifact.")
    target = output_root / "stitched_imotions.mp4"
    _copy_regular_file_atomically(
        resolved_source,
        source_details=source_details,
        target=target,
    )
    return target


def _copy_regular_file_atomically(
    source: Path,
    *,
    source_details: os.stat_result,
    target: Path,
) -> None:
    """Copy one stable regular file, then replace the public path atomically."""

    temporary = target.parent / f".{target.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    try:
        copied = 0
        with source.open("rb") as source_handle, temporary.open("xb") as target_handle:
            opened = os.fstat(source_handle.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or _file_identity(source_details) != _file_identity(opened)
                or source_details.st_size != opened.st_size
            ):
                raise ValueError("Clean speaker catalog output changed while it was opened.")
            for block in iter(lambda: source_handle.read(1024 * 1024), b""):
                target_handle.write(block)
                copied += len(block)
            target_handle.flush()
            os.fsync(target_handle.fileno())
            after = os.fstat(source_handle.fileno())
        if (
            _open_snapshot(after) != _open_snapshot(opened)
            or copied != opened.st_size
        ):
            raise ValueError("Clean speaker catalog output changed while it was copied.")
        if not video_file_is_usable(temporary):
            raise ValueError("Clean speaker catalog output is not usable for publication.")
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def select_videos(
    videos: list[backend.VideoItem],
    *,
    only_video_ids: list[str] | None = None,
    selected_speakers: list[str] | None = None,
    selected_source_ids: list[str] | None = None,
) -> list[backend.VideoItem]:
    """Return videos matching explicit ids and speaker groups in source order."""

    requested_ids = {normalise_video_id(value) for value in only_video_ids or [] if normalise_video_id(value)}
    requested_speakers = {
        run_docx_extractions.speaker_match_key(value)
        for value in selected_speakers or []
        if run_docx_extractions.speaker_match_key(value)
    }
    selected = list(videos)
    requested_source_ids = [str(value or "").strip() for value in selected_source_ids or []]
    if len(requested_source_ids) != len(set(requested_source_ids)):
        raise ValueError("Selected catalog SourceIDs must be unique.")
    if requested_source_ids:
        available_source_ids = {video.source_id for video in videos if video.source_id}
        unknown = sorted(set(requested_source_ids) - available_source_ids)
        if unknown:
            raise ValueError(f"Unknown catalog SourceID selection: {', '.join(unknown)}")
        requested_set = set(requested_source_ids)
        selected = [video for video in selected if video.source_id in requested_set]
    if requested_ids:
        selected = [
            video
            for video in selected
            if normalise_video_id(video.video_id or video.youtube_url or video.id) in requested_ids
        ]
    if requested_speakers:
        selected = [
            video
            for video in selected
            if run_docx_extractions.speaker_match_key(video.speaker) in requested_speakers
        ]
    return selected


def deduplicate_videos(videos: list[backend.VideoItem]) -> list[backend.VideoItem]:
    """Avoid processing the same speaker/video output key in parallel."""

    seen: set[tuple[str, str]] = set()
    selected: list[backend.VideoItem] = []
    for video in videos:
        identity = normalise_video_id(video.video_id or video.youtube_url or video.id)
        if not identity and video.source_path:
            identity = os.path.normcase(str(Path(video.source_path).expanduser().resolve()))
        key = (str(video.speaker).strip().casefold(), identity)
        if key in seen:
            print(f"Skipping duplicate clean speaker beta video row: {video.speaker}/{video.title}", flush=True)
            continue
        seen.add(key)
        selected.append(video)
    return selected


def choose_random_video(videos: list[backend.VideoItem], *, seed: str | int | None = None) -> list[backend.VideoItem]:
    """Pick one video for controlled validation without losing speaker metadata."""

    if not videos:
        return []
    seed_text = str(seed or "").strip()
    generator = random.Random(seed_text) if seed_text else random.SystemRandom()
    return [generator.choice(list(videos))]


def normalise_video_id(value: str | None) -> str:
    """Extract a YouTube video id from ids, URLs, or DOCX row identifiers."""

    text = str(value or "").strip()
    if not text:
        return ""
    video_id = run_docx_extractions.get_youtube_video_id(text)
    if video_id:
        return video_id
    if text.startswith("docx:"):
        parts = text.split(":")
        return parts[1] if len(parts) > 1 else ""
    return text
def videos_from_source_input(
    source_input: str | Path,
    *,
    enrich_youtube: bool = True,
    logger: Callable[[str], None] | None = None,
) -> tuple[str, list[backend.VideoItem]]:
    """Resolve a CLI source into the video rows that should be processed."""

    source_text = str(source_input).strip()
    video_id = run_docx_extractions.get_youtube_video_id(source_text)
    if video_id:
        scan = backend.scan_youtube_source(
            source_text,
            enrich_youtube=enrich_youtube,
            logger=logger,
        )
        items = [video for group in scan.groups for video in group.videos]
        return scan.source_path, items

    source_path = Path(source_text).expanduser().resolve()
    scan = backend.scan_input_source(source_path, enrich_youtube=enrich_youtube, logger=logger)
    videos = [video for group in scan.groups for video in group.videos]
    return str(source_path), videos


def catalog_video_from_context(
    source_input: str | Path,
    context_path: Path,
    *,
    selected_source_ids: list[str] | None = None,
) -> backend.VideoItem:
    """Build one beta input from the coordinator's bounded immutable context."""

    path = context_path.expanduser()
    if path.is_symlink():
        raise ValueError(f"Catalog source context must not be a symlink: {path}")
    payload = read_control_json(
        path,
        label="catalog source context",
        max_bytes=MAX_CATALOG_CONTEXT_BYTES,
        max_items=MAX_CATALOG_CONTEXT_ITEMS,
    )
    if not isinstance(payload, dict):
        raise ValueError("Catalog source context must be a JSON object.")
    source_id = str(payload.get("source_id") or "")
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise ValueError("Catalog source context has an invalid SourceID.")
    requested = [str(value or "").strip() for value in selected_source_ids or []]
    if len(requested) != len(set(requested)):
        raise ValueError("Selected catalog SourceIDs must be unique.")
    if requested != [source_id]:
        raise ValueError("Catalog source context does not match the selected SourceID.")
    resolved_link = str(payload.get("resolved_link") or "").strip()
    if not resolved_link:
        raise ValueError("Catalog source context does not match the selected source.")
    speaker = payload.get("speaker", "")
    if not isinstance(speaker, str):
        raise ValueError("Catalog source context Speaker must be text.")
    metadata = payload.get("user_metadata", {})
    if not isinstance(metadata, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in metadata.items()
    ):
        raise ValueError("Catalog source context metadata must contain text labels and values.")
    system = payload.get("system_metadata", {})
    if not isinstance(system, dict):
        raise ValueError("Catalog source context system metadata must be an object.")
    source_kind = str(payload.get("source_kind") or "")
    youtube_id = run_docx_extractions.get_youtube_video_id(resolved_link) if source_kind == "youtube" else ""
    if source_kind not in {"local", "youtube"} or (source_kind == "youtube" and not youtube_id):
        raise ValueError("Catalog source context has an unsupported source kind.")
    if source_kind == "local":
        processing_source = _validated_local_catalog_snapshot(source_input, payload, resolved_link)
    else:
        if not backend.source_references_match(source_input, resolved_link):
            raise ValueError("Catalog source context does not match the selected source.")
        processing_source = resolved_link
    duration_value = system.get("duration_seconds")
    duration = float(duration_value) if isinstance(duration_value, (int, float)) else None
    return backend.VideoItem(
        id=source_id,
        title=str(system.get("title") or (Path(resolved_link).stem if source_kind == "local" else youtube_id)),
        speaker=speaker,
        source_path=str(processing_source),
        source_kind="file" if source_kind == "local" else "youtube",
        youtube_url=resolved_link if source_kind == "youtube" else "",
        video_id=youtube_id,
        duration_seconds=duration,
        source_id=source_id,
        metadata=dict(metadata),
        youtube_language=str(system.get("youtube_language") or ""),
    )


def _validated_local_catalog_snapshot(
    source_input: str | Path,
    context: dict[str, object],
    original_link: str,
) -> Path:
    """Verify and return the coordinator-owned bytes passed to the beta child."""

    identity = context.get("local_identity")
    if not isinstance(identity, dict):
        raise ValueError("Catalog source context has no immutable local media identity.")
    canonical_path = identity.get("canonical_path")
    expected_digest = identity.get("sha256")
    expected_size = identity.get("size_bytes")
    if (
        not isinstance(canonical_path, str)
        or not canonical_path.strip()
        or not backend.source_references_match(canonical_path, original_link)
        or not isinstance(expected_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
        or not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size < 0
    ):
        raise ValueError("Catalog source context has an invalid immutable local media identity.")

    supplied = Path(source_input).expanduser()
    try:
        before = supplied.lstat()
    except OSError as exc:
        raise ValueError("Catalog local media snapshot is unavailable.") from exc
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0)
    attributes = int(getattr(before, "st_file_attributes", 0) or 0)
    if stat.S_ISLNK(before.st_mode) or (reparse_flag and attributes & reparse_flag):
        raise ValueError("Catalog local media snapshot must not be a symlink or reparse point.")
    if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
        raise ValueError("Catalog local media snapshot does not match its immutable local media identity.")

    snapshot = supplied.resolve(strict=True)
    digest = hashlib.sha256()
    size = 0
    with snapshot.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or _file_identity(before) != _file_identity(opened):
            raise ValueError("Catalog local media snapshot changed while it was opened.")
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
        after = os.fstat(handle.fileno())
    try:
        current = snapshot.lstat()
    except OSError as exc:
        raise ValueError("Catalog local media snapshot changed while it was read.") from exc
    if (
        _open_snapshot(after) != _open_snapshot(opened)
        or _file_identity(current) != _file_identity(opened)
        or size != expected_size
        or digest.hexdigest() != expected_digest
    ):
        raise ValueError("Catalog local media snapshot does not match its immutable local media identity.")
    return snapshot


def _file_identity(details: os.stat_result) -> tuple[int, int]:
    return int(details.st_dev), int(details.st_ino)


def _open_snapshot(details: os.stat_result) -> tuple[tuple[int, int], int, int, int]:
    return (
        _file_identity(details),
        int(details.st_size),
        int(details.st_mtime_ns),
        int(details.st_ctime_ns),
    )


def prepare_work_item(video: backend.VideoItem, temp_root: Path, *, max_download_height: int = 720) -> VideoWorkItem:
    source_path = Path(video.source_path).expanduser()
    if video.source_kind in {"folder", "file"} and source_path.exists() and source_path.is_file():
        local_video = source_path.resolve()
    elif video.youtube_url:
        local_video = download_youtube_video(video, temp_root, max_height=max_download_height)
    else:
        raise FileNotFoundError(f"Video source is not available locally and has no YouTube URL: {video.title}")

    duration = float(video.duration_seconds or backend.read_duration_seconds(local_video) or 0.0)
    return VideoWorkItem(
        speaker=video.speaker,
        title=video.title,
        source_path=local_video,
        youtube_url=video.youtube_url,
        video_id=video.video_id,
        duration_seconds=duration,
        source_id=video.source_id,
        source_metadata=dict(video.metadata),
        youtube_language=video.youtube_language,
    )


def download_youtube_video(video: backend.VideoItem, temp_root: Path, *, max_height: int = 720) -> Path:
    """Download a YouTube video at a research-friendly default resolution."""

    height = max(0, int(max_height))
    quality_suffix = f"h{height}" if height else "best"
    target = temp_root / f"{video.video_id or 'youtube_video'}_{quality_suffix}.mp4"
    with DOWNLOAD_CACHE_LOCK:
        if target.exists() and target.stat().st_size > 0:
            print(f"Download cache hit: {target}", flush=True)
            return target

        last_error: subprocess.CalledProcessError | None = None
        selectors = youtube_format_fallback_selectors(height)
        for attempt, format_selector in enumerate(selectors, start=1):
            command = youtube_download_command(video.youtube_url, target, format_selector)
            try:
                subprocess.run(
                    command,
                    check=True,
                    timeout=YOUTUBE_DOWNLOAD_TIMEOUT_SECONDS,
                    env=credential_free_media_environment(),
                )
                if target.exists() and target.stat().st_size > 0:
                    return target
            except subprocess.CalledProcessError as exc:
                last_error = exc
                remove_partial_downloads(target)
                if attempt < len(selectors):
                    print(f"Download failed for selected YouTube format; retrying fallback {attempt + 1}/{len(selectors)}.", flush=True)

        if last_error is not None:
            raise last_error
        raise FileNotFoundError(f"yt-dlp did not create expected output: {target}")


def youtube_download_command(youtube_url: str, target: Path, format_selector: str) -> list[str]:
    """Build one yt-dlp command for the requested fallback format."""

    command = build_yt_dlp_command(
        [
        "-f",
        format_selector,
        "--merge-output-format",
        "mp4",
        "-o",
        str(target),
        youtube_url,
        ],
        ffmpeg_binary=resolve_media_binary("ffmpeg", excluded_roots=(target.parent,)),
    )
    cookies_browser = str(os.getenv("YT_DLP_COOKIES_FROM_BROWSER") or "").strip()
    if cookies_browser:
        option_index = command.index("--ffmpeg-location") + 2
        command[option_index:option_index] = ["--cookies-from-browser", cookies_browser]
    return command


def ensure_output_outside_source(source_input: str | Path, output_root: Path) -> None:
    """Prevent generated Clean speaker videos from becoming future inputs."""

    source_text = str(source_input).strip()
    if run_docx_extractions.get_youtube_video_id(source_text):
        return
    source = Path(source_text).expanduser().resolve()
    if source.is_dir() and (output_root == source or source in output_root.parents):
        raise ValueError("Choose a Clean speaker output directory outside the input folder.")


def ensure_unique_output_destinations(videos: list[backend.VideoItem], cache_root: Path) -> None:
    """Reject any batch whose selected items would write to the same folder."""

    destinations: dict[Path, backend.VideoItem] = {}
    for video in videos:
        source_path = Path(video.source_path).expanduser()
        item = VideoWorkItem(
            speaker=video.speaker,
            title=video.title,
            source_path=source_path,
            youtube_url=video.youtube_url,
            video_id=video.video_id,
            duration_seconds=float(video.duration_seconds or 0),
            source_id=video.source_id,
            source_metadata=dict(video.metadata),
            youtube_language=video.youtube_language,
        )
        destination = output_directory_for_item(cache_root, item)
        previous = destinations.get(destination)
        if previous is not None:
            raise ValueError(
                "Two selected videos resolve to the same Clean speaker output folder: "
                f"{previous.title!r} and {video.title!r}."
            )
        destinations[destination] = video


def youtube_format_fallback_selectors(max_height: int) -> list[str]:
    """Return robust yt-dlp format selectors from preferred to safest fallback."""

    height = max(0, int(max_height))
    selectors = [youtube_format_selector(height)]
    if height > 0:
        selectors.append(youtube_progressive_format_selector(height))
        for fallback_height in (480, 360):
            if height > fallback_height:
                selectors.append(youtube_format_selector(fallback_height))
                selectors.append(youtube_progressive_format_selector(fallback_height))
    selectors.append(youtube_format_selector(0))
    deduped: list[str] = []
    for selector in selectors:
        if selector not in deduped:
            deduped.append(selector)
    return deduped


def youtube_progressive_format_selector(max_height: int) -> str:
    """Prefer a single-file MP4 fallback when separate video/audio streams fail."""

    if max_height <= 0:
        return "best[ext=mp4]/best"
    return f"best[height<={max_height}][ext=mp4]/best[height<={max_height}]/best[ext=mp4]/best"


def remove_partial_downloads(target: Path) -> None:
    """Remove partial yt-dlp stream files before trying a fallback format."""

    for candidate in target.parent.glob(f"{target.stem}*"):
        if candidate == target or candidate.name.startswith(f"{target.stem}."):
            try:
                candidate.unlink()
            except OSError:
                pass

def youtube_format_selector(max_height: int) -> str:
    """Return a yt-dlp format expression capped to a practical height."""

    if max_height <= 0:
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    return (
        f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={max_height}]+bestaudio/"
        f"best[height<={max_height}][ext=mp4]/best[height<={max_height}]/best"
    )


if __name__ == "__main__":
    raise SystemExit(main())

