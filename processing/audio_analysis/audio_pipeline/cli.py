from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .batch import run_batch
from .doctor import run_doctor
from .full_stack import find_project_root
from .pipeline import run_single_video
from .source_context import load_source_context


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Multimodal Emotion Analysis Tool audio analysis: OpenSMILE over MP4 speech samples."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    single = subcommands.add_parser("single", help="Analyse one MP4 file.")
    single.add_argument("input_video", type=Path, help="Input .mp4 file.")
    single.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output folder for this video. Defaults to the project output folder.",
    )
    add_common_options(single)

    batch = subcommands.add_parser("batch", help="Analyse a procurement downloads folder.")
    batch.add_argument(
        "input_folder",
        type=Path,
        nargs="?",
        default=None,
        help="Downloads folder from procurement/output/.../downloads. Defaults to the latest procurement output.",
    )
    batch.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Root output folder for audio analysis. Defaults to the project output folder.",
    )
    batch.add_argument("--stop-on-error", action="store_true", help="Stop at the first failed video.")
    batch.add_argument(
        "--source-id",
        action="append",
        default=None,
        help="Analyse only this catalog SourceID. Repeat for multiple sources.",
    )
    batch.add_argument(
        "--catalog-sha256",
        default="",
        help="Expected SHA-256 from the selected batch folder's source manifest.",
    )
    add_common_options(batch)

    subcommands.add_parser("doctor", help="Check Python dependencies, model libraries, and external tools.")

    return parser


def default_batch_input_folder(project_root: Path | None = None) -> Path:
    root = (project_root or PROJECT_ROOT).expanduser().resolve()
    try:
        root = find_project_root(root)
    except FileNotFoundError:
        pass
    output_root = root / "procurement" / "output"
    candidates = [path for path in output_root.glob("*/downloads") if path.is_dir()]
    if not candidates:
        raise NotADirectoryError(
            f"No procurement downloads folders found under {output_root}. "
            "Pass an input folder explicitly."
        )
    return max(candidates, key=lambda path: path.parent.stat().st_mtime)


def default_batch_output_root() -> Path:
    return DEFAULT_OUTPUT_ROOT


def default_single_output_dir(input_video: Path) -> Path:
    video = input_video.expanduser().resolve()
    for parent in video.parents:
        if parent.name.casefold() == "downloads":
            return DEFAULT_OUTPUT_ROOT / video.parent.relative_to(parent)

    if video.name.casefold() == "stitched_imotions.mp4" and video.parent.name:
        return DEFAULT_OUTPUT_ROOT / video.parent.name

    return DEFAULT_OUTPUT_ROOT / video.stem


def print_progress(message: str) -> None:
    print_console(message)


def print_error(message: str) -> None:
    print_console(message, stream=sys.stderr)


def print_console(message: str, stream=sys.stdout) -> None:
    encoding = stream.encoding or "utf-8"
    safe_message = str(message).encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe_message, file=stream, flush=True)


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--window-seconds", type=float, default=10.0, help="Analysis window size in seconds; at most 15 with emotion models enabled.")
    parser.add_argument("--stride-seconds", type=float, default=5.0, help="Seconds between analysis windows.")
    parser.add_argument(
        "--opensmile-feature-set",
        choices=["egemaps", "compare", "compare16"],
        default="egemaps",
        help="OpenSMILE feature set. Use egemaps for the standard research pipeline.",
    )
    parser.add_argument(
        "--skip-emotion-models",
        action="store_true",
        help="Run only OpenSMILE extraction and leave model-output columns blank.",
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cpu", "cuda"],
        default="auto",
        help="Device for Hugging Face emotion models. auto uses CUDA when available.",
    )
    parser.add_argument(
        "--keep-temp-audio",
        action="store_true",
        help="Keep temporary extracted WAV windows under the per-video output folder for debugging.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Also run the categorical fallback model into output/debug for comparison; main outputs still use only the primary model.",
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "single":
            output_dir = args.output or default_single_output_dir(args.input_video)
            result = run_single_video(
                args.input_video,
                output_dir,
                window_seconds=args.window_seconds,
                stride_seconds=args.stride_seconds,
                opensmile_feature_set=args.opensmile_feature_set,
                skip_emotion_models=args.skip_emotion_models,
                device=args.device,
                keep_temp_audio=args.keep_temp_audio,
                debug=args.debug,
                source_context=load_source_context(args.input_video),
                progress=print_progress,
            )
            print_progress(f"Video analysed: {args.input_video}")
            print_progress(f"Output folder: {result.output_dir.resolve()}")
            print_progress(f"Audio analysis: {result.audio_analysis_csv.resolve()}")
            print_progress(f"OpenSMILE features: {result.opensmile_csv.resolve()}")
            print_progress(f"Manifest: {result.manifest_path.resolve()}")
        elif args.command == "batch":
            input_folder = args.input_folder or default_batch_input_folder()
            output_root = args.output or default_batch_output_root()
            result = run_batch(
                input_folder,
                output_root,
                window_seconds=args.window_seconds,
                stride_seconds=args.stride_seconds,
                opensmile_feature_set=args.opensmile_feature_set,
                continue_on_error=not args.stop_on_error,
                skip_emotion_models=args.skip_emotion_models,
                device=args.device,
                keep_temp_audio=args.keep_temp_audio,
                debug=args.debug,
                selected_source_ids=args.source_id,
                expected_catalog_sha256=args.catalog_sha256,
                progress=print_progress,
            )
            print_progress(f"Input folder: {input_folder.resolve()}")
            print_progress(f"Output folder: {result.output_root.resolve()}")
            print_progress(f"Processed videos: {result.processed_count}")
            print_progress(f"Failed videos: {result.failed_count}")
            print_progress(f"Batch manifest: {result.manifest_csv.resolve()}")
            print_progress(f"Run log: {result.run_log.resolve()}")
            if result.failed_count:
                raise SystemExit(1)
        elif args.command == "doctor":
            ok = run_doctor(print_progress)
            if not ok:
                raise SystemExit(1)
        else:
            parser.error(f"Unknown command: {args.command}")
    except (FileNotFoundError, NotADirectoryError, RuntimeError, subprocess.CalledProcessError, ValueError, OSError) as exc:
        print_error(f"ERROR: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
