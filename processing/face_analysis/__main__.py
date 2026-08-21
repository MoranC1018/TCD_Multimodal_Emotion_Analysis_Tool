"""Command-line entry point for native facial processing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import FaceProcessingConfig
from .health import check_readiness, prepare_detector_models
from .pipeline import process_face_input


def _print_progress(index: int, total: int, status: str, input_relative: str) -> None:
    """Emit one stable launcher-readable progress record."""

    print(f"Face item {index}/{total}: {status} {input_relative}", flush=True)


def _require_runtime_readiness(device: str) -> None:
    readiness = check_readiness(device)
    if not readiness.ready:
        raise RuntimeError(readiness.detail)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyse videos with Py-Feat Detectorv2.")
    parser.add_argument("input", type=Path, nargs="?", help="One video or a directory of videos")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--check",
        action="store_true",
        help=(
            "Check local Py-Feat/models, PyArrow, PyTorch/TorchCodec and "
            "FFmpeg/ffprobe readiness without downloading"
        ),
    )
    operation.add_argument(
        "--prepare-models",
        action="store_true",
        help="Explicitly download/load and validate all Py-Feat Detectorv2 weights",
    )
    parser.add_argument("--output-root", type=Path, default=Path("processing/face_analysis/output"))
    parser.add_argument("--sample-fps", type=float, default=5.0)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--face-threshold", type=float, default=0.90)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default="auto")
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--source-id",
        action="append",
        default=[],
        help="Analyse an authorized catalog SourceID. Repeat for multiple rows.",
    )
    parser.add_argument(
        "--catalog-sha256",
        default="",
        help="Exact digest of the authorized procurement catalog.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show a traceback for configuration/startup failures",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional caller/request identifier written to the run manifests",
    )
    args = parser.parse_args()
    if args.input is not None and (args.check or args.prepare_models):
        parser.error("input cannot be combined with --check or --prepare-models")
    if args.prepare_models:
        preparation = prepare_detector_models(args.device)
        print(json.dumps(preparation.to_dict(), ensure_ascii=False, indent=2))
        return 0 if preparation.ready else 1
    if args.check:
        readiness = check_readiness(args.device)
        print(json.dumps(readiness.to_dict(), ensure_ascii=False, indent=2))
        return 0 if readiness.ready else 1
    if args.input is None:
        parser.error("input is required unless --check or --prepare-models is used")
    try:
        result = process_face_input(
            args.input,
            args.output_root,
            config=FaceProcessingConfig(
                sample_fps=args.sample_fps,
                batch_size=args.batch_size,
                face_detection_threshold=args.face_threshold,
                device=args.device,
                recursive=not args.no_recursive,
                overwrite=args.overwrite,
                source_ids=tuple(args.source_id),
                catalog_sha256=str(args.catalog_sha256).casefold(),
            ),
            run_id=args.run_id,
            progress_callback=_print_progress,
            runtime_readiness_check=_require_runtime_readiness,
        )
    except KeyboardInterrupt:
        print("Facial processing cancelled; inspect run_manifest.json for partial status.", file=sys.stderr)
        return 130
    except Exception as exc:
        if args.debug:
            raise
        print(f"Facial processing failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Output root: {result.output_root}")
    print(f"Processed: {result.processed}; skipped: {result.skipped}; failed: {result.failed}")
    print(f"Run manifest: {result.run_manifest}")
    print(f"Run index: {result.run_index}")
    if result.failed:
        payload = json.loads(result.run_manifest.read_text(encoding="utf-8"))
        for record in payload.get("videos") or []:
            if record.get("status") != "failed":
                continue
            print(
                "FAILED "
                f"{record.get('input_relative') or record.get('input_video')}: "
                f"[{record.get('error_stage', 'unknown')}] "
                f"{record.get('error_type', 'Error')}: "
                f"{record.get('error_message') or record.get('error', '')}",
                file=sys.stderr,
            )
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
