"""Run the complete existing workflow without a browser: python -m application.cli."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
from pathlib import Path

from .automation.errors import CANCELLED, EXECUTION_ERROR, VALIDATION_ERROR, ValidationError

REPO_ROOT = Path(__file__).absolute().parents[1]


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValidationError(message)


def build_parser():
    parser = JsonArgumentParser(description="Automate procurement, Face, Audio, Text and Analysis using the existing engines.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "validate"):
        operation = sub.add_parser(name, help="Execute a job" if name == "run" else "Validate and describe a job without creating outputs")
        operation.add_argument("--job", type=Path, required=True)
        operation.add_argument("--run-dir", type=Path, required=True, help="New, exclusive evidence directory")
        if name == "run":
            operation.add_argument("--dry-run", action="store_true")
            operation.add_argument("--timeout", type=float, help="Whole-workflow deadline in seconds")
    schema = sub.add_parser("schema", help="Print the versioned JSON job schema")
    schema.add_argument("--stage", help="Show one stage's option schema")
    for name in ("status", "cancel"):
        operation = sub.add_parser(name)
        operation.add_argument("--run-dir", type=Path, required=True)
    sub.add_parser("settings", help="Describe per-job resource defaults and credential sources")
    check = sub.add_parser("doctor", help="Check local runtime readiness without installation or model downloads")
    check.add_argument("--component", choices=("all", "procurement", "audio", "face", "text", "clean-speaker"), default="all")
    check.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default="auto")
    check.add_argument("--text-stage", action="append", choices=("transcribe", "select", "prepare", "rocksteady", "postprocess"))
    inspect = sub.add_parser("inspect", help="Discover source/catalog/provenance and Analysis group inputs")
    kinds = inspect.add_subparsers(dest="kind", required=True)
    source = kinds.add_parser("source")
    source.add_argument("source")
    source.add_argument("--no-enrich", action="store_true", help="Skip optional YouTube metadata enrichment")
    catalog = kinds.add_parser("catalog")
    catalog.add_argument("source")
    for name in ("analysis-speakers", "analysis-profile"):
        operation = kinds.add_parser(name)
        operation.add_argument("--modality", nargs=3, action="append", required=True, metavar=("NAME", "METHOD", "PATH"))
        if name == "analysis-profile":
            operation.add_argument("--source-manifest")
    return parser


def dispatch(args):
    from .automation.config import job_schema, load_job
    from .automation import inspection, runner

    if args.command in {"run", "validate"}:
        timeout = getattr(args, "timeout", None)
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            raise ValidationError("--timeout must be a positive finite number.")
        job = load_job(args.job)
        if args.command == "validate" or args.dry_run:
            result = runner.plan_job(job, args.run_dir, repo_root=REPO_ROOT, python_executable=sys.executable)
            if timeout is not None:
                result["timeout_seconds"] = timeout
            return result, 0
        return runner.run_job(job, args.run_dir, repo_root=REPO_ROOT, python_executable=sys.executable, timeout_seconds=timeout)
    if args.command == "schema":
        result = job_schema()
        if args.stage:
            try:
                result = result["x-stage-options"][args.stage]
            except KeyError as exc:
                raise ValidationError(f"Unknown stage: {args.stage}") from exc
        return result, 0
    if args.command == "status":
        return runner.read_status(args.run_dir), 0
    if args.command == "cancel":
        return runner.request_cancel(args.run_dir), 0
    if args.command == "settings":
        return inspection.settings_description(), 0
    if args.command == "doctor":
        result = inspection.doctor(args.component, device=args.device, text_stages=args.text_stage)
        return result, 0 if result["state"] == "ready" else EXECUTION_ERROR
    if args.kind == "source":
        return inspection.inspect_source(args.source, enrich_youtube=not args.no_enrich), 0
    if args.kind == "catalog":
        return inspection.inspect_catalog(args.source), 0
    return inspection.inspect_analysis(args.kind, args.modality, getattr(args, "source_manifest", None)), 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        args = build_parser().parse_args(argv)
        # Engine imports and diagnostics can print; stdout belongs to one result.
        with contextlib.redirect_stdout(sys.stderr):
            result, code = dispatch(args)
    except (ValidationError, ValueError, TypeError, FileNotFoundError) as exc:
        result, code = {"state": "validation_failed", "error": str(exc), "exit_code": VALIDATION_ERROR}, VALIDATION_ERROR
    except KeyboardInterrupt:
        result, code = {"state": "cancelled", "exit_code": CANCELLED}, CANCELLED
    except Exception as exc:
        result, code = {"state": "failed", "error": str(exc), "exit_code": EXECUTION_ERROR}, EXECUTION_ERROR
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
