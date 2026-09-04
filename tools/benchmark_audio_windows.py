"""Compare real Audio processing with FFmpeg versus direct PCM window export.

Run from the repository root with the installed project Python environment.
Uses the actual emotion models and acoustic extractor; first use may download
models unless HF_HUB_OFFLINE=1. Always requires a new output directory.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def data_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(line for line in handle if not line.startswith("#")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Short representative video with audio; preserved unchanged")
    parser.add_argument("--output", type=Path, required=True, help="New benchmark directory (must not exist)")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--native-threads", type=int, default=4)
    parser.add_argument("--window-seconds", type=float, default=10)
    parser.add_argument("--stride-seconds", type=float, default=5)
    args = parser.parse_args()
    if not 1 <= args.native_threads <= 256:
        parser.error("--native-threads must be between 1 and 256")
    if not args.input.is_file():
        parser.error("input must be an existing video file")
    if args.output.exists():
        parser.error("--output must be a new directory")
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "MEA_NATIVE_THREADS"):
        os.environ[name] = str(args.native_threads)
    from processing.audio_analysis.audio_pipeline import pipeline
    from processing.audio_analysis.audio_pipeline.config import resolve_ffmpeg_binary
    from processing.audio_analysis.audio_pipeline.emotion_models import EmotionModelBundle
    from processing.audio_analysis.audio_pipeline.windows import make_windows
    from procurement.external_tools import credential_free_media_environment

    # Validate workload settings before model loads or output creation.
    make_windows(1, args.window_seconds, args.stride_seconds)
    if args.window_seconds > 15:
        parser.error("emotion-enabled windows must not exceed 15 seconds")
    input_path = args.input.resolve()
    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    with input_path.open("rb") as handle:
        input_digest = hashlib.file_digest(handle, "sha256").hexdigest()
    started = time.perf_counter()
    models = EmotionModelBundle.load(skip=False, device=args.device)
    model_load_seconds = time.perf_counter() - started
    if not (models.categorical_available and models.dimensional_available):
        raise RuntimeError("Both real emotion-model layers must load for this benchmark.")
    optimized_export = pipeline.export_window_wav

    def legacy_export(source_wav, window, output_wav):
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            str(resolve_ffmpeg_binary(excluded_roots=(source_wav.parent, output_wav.parent))),
            "-y", "-ss", f"{window.start:.6f}", "-t", f"{window.duration:.6f}",
            "-i", str(source_wav), "-ac", "1", "-ar", "16000", str(output_wav),
        ], check=True, capture_output=True, text=True, timeout=21600,
            env=credential_free_media_environment())
        return output_wav

    report = {
        "input": str(input_path), "input_sha256": input_digest,
        "device": args.device, "native_threads": args.native_threads,
        "window_seconds": args.window_seconds, "stride_seconds": args.stride_seconds,
        "categorical_model": models.categorical_model_name,
        "categorical_revision": models.categorical_model_version,
        "dimensional_model": models.dimensional_model_name,
        "dimensional_revision": models.dimensional_model_version,
        "model_load_seconds": model_load_seconds,
        "order": ["ffmpeg", "pcm", "pcm", "ffmpeg"], "trials": [],
        "boundary": "One host/input/device; cached models reused; sequential ABBA includes scheduler/cache noise.",
    }
    try:
        for index, variant in enumerate(report["order"], 1):
            pipeline.export_window_wav = legacy_export if variant == "ffmpeg" else optimized_export
            started = time.perf_counter()
            result = pipeline.run_single_video(
                input_path, output_root / f"trial-{index}-{variant}",
                emotion_models=models, device=args.device,
                window_seconds=args.window_seconds, stride_seconds=args.stride_seconds,
                progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
            trial = {"variant": variant, "seconds": time.perf_counter() - started,
                     "window_count": result.window_count,
                     "audio_csv": str(result.audio_analysis_csv),
                     "acoustics_csv": str(result.opensmile_csv)}
            report["trials"].append(trial)
            (output_root / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    finally:
        pipeline.export_window_wav = optimized_export
    baseline = report["trials"][0]
    report["all_exported_data_identical"] = all(
        data_rows(Path(trial[key])) == data_rows(Path(baseline[key]))
        for trial in report["trials"] for key in ("audio_csv", "acoustics_csv")
    )
    with input_path.open("rb") as handle:
        report["input_unchanged"] = hashlib.file_digest(handle, "sha256").hexdigest() == input_digest
    medians = {variant: statistics.median(trial["seconds"] for trial in report["trials"] if trial["variant"] == variant) for variant in ("ffmpeg", "pcm")}
    report["median_seconds"] = medians
    report["observed_percent_reduction"] = 100 * (1 - medians["pcm"] / medians["ffmpeg"])
    (output_root / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["all_exported_data_identical"] and report["input_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
