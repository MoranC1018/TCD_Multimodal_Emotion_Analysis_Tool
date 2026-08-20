"""
Whisper Transcription Script (openai-whisper version)
======================================================

Transcribes a single video/audio file, or an entire folder tree of videos,
producing JSON files with segment-level transcripts and timestamps.

When the input is a folder the output mirrors the same directory structure.

Usage:
    # Install GPU PyTorch first (see README for CUDA version):
    pip install torch --index-url https://download.pytorch.org/whl/cu121
    pip install openai-whisper

    # Single file:
    python transcribe.py "Videos/clip.mp4"

    # Whole folder (output mirrors input tree under output/):
    python transcribe.py "Path/To/Videos" --output-dir output

    # From a preprocessing run folder (auto-finds stitched/full videos, names by title):
    python transcribe.py --from-preprocessing preprocessing/output/<run> --task bilingual

    # With options:
    python transcribe.py "Path/To/Videos" --language fr --task bilingual

    # Skip files that already have a JSON:
    python transcribe.py "Path/To/Videos" --skip-existing

Output (folder mode):
    output/
      subfolder_a/
        clip1.json
        clip2.json
      subfolder_b/
        clip3.json

Author: Jiaming Liu
"""

import argparse
import json
import sys
from pathlib import Path

import torch
import whisper

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
    ".webm", ".m4v", ".ts", ".mts", ".m2ts",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a",
}


def _resolve_device(device):
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        print("WARNING: CUDA requested but not available. Falling back to CPU.",
              file=sys.stderr)
        device = "cpu"
    return device


def _overlap(s1, e1, s2, e2):
    return max(0.0, min(e1, e2) - max(s1, s2))


def _align_segments(segs_fr, segs_en):
    """Merge French and English segments by time overlap."""
    if len(segs_fr) != len(segs_en):
        print(
            f"WARNING: segment count mismatch (fr={len(segs_fr)}, en={len(segs_en)}). "
            "Using time-based alignment.",
            file=sys.stderr,
        )

    segments = []
    for i, s in enumerate(segs_fr):
        if len(segs_fr) == len(segs_en):
            best_en = segs_en[i]
        else:
            best_en = max(
                segs_en,
                key=lambda e: _overlap(s["start"], s["end"], e["start"], e["end"]),
            )
        segments.append({
            "id": i,
            "start": round(s["start"], 2),
            "end": round(s["end"], 2),
            "text_fr": s["text"].strip(),
            "text_en": best_en["text"].strip(),
        })
        print(f"  [{s['start']:6.1f}s] FR: {s['text'].strip()[:60]}")
        print(f"           EN: {best_en['text'].strip()[:60]}")
    return segments


def transcribe_file(video_path, model, device, language=None, task="transcribe"):
    """Run Whisper on one video/audio file using a pre-loaded model."""
    fp16 = device == "cuda"

    if task == "bilingual":
        print(f"  Pass 1/2 — transcribing original: {video_path.name} ...")
        result_fr = model.transcribe(
            str(video_path), language=language, task="transcribe",
            verbose=False, fp16=fp16,
        )
        print(f"  Pass 2/2 — translating to English: {video_path.name} ...")
        result_en = model.transcribe(
            str(video_path), language=language, task="translate",
            verbose=False, fp16=fp16,
        )
        detected_lang = result_fr.get("language", "unknown")
        print(f"  Detected language: {detected_lang}")
        segments = _align_segments(result_fr["segments"], result_en["segments"])
    else:
        if task == "translate":
            print(f"  Transcribing + translating to English: {video_path.name} ...")
        else:
            print(f"  Transcribing: {video_path.name} ...")
        result = model.transcribe(
            str(video_path), language=language, task=task,
            verbose=False, fp16=fp16,
        )
        detected_lang = result.get("language", "unknown")
        print(f"  Detected language: {detected_lang}")
        segments = []
        for seg in result["segments"]:
            segments.append({
                "id": seg["id"],
                "start": round(seg["start"], 2),
                "end": round(seg["end"], 2),
                "text": seg["text"].strip(),
            })
            print(f"  [{seg['start']:6.1f}s] {seg['text'].strip()[:80]}")

    duration = segments[-1]["end"] if segments else 0.0

    return {
        "source": str(video_path),
        "language": detected_lang,
        "task": task,
        "duration_sec": duration,
        "model": model.dims.n_audio_ctx,  # kept for provenance; actual name set by caller
        "device": device,
        "segments": segments,
    }


def collect_videos(root: Path):
    """Return all video/audio files under root, sorted."""
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )


def collect_from_preprocessing(downloads_root: Path) -> list[tuple[Path, Path]]:
    """Find transcribable videos from a preprocessing downloads folder.

    Returns a list of (video_path, output_stem) pairs where output_stem is
    <Speaker>/<video_title> (using the video folder name, not the filename).

    Looks for:
      - stitched_imotions.mp4  (standard-license 10% sample)
      - *_full_video/*.mp4     (CC full-video download)
    """
    results: list[tuple[Path, Path]] = []
    for speaker_dir in sorted(downloads_root.iterdir()):
        if not speaker_dir.is_dir():
            continue
        for video_dir in sorted(speaker_dir.iterdir()):
            if not video_dir.is_dir():
                continue
            # Standard license: stitched_imotions.mp4
            stitched = video_dir / "stitched_imotions.mp4"
            if stitched.exists():
                results.append((stitched, Path(speaker_dir.name) / video_dir.name))
                continue
            # CC full-video: single mp4 directly inside *_full_video folder
            if video_dir.name.endswith("_full_video"):
                mp4s = [p for p in video_dir.iterdir()
                        if p.is_file() and p.suffix.lower() == ".mp4"]
                if mp4s:
                    results.append((mp4s[0], Path(speaker_dir.name) / video_dir.name))
    return results


def main():
    parser = argparse.ArgumentParser(description="Batch-transcribe video/audio with Whisper")
    parser.add_argument("input", nargs="?", default=None,
                        help="Path to a video/audio file OR a folder")
    parser.add_argument("--from-preprocessing", type=Path, default=None, metavar="RUN_FOLDER",
                        help="Preprocessing run folder (e.g. preprocessing/output/<run>). "
                             "Automatically finds stitched_imotions.mp4 / full-video files "
                             "under its downloads/ subfolder and names outputs by video title.")
    parser.add_argument("--model", default="small",
                        choices=["tiny", "base", "small", "medium",
                                 "large", "large-v2", "large-v3"],
                        help="Model size (default: small)")
    parser.add_argument("--language", default=None,
                        help="Language code (en/fr/pl/...). Auto-detected if omitted.")
    parser.add_argument("--device", default=None, choices=["cpu", "cuda"],
                        help="cpu or cuda. Default: auto-detect.")
    parser.add_argument("--task", default="transcribe",
                        choices=["transcribe", "translate", "bilingual"],
                        help="transcribe (default), translate to English, or bilingual.")
    parser.add_argument("--output-dir", default="output",
                        help="Root output folder (default: output/)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip videos whose JSON output already exists.")
    args = parser.parse_args()

    if args.from_preprocessing is None and args.input is None:
        parser.error("Provide either 'input' or --from-preprocessing.")

    output_root = Path(args.output_dir)
    device = _resolve_device(args.device)

    # ── Collect files ──────────────────────────────────────────────────────────
    # preprocessing mode: (video_path, output_stem) pairs with title-based names
    preprocessing_pairs: list[tuple[Path, Path]] | None = None

    if args.from_preprocessing:
        run_folder = args.from_preprocessing.resolve()
        downloads = run_folder / "downloads"
        if not downloads.is_dir():
            print(f"ERROR: no downloads/ folder found under {run_folder}", file=sys.stderr)
            sys.exit(1)
        preprocessing_pairs = collect_from_preprocessing(downloads)
        if not preprocessing_pairs:
            print(f"No transcribable videos found under {downloads}", file=sys.stderr)
            sys.exit(1)
        print(f"Found {len(preprocessing_pairs)} video(s) from preprocessing run.")
        videos = [p for p, _ in preprocessing_pairs]
    else:
        input_path = Path(args.input)
        if input_path.is_file():
            if input_path.suffix.lower() not in VIDEO_EXTENSIONS:
                print(f"ERROR: unsupported file type: {input_path.suffix}", file=sys.stderr)
                sys.exit(1)
            videos = [input_path]
            input_root = input_path.parent
        elif input_path.is_dir():
            videos = collect_videos(input_path)
            input_root = input_path
            if not videos:
                print(f"No video/audio files found under {input_path}", file=sys.stderr)
                sys.exit(1)
            print(f"Found {len(videos)} file(s) under {input_path}")
        else:
            print(f"ERROR: path not found: {input_path}", file=sys.stderr)
            sys.exit(1)

    # ── Filter already-done ────────────────────────────────────────────────────
    if args.skip_existing:
        pending_videos = []
        pending_pairs = []
        for i, video_path in enumerate(videos):
            if preprocessing_pairs:
                _, stem = preprocessing_pairs[i]
                out = output_root / stem.with_suffix(".json")
            else:
                out = output_root / video_path.relative_to(input_root).with_suffix(".json")
            if out.exists():
                print(f"  SKIP (exists): {out}")
            else:
                pending_videos.append(video_path)
                if preprocessing_pairs:
                    pending_pairs.append(preprocessing_pairs[i])
        videos = pending_videos
        if preprocessing_pairs:
            preprocessing_pairs = pending_pairs
        if not videos:
            print("All files already transcribed. Nothing to do.")
            sys.exit(0)
        print(f"{len(videos)} file(s) remaining after skipping existing outputs.")

    # ── Load model once ────────────────────────────────────────────────────────
    print(f"\nLoading Whisper model '{args.model}' on {device} ...")
    if device == "cuda":
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
    model = whisper.load_model(args.model, device=device)

    # ── Process each file ──────────────────────────────────────────────────────
    ok, failed = 0, []
    for idx, video_path in enumerate(videos, 1):
        if preprocessing_pairs:
            _, stem = preprocessing_pairs[idx - 1]
            out_path = output_root / stem.with_suffix(".json")
            rel = stem
        else:
            rel = video_path.relative_to(input_root)
            out_path = output_root / rel.with_suffix(".json")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"\n[{idx}/{len(videos)}] {rel}")
        try:
            result = transcribe_file(
                video_path, model, device,
                language=args.language,
                task=args.task,
            )
            # Store the human-readable model name instead of the internal dim
            result["model"] = args.model

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            print(f"  -> {out_path}  ({len(result['segments'])} segments)")
            ok += 1
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            failed.append((rel, exc))

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Done. {ok}/{ok + len(failed)} file(s) transcribed successfully.")
    if failed:
        print("Failed files:")
        for rel, exc in failed:
            print(f"  {rel}: {exc}")


if __name__ == "__main__":
    main()
