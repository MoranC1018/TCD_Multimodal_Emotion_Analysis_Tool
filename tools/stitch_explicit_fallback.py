#!/usr/bin/env python3
"""Stitch one canonical clean video from an explicitly selected detector track."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

from procurement.procurement_beta.intervals import Interval
from procurement.procurement_beta.runner import cleanup_stitch_intermediates, stitch_with_ffmpeg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery-root", type=Path, required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--interval-file", type=Path, required=True)
    parser.add_argument("--selection-basis", required=True)
    parser.add_argument("--merge-gap-seconds", type=float, default=15.0)
    parser.add_argument("--minimum-seconds", type=float, default=10.0)
    parser.add_argument("--stitch-gap-seconds", type=float, default=0.5)
    return parser.parse_args()


def load_intervals(path: Path) -> list[Interval]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    intervals: list[Interval] = []
    for item in payload.get("intervals", []):
        start = float(item["start"])
        end = float(item["end"])
        if end > start:
            intervals.append(Interval(start, end, float(item.get("confidence", 0.65))))
    return sorted(intervals, key=lambda item: (item.start, item.end))


def merge_intervals(intervals: list[Interval], max_gap: float, minimum: float) -> list[Interval]:
    if not intervals:
        return []
    merged = [intervals[0]]
    for interval in intervals[1:]:
        previous = merged[-1]
        if interval.start - previous.end <= max_gap:
            merged[-1] = Interval(
                previous.start,
                max(previous.end, interval.end),
                min(previous.confidence, interval.confidence),
            )
        else:
            merged.append(interval)
    return [interval for interval in merged if interval.duration >= minimum]


def write_manifest(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    root = args.delivery_root.resolve()
    canonical_path = root / "04_metadata" / "manifests" / "canonical_delivery_manifest.csv"
    with canonical_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    row = next((item for item in rows if item["video_id"] == args.video_id), None)
    if row is None:
        raise RuntimeError(f"Video ID is not present in the canonical manifest: {args.video_id}")

    intervals = merge_intervals(
        load_intervals(args.interval_file.resolve()),
        args.merge_gap_seconds,
        args.minimum_seconds,
    )
    if not intervals:
        raise RuntimeError("No fallback intervals remain after filtering.")

    work_dir = root / "04_metadata" / "cache" / "fallback_stitches" / args.video_id
    work_dir.mkdir(parents=True, exist_ok=True)
    temporary_video = work_dir / "stitched_imotions.mp4"
    destination = Path(row["clean_video"])
    print(
        f"Fallback {args.video_id}: {len(intervals)} segments, "
        f"{sum(item.duration for item in intervals):.1f}s before stitch edge trims.",
        flush=True,
    )
    stitch_with_ffmpeg(Path(row["full_video"]), temporary_video, intervals, args.stitch_gap_seconds)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    shutil.move(str(temporary_video), str(destination))
    cleanup_stitch_intermediates(work_dir)

    selected = [
        {"start": item.start, "end": item.end, "duration": item.duration, "confidence": item.confidence}
        for item in intervals
    ]
    (work_dir / "selected_segments.json").write_text(
        json.dumps(
            {"selection_basis": args.selection_basis, "selected_segments": selected, "rejected_segments": []},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "status": "ok",
        "message": "Explicit detector-track fallback; see selection_basis and source_intervals.",
        "input": {
            "speaker": row["speaker"],
            "video_id": row["video_id"],
            "source_path": row["full_video"],
            "youtube_url": row["youtube_url"],
            "duration_seconds": float(row["sensor_duration_seconds"]),
        },
        "options": {
            "output_mode": "clean",
            "min_clean_seconds": args.minimum_seconds,
            "gap_seconds": args.stitch_gap_seconds,
        },
        "selection_basis": args.selection_basis,
        "source_intervals": str(args.interval_file.resolve()),
        "segment_plan": {"selected_segments": selected, "rejected_segments": []},
        "outputs": {"stitched_imotions": str(destination)},
    }
    (work_dir / "clean_speaker_beta_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    row["clean_video_found"] = "True"
    write_manifest(canonical_path, rows, fieldnames)
    print(f"Moved fallback clean output: {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
