"""Command-line entry point for the complete text workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from processing.io_utils import lexical_absolute_path

from .pipeline import (
    STAGES,
    WHISPER_MODELS,
    check_text_processing_readiness,
    load_text_processing_config,
    run_text_pipeline,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the complete modular text-processing workflow.")
    parser.add_argument("input", nargs="?", default=None)
    parser.add_argument("--config", type=Path, help="Optional JSON object overriding pipeline defaults")
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Place every Text stage in one workspace root (used by the desktop UI).",
    )
    parser.add_argument("--from-stage", choices=STAGES, default="transcribe")
    parser.add_argument("--to-stage", choices=STAGES, default="postprocess")
    parser.add_argument("--whisper-model", choices=WHISPER_MODELS, default=None)
    parser.add_argument("--whisper-device", choices=("auto", "cpu", "cuda"), default=None)
    parser.add_argument(
        "--whisper-language",
        default=None,
        help="Explicit Whisper language used only when catalog system metadata is blank.",
    )
    parser.add_argument(
        "--source-id",
        action="append",
        default=None,
        help="Process an authorized catalog SourceID. Repeat for multiple rows.",
    )
    parser.add_argument(
        "--catalog-sha256",
        default=None,
        help="Exact digest of the authorized procurement catalog.",
    )
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument(
        "--dictionary",
        action="append",
        default=None,
        metavar="SOURCE:PATH",
        help="Repeat for each embedded:RESOURCE or file:PATH dictionary.",
    )
    category_group = parser.add_mutually_exclusive_group()
    category_group.add_argument(
        "--category",
        action="append",
        default=None,
        help="Repeat to export an explicit category set.",
    )
    category_group.add_argument(
        "--all-categories",
        action="store_true",
        help="Override config category filters and export every dictionary category.",
    )
    parser.add_argument(
        "--dictionary-combination", choices=("merge", "override"), default=None
    )
    parser.add_argument(
        "--default-language-variant", choices=("original", "eng"), default=None
    )
    parser.add_argument("--force-rocksteady", action="store_true")
    parser.add_argument("--no-graphs", action="store_true")
    parser.add_argument("--run-id", default=None, help="Optional caller-supplied run identifier")
    parser.add_argument(
        "--check", action="store_true",
        help=(
            "Validate Whisper, PyTorch, FFmpeg, Java and the exact RockSteady "
            "runtime/configuration, then exit without processing input."
        ),
    )
    parser.add_argument("--debug", action="store_true", help="Show a traceback on failure")
    args = parser.parse_args(argv)
    try:
        overrides = {
            "whisper_model": args.whisper_model,
            "whisper_device": args.whisper_device,
            "whisper_language": args.whisper_language,
            "source_ids": tuple(args.source_id) if args.source_id is not None else None,
            "catalog_sha256": args.catalog_sha256,
            "threads": args.threads,
            "dictionaries": tuple(args.dictionary) if args.dictionary is not None else None,
            "categories": (
                ()
                if args.all_categories
                else tuple(args.category)
                if args.category is not None
                else None
            ),
            "dictionary_combination": args.dictionary_combination,
            "default_language_variant": args.default_language_variant,
            "overwrite_rocksteady": True if args.force_rocksteady else None,
            "write_graphs": False if args.no_graphs else None,
        }
        if args.output_root is not None:
            output_root = lexical_absolute_path(args.output_root)
            overrides.update(
                {
                    "whisper_root": str(output_root / "transcripts"),
                    "selected_whisper_root": str(output_root / "selected_transcripts"),
                    "prepared_root": str(output_root / "prepared_segments"),
                    "selected_csv_root": str(output_root / "rocksteady" / "core"),
                    "extra_csv_root": str(output_root / "rocksteady" / "all"),
                    "postprocessing_root": str(output_root / "analysis"),
                }
            )
        config = load_text_processing_config(
            args.config,
            input_path=args.input,
            overrides=overrides,
        )
        if args.check:
            readiness = check_text_processing_readiness(config)
            print(
                json.dumps(
                    {"kind": "text-processing-readiness", **readiness},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        result = run_text_pipeline(
            config,
            from_stage=args.from_stage,
            to_stage=args.to_stage,
            run_id=args.run_id,
        )
        print(f"Completed stages: {', '.join(result.completed_stages)}")
        if result.selected_output is not None:
            print(f"Selected output: {result.selected_output}")
        if result.extra_output is not None:
            print(f"Extra output: {result.extra_output}")
        print(f"Manifest: {result.manifest}")
        return 0
    except KeyboardInterrupt:
        print("CANCELLED: Text processing was interrupted by the user.", file=sys.stderr)
        return 130
    except Exception as exc:
        if args.debug:
            raise
        if args.check:
            print(
                json.dumps(
                    {
                        "kind": "text-processing-readiness",
                        "status": "not_ready",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
