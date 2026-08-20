from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from .cli import add_common_options, default_single_output_dir, print_error, print_progress
from .pipeline import run_single_video
from .source_context import load_source_context


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse one MP4 with the Multimodal Emotion Analysis Tool audio workflow.")
    parser.add_argument("input_video", type=Path, help="Input .mp4 file.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output folder for this video. Defaults to the project output folder.",
    )
    add_common_options(parser)
    args = parser.parse_args()
    try:
        result = run_single_video(
            args.input_video,
            args.output or default_single_output_dir(args.input_video),
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
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError, ValueError, OSError) as exc:
        print_error(f"ERROR: {exc}")
        raise SystemExit(1) from exc

    print_progress(f"Video analysed: {args.input_video}")
    print_progress(f"Output folder: {result.output_dir.resolve()}")
    print_progress(f"Audio analysis: {result.audio_analysis_csv.resolve()}")
    print_progress(f"OpenSMILE features: {result.opensmile_csv.resolve()}")
    print_progress(f"Manifest: {result.manifest_path.resolve()}")


if __name__ == "__main__":
    main()
