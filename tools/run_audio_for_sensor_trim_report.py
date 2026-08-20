#!/usr/bin/env python3
"""Run audio analysis for the videos referenced by a sensor-trim report.

The sensor-trim report links each cleaned iMotions CSV to the clean-speaker beta
manifest that produced it. This utility follows those manifest paths back to
their `stitched_imotions.mp4` files and runs the existing audio pipeline over
exactly that subset.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIO_ANALYSIS_ROOT = REPO_ROOT / "processing" / "audio_analysis"
if str(AUDIO_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(AUDIO_ANALYSIS_ROOT))

from audio_pipeline.emotion_models import EmotionModelBundle  # noqa: E402
from audio_pipeline.pipeline import run_single_video  # noqa: E402


@dataclass(frozen=True)
class TrimmedVideoJob:
    """One cleaned iMotions row mapped to its stitched MP4."""

    source_csv: Path
    manifest: Path
    input_video: Path
    output_dir: Path
    speaker: str
    video_id: str


def main() -> int:
    args = parse_args()
    report_csv = Path(args.report_csv).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    jobs = load_jobs(report_csv, output_root)
    if not jobs:
        raise SystemExit(f"No processable rows found in trim report: {report_csv}")

    skip_emotion_models = not args.with_emotion_models
    print(f"Trim report: {report_csv}", flush=True)
    print(f"Output root: {output_root}", flush=True)
    print(f"Videos queued: {len(jobs)}", flush=True)
    if skip_emotion_models:
        print("Mode: OpenSMILE-only audio channel; emotion-model columns will be blank.", flush=True)
    else:
        print("Mode: OpenSMILE plus emotion models.", flush=True)

    # Load once and share across videos. In OpenSMILE-only mode this returns a
    # lightweight skipped bundle, keeping the per-video loop simple and explicit.
    emotion_models = EmotionModelBundle.load(skip=skip_emotion_models, device=args.device)

    rows: list[dict[str, object]] = []
    run_log: list[str] = [
        f"Run started: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Report CSV: {report_csv}",
        f"Output root: {output_root}",
        f"Videos queued: {len(jobs)}",
        f"OpenSMILE feature set: {args.opensmile_feature_set}",
        f"Window seconds: {args.window_seconds}",
        f"Stride seconds: {args.stride_seconds}",
        f"Emotion models skipped: {skip_emotion_models}",
        "",
    ]
    processed = 0
    failed = 0

    for index, job in enumerate(jobs, start=1):
        print(f"[{index}/{len(jobs)}] {job.speaker} {job.video_id}", flush=True)
        print(f"[{index}/{len(jobs)}] Input: {job.input_video}", flush=True)
        print(f"[{index}/{len(jobs)}] Output: {job.output_dir}", flush=True)
        try:
            result = run_single_video(
                job.input_video,
                job.output_dir,
                window_seconds=args.window_seconds,
                stride_seconds=args.stride_seconds,
                opensmile_feature_set=args.opensmile_feature_set,
                emotion_models=emotion_models,
                skip_emotion_models=skip_emotion_models,
                device=args.device,
                keep_temp_audio=args.keep_temp_audio,
                debug=args.debug,
                progress=lambda message: print(f"  {message}", flush=True),
            )
            processed += 1
            rows.append(
                {
                    "status": "ok",
                    "speaker": job.speaker,
                    "video_id": job.video_id,
                    "source_csv": str(job.source_csv),
                    "input_video": str(job.input_video),
                    "output_folder": str(result.output_dir),
                    "audio_analysis_csv": str(result.audio_analysis_csv),
                    "opensmile_features_csv": str(result.opensmile_csv),
                    "per_video_manifest": str(result.manifest_path),
                    "window_count": result.window_count,
                    "error": "",
                }
            )
            run_log.append(f"OK: {job.input_video}")
        except Exception as exc:  # noqa: BLE001 - keep batch moving and report all failures.
            failed += 1
            rows.append(
                {
                    "status": "failed",
                    "speaker": job.speaker,
                    "video_id": job.video_id,
                    "source_csv": str(job.source_csv),
                    "input_video": str(job.input_video),
                    "output_folder": str(job.output_dir),
                    "audio_analysis_csv": "",
                    "opensmile_features_csv": "",
                    "per_video_manifest": "",
                    "window_count": "",
                    "error": str(exc),
                }
            )
            run_log.append(f"FAILED: {job.input_video} -> {exc}")
            print(f"[{index}/{len(jobs)}] ERROR: {exc}", flush=True)
            if args.stop_on_error:
                break

    write_manifest(output_root / "audio_channel_manifest.csv", rows)
    summary = {
        "report_csv": str(report_csv),
        "output_root": str(output_root),
        "processed": processed,
        "failed": failed,
        "with_emotion_models": args.with_emotion_models,
        "opensmile_feature_set": args.opensmile_feature_set,
        "window_seconds": args.window_seconds,
        "stride_seconds": args.stride_seconds,
    }
    (output_root / "audio_channel_run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    run_log.append("")
    run_log.append(f"Batch complete: {processed} processed, {failed} failed.")
    (output_root / "audio_channel_run_log.txt").write_text("\n".join(run_log) + "\n", encoding="utf-8-sig")
    print(f"Batch complete: {processed} processed, {failed} failed.", flush=True)
    return 0 if failed == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-csv", required=True, help="sensor_trim_report.csv produced by trim_imotions_sensor_data.py.")
    parser.add_argument("--output-root", required=True, help="Folder where audio-channel outputs should be written.")
    parser.add_argument("--window-seconds", type=float, default=10.0)
    parser.add_argument("--stride-seconds", type=float, default=5.0)
    parser.add_argument("--opensmile-feature-set", choices=["egemaps", "compare", "compare16"], default="egemaps")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="cpu")
    parser.add_argument("--with-emotion-models", action="store_true", help="Also run the Hugging Face emotion models.")
    parser.add_argument("--keep-temp-audio", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args()


def load_jobs(report_csv: Path, output_root: Path) -> list[TrimmedVideoJob]:
    jobs: list[TrimmedVideoJob] = []
    with report_csv.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            manifest = Path(row["manifest"]).expanduser().resolve()
            input_video = manifest.parent / "stitched_imotions.mp4"
            if not input_video.exists():
                print(f"Skipping missing stitched video: {input_video}", flush=True)
                continue
            speaker = row.get("speaker", "Unknown Speaker") or "Unknown Speaker"
            video_id = row.get("video_id", "") or manifest.parent.name
            output_dir = output_root / safe_name(speaker) / f"{Path(row['source_csv']).stem}_[{video_id}]"
            jobs.append(
                TrimmedVideoJob(
                    source_csv=Path(row["source_csv"]),
                    manifest=manifest,
                    input_video=input_video,
                    output_dir=output_dir,
                    speaker=speaker,
                    video_id=video_id,
                )
            )
    return jobs


def write_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "status",
        "speaker",
        "video_id",
        "source_csv",
        "input_video",
        "output_folder",
        "audio_analysis_csv",
        "opensmile_features_csv",
        "per_video_manifest",
        "window_count",
        "error",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return name or "Unknown_Speaker"


if __name__ == "__main__":
    raise SystemExit(main())
