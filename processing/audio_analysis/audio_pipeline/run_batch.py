from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from .batch import run_batch
from .cli import add_common_options, default_batch_output_root, print_error, print_progress


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse a procurement downloads folder with OpenSMILE.")
    parser.add_argument("input_folder", type=Path, help="Downloads folder from procurement/output/.../downloads.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Root output folder for audio analysis. Defaults to the project output folder.",
    )
    parser.add_argument("--stop-on-error", action="store_true", help="Stop at the first failed video.")
    add_common_options(parser)
    args = parser.parse_args()
    try:
        result = run_batch(
            args.input_folder,
            args.output or default_batch_output_root(),
            window_seconds=args.window_seconds,
            stride_seconds=args.stride_seconds,
            opensmile_feature_set=args.opensmile_feature_set,
            continue_on_error=not args.stop_on_error,
            skip_emotion_models=args.skip_emotion_models,
            device=args.device,
            keep_temp_audio=args.keep_temp_audio,
            debug=args.debug,
            progress=print_progress,
        )
    except (FileNotFoundError, NotADirectoryError, RuntimeError, subprocess.CalledProcessError, ValueError, OSError) as exc:
        print_error(f"ERROR: {exc}")
        raise SystemExit(1) from exc

    print_progress(f"Input folder: {args.input_folder.resolve()}")
    print_progress(f"Output folder: {result.output_root.resolve()}")
    print_progress(f"Processed videos: {result.processed_count}")
    print_progress(f"Failed videos: {result.failed_count}")
    print_progress(f"Batch manifest: {result.manifest_csv.resolve()}")
    print_progress(f"Run log: {result.run_log.resolve()}")


if __name__ == "__main__":
    main()
