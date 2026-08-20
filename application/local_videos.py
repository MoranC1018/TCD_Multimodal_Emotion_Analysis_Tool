from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
from datetime import datetime
from pathlib import Path

from application import backend
from procurement.external_tools import credential_free_media_environment

FFMPEG_TIMEOUT_SECONDS = 6 * 60 * 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preprocess local video folders while preserving folder structure.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--mode", choices=["standard", "full"], required=True)
    parser.add_argument("--percentage", type=float, default=0.10)
    parser.add_argument("--max-segment-seconds", type=int, default=30)
    parser.add_argument(
        "--speaker",
        action="append",
        default=[],
        help="Process only this first-level speaker folder. May be repeated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.expanduser().resolve()
    output_base = args.output_root.expanduser().resolve()
    if source.is_dir() and (output_base == source or source in output_base.parents):
        raise ValueError("Choose an output directory outside the input folder to avoid reprocessing generated videos.")
    if not 0 < args.percentage <= 1:
        raise ValueError("Percentage must be greater than 0 and no more than 1.")
    if args.max_segment_seconds < 1:
        raise ValueError("Maximum segment length must be at least 1 second.")

    videos = source_videos(source, selected_speakers=getattr(args, "speaker", []))
    source_label = source.stem if source.is_file() else source.name
    output_root = output_base / f"{source_label}_local_{args.mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    print(f"Source: {source}")
    print(f"Output folder: {output_root}")
    for video in videos:
        relative = video.relative_to(source) if source.is_dir() else Path(video.name)
        target_dir = output_root / relative.with_suffix("")
        target_dir.mkdir(parents=True, exist_ok=True)
        print("=" * 70)
        print(f"Processing {relative}")
        try:
            if args.mode == "full":
                target = target_dir / "stitched_imotions.mp4"
                create_full_video(video, target)
                status = "ok"
                note = "Full local video validated and written as canonical MP4."
            else:
                target = target_dir / "stitched_imotions.mp4"
                create_standard_sample(video, target, args.percentage, args.max_segment_seconds)
                status = "ok"
                note = "Random local sample created."
            manifest = target_dir / "local_procurement_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "input_video": str(video),
                        "output_video": str(target),
                        "mode": args.mode,
                        "percentage": args.percentage,
                        "max_segment_seconds": args.max_segment_seconds,
                        "status": status,
                        "note": note,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            print(f"Output: {target}")
            rows.append({"status": status, "input": str(video), "output": str(target), "note": note})
        except Exception as exc:
            print(f"ERROR: {exc}")
            rows.append({"status": "failed", "input": str(video), "output": "", "note": str(exc)})

    (output_root / "local_procurement_manifest.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    failed = sum(1 for row in rows if row["status"] != "ok")
    print(f"Local procurement complete: {len(rows) - failed} processed, {failed} failed.")
    return 1 if failed else 0


def source_videos(source: Path, *, selected_speakers: list[str] | None = None) -> list[Path]:
    """Return videos for the source, optionally limited to named speaker groups."""

    if source.is_file():
        if source.suffix.casefold() not in backend.VIDEO_EXTENSIONS:
            supported = ", ".join(sorted(backend.VIDEO_EXTENSIONS))
            raise ValueError(f"Unsupported video format. Supported formats: {supported}.")
        videos = [source]
        speaker_for_video = lambda _video: source.parent.name
    else:
        if not source.exists() or not source.is_dir():
            raise FileNotFoundError(f"Input source does not exist: {source}")
        videos = list(backend.iter_video_files(source))
        speaker_for_video = lambda video: backend.speaker_from_relative_path(source, video.relative_to(source))

    if not videos:
        supported = ", ".join(sorted(backend.VIDEO_EXTENSIONS))
        raise ValueError(f"No supported videos found. Supported formats: {supported}.")

    requested = {
        backend.run_docx_extractions.speaker_match_key(speaker)
        for speaker in selected_speakers or []
        if backend.run_docx_extractions.speaker_match_key(speaker)
    }
    if requested:
        videos = [
            video
            for video in videos
            if backend.run_docx_extractions.speaker_match_key(speaker_for_video(video)) in requested
        ]
        if not videos:
            raise ValueError("No videos matched the selected speaker groups.")
    return videos


def create_standard_sample(video: Path, target: Path, percentage: float, max_segment_seconds: int) -> None:
    duration = backend.read_duration_seconds(video)
    if not duration or duration <= 0:
        raise RuntimeError(f"Could not read duration for {video}")
    total = max(1, math.floor(duration * percentage))
    segments = random_segments(duration, total, max_segment_seconds, seed=str(video))
    segment_files: list[Path] = []
    for index, (start, length) in enumerate(segments, start=1):
        segment = target.parent / f"segment_{index:03d}.mp4"
        command = backend.build_imotions_transcode_command(
            video,
            segment,
            start_seconds=start,
            duration_seconds=length,
        )
        subprocess.run(
            command,
            check=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
            env=credential_free_media_environment(),
        )
        segment_files.append(segment)

    concat_list = target.parent / "_concat_segments.txt"
    concat_list.write_text("".join(concat_file_line(item) for item in segment_files), encoding="utf-8")
    subprocess.run(
        backend.build_imotions_concat_command(concat_list, target),
        check=True,
        timeout=FFMPEG_TIMEOUT_SECONDS,
        env=credential_free_media_environment(),
    )
    if not backend.read_duration_seconds(target):
        raise RuntimeError(f"Sample output could not be validated: {target}")
    for path in [*segment_files, concat_list]:
        path.unlink(missing_ok=True)


def create_full_video(video: Path, target: Path) -> None:
    """Validate one local input and produce the MP4 contract used downstream."""

    if not backend.read_duration_seconds(video):
        raise RuntimeError(f"Input is not a valid video with positive duration: {video}")
    subprocess.run(
        backend.build_imotions_transcode_command(video, target),
        check=True,
        timeout=FFMPEG_TIMEOUT_SECONDS,
        env=credential_free_media_environment(),
    )
    if not target.exists() or target.stat().st_size <= 0 or not backend.read_duration_seconds(target):
        raise RuntimeError(f"Full-video output could not be validated: {target}")


def concat_file_line(path: Path) -> str:
    """Escape absolute paths for ffmpeg's single-quoted concat-list syntax."""

    escaped = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{escaped}'\n"


def random_segments(duration: float, total_seconds: int, max_segment_seconds: int, *, seed: str) -> list[tuple[float, float]]:
    """Spread a requested duration across non-overlapping deterministic clips."""

    if duration <= 0:
        raise ValueError("Video duration must be greater than zero.")
    if total_seconds < 0 or total_seconds > duration:
        raise ValueError("Requested sample duration must fit inside the video.")
    if max_segment_seconds < 1:
        raise ValueError("Maximum segment length must be at least one second.")
    if total_seconds == 0:
        return []

    rng = random.Random(seed)
    remaining = float(total_seconds)
    clip_lengths: list[float] = []
    while remaining > 0:
        length = min(float(max_segment_seconds), remaining)
        clip_lengths.append(length)
        remaining -= length

    # Randomly distribute all unselected time around the clips. This creates a
    # broad timeline sample while guaranteeing that no selected clips overlap.
    unselected_seconds = max(0.0, duration - sum(clip_lengths))
    weights = [rng.expovariate(1.0) for _ in range(len(clip_lengths) + 1)]
    weight_total = sum(weights)
    gaps = [unselected_seconds * weight / weight_total for weight in weights]

    cursor = gaps[0]
    segments: list[tuple[float, float]] = []
    for index, length in enumerate(clip_lengths):
        segments.append((cursor, length))
        cursor += length + gaps[index + 1]
    return segments


if __name__ == "__main__":
    raise SystemExit(main())
