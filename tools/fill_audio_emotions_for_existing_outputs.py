#!/usr/bin/env python3
"""Fill audio emotion-model columns for an existing OpenSMILE audio run.

This is intentionally separate from the normal audio extraction command. It
reuses already-generated `opensmile_features.csv` files, streams each selected
audio window from the stitched MP4, and writes a fresh `audio_analysis.csv`
with categorical and dimensional model outputs.
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from procurement.input_limits import (
    MAX_CLEAN_SPEAKER_JSON_BYTES,
    MAX_CLEAN_SPEAKER_JSON_ITEMS,
    read_control_json,
)


# Keep CPU inference from pinning every core. These must be set before torch is
# imported by the audio model adapters.
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "2")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIO_ANALYSIS_ROOT = REPO_ROOT / "processing" / "audio_analysis"
if str(AUDIO_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(AUDIO_ANALYSIS_ROOT))

from audio_pipeline.audio_analysis_csv import (  # noqa: E402
    build_audio_analysis_metadata,
    build_audio_analysis_rows,
    write_audio_analysis_csv,
)
from audio_pipeline.config import resolve_ffprobe_binary  # noqa: E402
from audio_pipeline.emotion_models import (  # noqa: E402
    DIMENSIONAL_MODEL_NAME,
    DIMENSIONAL_MODEL_REVISION,
    FALLBACK_CATEGORICAL_MODEL_NAME,
    FALLBACK_CATEGORICAL_MODEL_REVISION,
    DimensionalAffectModel,
    EmotionModelResult,
    FallbackCategoricalEmotionModel,
    import_torch,
    normalise_emotion_scores,
    resolve_device,
)
from audio_pipeline.media import extract_mono_wav  # noqa: E402
from audio_pipeline.pipeline import write_single_manifest  # noqa: E402
from audio_pipeline.windows import AudioWindow  # noqa: E402


try:
    import soundfile as sf
except ImportError as exc:  # pragma: no cover - runtime environment check.
    raise RuntimeError("soundfile is required for safe streamed audio-window inference.") from exc


@dataclass(frozen=True)
class SourceJob:
    """One existing audio output folder to enrich with model columns."""

    speaker: str
    video_id: str
    input_video: Path
    source_output_dir: Path
    target_output_dir: Path
    source_csv: Path
    source_audio_analysis_csv: Path
    source_opensmile_csv: Path


@dataclass
class CombinedEmotionModels:
    """Metadata/protocol object for fallback categorical + dimensional outputs."""

    categorical_model: FallbackCategoricalEmotionModel | None
    dimensional_model: DimensionalAffectModel | None
    device: str
    errors: list[str]
    categorical_model_name: str = FALLBACK_CATEGORICAL_MODEL_NAME
    categorical_model_version: str = FALLBACK_CATEGORICAL_MODEL_REVISION
    dimensional_model_name: str = DIMENSIONAL_MODEL_NAME
    dimensional_model_version: str = DIMENSIONAL_MODEL_REVISION
    skipped: bool = False

    @property
    def categorical_available(self) -> bool:
        return self.categorical_model is not None

    @property
    def dimensional_available(self) -> bool:
        return self.dimensional_model is not None


def main() -> int:
    args = parse_args()
    set_process_priority()

    source_root = Path(args.source_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    jobs = discover_jobs(source_root, output_root, args)
    if not jobs:
        raise SystemExit(f"No source audio jobs found under {source_root}")

    output_root.mkdir(parents=True, exist_ok=True)
    print(f"Source OpenSMILE run: {source_root}", flush=True)
    print(f"Emotion output root: {output_root}", flush=True)
    print(f"Jobs: {len(jobs)}", flush=True)
    print("Loading emotion models on CPU with capped torch threads.", flush=True)

    torch_module = import_torch()
    configure_torch(torch_module, args.torch_threads)
    device = resolve_device(args.device, torch_module)
    models = load_models(torch_module, device, args)

    manifest_rows: list[dict[str, object]] = []
    log_lines = [
        f"Run started: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Source root: {source_root}",
        f"Output root: {output_root}",
        f"Jobs: {len(jobs)}",
        f"Device: {device}",
        f"Torch threads: {args.torch_threads}",
        f"Categorical model: {models.categorical_model_name if models.categorical_available else 'unavailable'}",
        f"Dimensional model: {models.dimensional_model_name if models.dimensional_available else 'unavailable'}",
        f"Model notes: {' | '.join(models.errors)}",
        "",
    ]

    processed = 0
    failed = 0
    for index, job in enumerate(jobs, start=1):
        print(f"[{index}/{len(jobs)}] {job.speaker} {job.video_id}", flush=True)
        try:
            summary = process_job(job, models, args)
            processed += 1
            manifest_rows.append({**summary, "status": "ok", "error": ""})
            log_lines.append(f"OK: {job.input_video}")
        except Exception as exc:  # noqa: BLE001 - continue and report every failed video.
            failed += 1
            message = str(exc)
            print(f"[{index}/{len(jobs)}] ERROR: {message}", flush=True)
            manifest_rows.append(failure_row(job, message))
            log_lines.append(f"FAILED: {job.input_video} -> {message}")
            if args.stop_on_error:
                break

    write_batch_manifest(output_root / "audio_emotion_manifest.csv", manifest_rows)
    summary = {
        "source_root": str(source_root),
        "output_root": str(output_root),
        "processed": processed,
        "failed": failed,
        "device": device,
        "torch_threads": args.torch_threads,
        "categorical_model": models.categorical_model_name if models.categorical_available else "",
        "dimensional_model": models.dimensional_model_name if models.dimensional_available else "",
        "model_notes": models.errors,
    }
    (output_root / "audio_emotion_run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    log_lines.append("")
    log_lines.append(f"Batch complete: {processed} processed, {failed} failed.")
    (output_root / "audio_emotion_run_log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8-sig")
    print(f"Batch complete: {processed} processed, {failed} failed.", flush=True)
    return 0 if failed == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, help="Existing OpenSMILE audio output root.")
    parser.add_argument("--output-root", required=True, help="New output root with filled audio_analysis.csv files.")
    parser.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
    parser.add_argument("--torch-threads", type=int, default=2)
    parser.add_argument("--window-sleep", type=float, default=0.05, help="Small pause between windows to reduce sustained load.")
    parser.add_argument("--min-free-ram-percent", type=float, default=12.0)
    parser.add_argument("--max-cpu-percent", type=float, default=92.0)
    parser.add_argument("--resource-poll-seconds", type=float, default=5.0)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--skip-categorical", action="store_true")
    parser.add_argument("--skip-dimensional", action="store_true")
    return parser.parse_args()


def set_process_priority() -> None:
    try:
        import psutil

        process = psutil.Process()
        if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):
            process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        return


def configure_torch(torch_module, threads: int) -> None:
    safe_threads = max(1, int(threads))
    try:
        torch_module.set_num_threads(safe_threads)
    except Exception:
        pass
    try:
        torch_module.set_num_interop_threads(1)
    except Exception:
        pass


def load_models(torch_module, device: str, args: argparse.Namespace) -> CombinedEmotionModels:
    errors = [
        "preferred categorical model unavailable in this environment; categorical columns use the explicit SUPERB fallback model",
    ]
    categorical_model = None
    dimensional_model = None

    if not args.skip_categorical:
        print("Loading fallback categorical emotion model.", flush=True)
        categorical_model = FallbackCategoricalEmotionModel.load(torch_module, device)
    if not args.skip_dimensional:
        print("Loading dimensional affect model.", flush=True)
        dimensional_model = DimensionalAffectModel.load(torch_module, device)

    if categorical_model is None and dimensional_model is None:
        raise RuntimeError("No emotion models were enabled.")
    return CombinedEmotionModels(
        categorical_model=categorical_model,
        dimensional_model=dimensional_model,
        device=device,
        errors=errors,
    )


def discover_jobs(source_root: Path, output_root: Path, args: argparse.Namespace) -> list[SourceJob]:
    manifest = source_root / "audio_channel_manifest.csv"
    if not manifest.exists():
        raise FileNotFoundError(f"Missing audio_channel_manifest.csv: {manifest}")

    jobs: list[SourceJob] = []
    with manifest.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") != "ok":
                continue
            source_output_dir = Path(row["output_folder"]).expanduser().resolve()
            rel = source_output_dir.relative_to(source_root)
            target_output_dir = output_root / rel
            target_manifest = target_output_dir / "audio_analysis_manifest.json"
            target_csv = target_output_dir / "audio_analysis.csv"
            if args.resume and target_manifest.exists() and target_csv.exists():
                try:
                    payload = read_control_json(
                        target_manifest,
                        label="audio resume manifest",
                        max_bytes=MAX_CLEAN_SPEAKER_JSON_BYTES,
                        max_items=MAX_CLEAN_SPEAKER_JSON_ITEMS,
                    )
                    if not isinstance(payload, dict):
                        raise ValueError("audio resume manifest must be a JSON object")
                    if not payload.get("emotion_models_skipped", True):
                        print(f"Skipping completed output: {target_output_dir}", flush=True)
                        continue
                except (OSError, json.JSONDecodeError):
                    pass
            jobs.append(
                SourceJob(
                    speaker=row.get("speaker", ""),
                    video_id=row.get("video_id", ""),
                    input_video=Path(row["input_video"]).expanduser().resolve(),
                    source_output_dir=source_output_dir,
                    target_output_dir=target_output_dir,
                    source_csv=Path(row["source_csv"]).expanduser().resolve(),
                    source_audio_analysis_csv=Path(row["audio_analysis_csv"]).expanduser().resolve(),
                    source_opensmile_csv=Path(row["opensmile_features_csv"]).expanduser().resolve(),
                )
            )
    return jobs


def process_job(job: SourceJob, models: CombinedEmotionModels, args: argparse.Namespace) -> dict[str, object]:
    job.target_output_dir.mkdir(parents=True, exist_ok=True)
    opensmile_target = job.target_output_dir / "opensmile_features.csv"
    if job.source_opensmile_csv.exists():
        shutil.copyfile(job.source_opensmile_csv, opensmile_target)

    source_metadata, windows = read_source_windows(job.source_audio_analysis_csv)
    if not windows:
        raise ValueError(f"No windows found in {job.source_audio_analysis_csv}")

    partial_path = job.target_output_dir / "_emotion_rows_partial.jsonl"
    completed_rows = read_partial_rows(partial_path) if args.resume else []
    completed_count = len(completed_rows)
    if completed_count:
        print(f"  Resuming at window {completed_count + 1}/{len(windows)}.", flush=True)
    else:
        print(f"  Windows: {len(windows)}.", flush=True)

    with tempfile.TemporaryDirectory(prefix="audio_emotion_fill_") as temp_dir:
        temp_path = Path(temp_dir)
        audio_wav = extract_mono_wav(job.input_video, temp_path / "audio_16khz_mono.wav")
        with sf.SoundFile(str(audio_wav)) as audio_file:
            sample_rate = int(audio_file.samplerate)
            if sample_rate != 16000:
                raise RuntimeError(f"Expected 16 kHz audio after extraction, got {sample_rate} Hz.")
            for index, window in enumerate(windows[completed_count:], start=completed_count + 1):
                wait_for_headroom(args)
                samples = read_window_samples(audio_file, window, sample_rate)
                model_result = predict_samples(models, samples)
                row = build_audio_analysis_rows(
                    input_video=job.input_video,
                    windows=[window],
                    emotion_results=[model_result],
                    emotion_models=models,
                    opensmile_feature_set=source_metadata.get("OpenSMILEFeatureSet", "egemaps"),
                    window_seconds=float(source_metadata.get("WindowSeconds") or 10),
                    stride_seconds=float(source_metadata.get("StrideSeconds") or 5),
                )[0]
                append_partial_row(partial_path, row)
                completed_rows.append(row)
                if index % 25 == 0 or index == len(windows):
                    print(f"  Completed {index}/{len(windows)} windows.", flush=True)
                if args.window_sleep > 0:
                    time.sleep(args.window_sleep)

    metadata = build_audio_analysis_metadata(
        input_video=job.input_video,
        emotion_models=models,
        opensmile_feature_set=source_metadata.get("OpenSMILEFeatureSet", "egemaps"),
        window_seconds=float(source_metadata.get("WindowSeconds") or 10),
        stride_seconds=float(source_metadata.get("StrideSeconds") or 5),
    )
    metadata["Note"] = (
        "Categorical probabilities use the explicit SUPERB fallback model because the preferred "
        "Whisper categorical model is unavailable locally; dimensional affect uses the configured audeering model."
    )
    audio_analysis_csv = job.target_output_dir / "audio_analysis.csv"
    write_audio_analysis_csv(audio_analysis_csv, completed_rows, metadata=metadata)
    manifest_path = job.target_output_dir / "audio_analysis_manifest.json"
    duration_seconds = max(window.end for window in windows)
    write_single_manifest(
        manifest_path,
        input_video=job.input_video,
        audio_analysis_csv=audio_analysis_csv,
        opensmile_csv=opensmile_target,
        emotion_models=models,
        duration_seconds=duration_seconds,
        window_seconds=float(source_metadata.get("WindowSeconds") or 10),
        stride_seconds=float(source_metadata.get("StrideSeconds") or 5),
        window_count=len(windows),
        opensmile_feature_set=source_metadata.get("OpenSMILEFeatureSet", "egemaps"),
        keep_temp_audio=False,
    )
    if partial_path.exists():
        partial_path.unlink()
    gc.collect()
    return {
        "speaker": job.speaker,
        "video_id": job.video_id,
        "source_csv": str(job.source_csv),
        "input_video": str(job.input_video),
        "output_folder": str(job.target_output_dir),
        "audio_analysis_csv": str(audio_analysis_csv),
        "opensmile_features_csv": str(opensmile_target),
        "per_video_manifest": str(manifest_path),
        "window_count": len(windows),
    }


def read_source_windows(path: Path) -> tuple[dict[str, str], list[AudioWindow]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        raw_rows = list(csv.reader(handle))
    data_index = next((index for index, row in enumerate(raw_rows) if row and row[0] == "#DATA"), None)
    if data_index is None:
        raise ValueError(f"No #DATA section found in {path}")

    metadata: dict[str, str] = {}
    for row in raw_rows[:data_index]:
        if row and row[0].startswith("#") and len(row) > 1:
            metadata[row[0].lstrip("#")] = row[1]

    data_rows = raw_rows[data_index + 1 :]
    if not data_rows:
        return metadata, []
    header = data_rows[0]
    windows: list[AudioWindow] = []
    for raw_row in data_rows[1:]:
        padded = raw_row + [""] * max(0, len(header) - len(raw_row))
        row = {column: padded[index] if index < len(padded) else "" for index, column in enumerate(header)}
        try:
            windows.append(
                AudioWindow(
                    row=int(float(row["WindowIndex"])),
                    start=float(row["StartSeconds"]),
                    end=float(row["EndSeconds"]),
                )
            )
        except (KeyError, ValueError):
            continue
    return metadata, windows


def read_partial_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def append_partial_row(path: Path, row: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_window_samples(audio_file: sf.SoundFile, window: AudioWindow, sample_rate: int):
    start_frame = max(0, int(round(window.start * sample_rate)))
    frame_count = max(1, int(round(window.duration * sample_rate)))
    audio_file.seek(start_frame)
    samples = audio_file.read(frame_count, dtype="float32", always_2d=False)
    if getattr(samples, "ndim", 1) > 1:
        samples = samples.mean(axis=1)
    return samples


def predict_samples(models: CombinedEmotionModels, samples) -> EmotionModelResult:
    probabilities: dict[str, float | str | None]
    if models.categorical_model is None:
        probabilities = {}
    else:
        raw_scores = models.categorical_model.classifier({"array": samples, "sampling_rate": 16000}, top_k=None)
        if raw_scores and isinstance(raw_scores[0], list):
            raw_scores = raw_scores[0]
        probabilities = normalise_emotion_scores(raw_scores)

    arousal: float | str = ""
    dominance: float | str = ""
    valence: float | str = ""
    if models.dimensional_model is not None:
        processed = models.dimensional_model.processor(samples, sampling_rate=16000)
        torch_module = models.dimensional_model.torch
        input_values = torch_module.from_numpy(processed["input_values"][0]).reshape(1, -1).to(models.device)
        with torch_module.no_grad():
            _hidden_states, logits = models.dimensional_model.model(input_values)
        values = logits.detach().cpu().numpy()[0]
        arousal = float(values[0])
        dominance = float(values[1])
        valence = float(values[2])
        del input_values, logits
    return EmotionModelResult(probabilities=probabilities, arousal=arousal, dominance=dominance, valence=valence)


def wait_for_headroom(args: argparse.Namespace) -> None:
    try:
        import psutil
    except Exception:
        return

    while True:
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.1)
        if memory.available / memory.total * 100 >= args.min_free_ram_percent and cpu <= args.max_cpu_percent:
            return
        print(
            f"  Throttling: free RAM {memory.available / memory.total * 100:.1f}%, CPU {cpu:.1f}%.",
            flush=True,
        )
        time.sleep(args.resource_poll_seconds)


def failure_row(job: SourceJob, error: str) -> dict[str, object]:
    return {
        "status": "failed",
        "speaker": job.speaker,
        "video_id": job.video_id,
        "source_csv": str(job.source_csv),
        "input_video": str(job.input_video),
        "output_folder": str(job.target_output_dir),
        "audio_analysis_csv": "",
        "opensmile_features_csv": "",
        "per_video_manifest": "",
        "window_count": "",
        "error": error,
    }


def write_batch_manifest(path: Path, rows: Iterable[dict[str, object]]) -> None:
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
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
