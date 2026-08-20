#!/usr/bin/env python3
"""Python entrypoint for the DOCX-driven pre-processing workflow.

This replaces the Windows PowerShell wrapper so the pre-processing batch can be
started the same way on Windows, macOS, Linux, or inside the bundled Codex
Python runtime.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:  # pragma: no cover - supports direct script execution.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from procurement.external_tools import credential_free_media_environment


def resolve_python_executable() -> Path:
    """Find the Python executable that should run the lower-level wrapper."""

    env_python = os.environ.get("PYTHON")
    if env_python and Path(env_python).exists():
        return Path(env_python)

    # In normal use this script is already running under the desired Python.
    current_python = Path(sys.executable)
    if current_python.exists():
        return current_python

    for command_name in ("python", "py"):
        resolved = shutil.which(command_name)
        if resolved:
            return Path(resolved)

    bundled_python = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "python"
        / "python.exe"
    )
    if bundled_python.exists():
        return bundled_python

    raise FileNotFoundError("No Python executable found. Set PYTHON or install Python.")


def build_wrapper_command(
    *,
    python_executable: Path,
    script_root: Path,
    docx_path: Path,
    output_docx_path: Path | None = None,
    limit: int = 0,
    force: bool = False,
    no_stitch: bool = False,
) -> list[str]:
    """Build the command passed to the DOCX extraction wrapper."""

    command = [
        str(python_executable),
        "-m",
        "procurement.video_sampling.run_docx_extractions",
        str(docx_path),
        "--speaker-output-root",
        str(script_root),
    ]

    if output_docx_path is not None:
        command.extend(["--output", str(output_docx_path)])

    if limit > 0:
        command.extend(["--limit", str(limit)])

    if force:
        command.append("--force")

    if no_stitch:
        command.append("--no-stitch")

    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the DOCX-driven pre-processing workflow with speaker-based output folders."
    )
    parser.add_argument("docx_path", type=Path, help="DOCX file containing the video tables.")
    parser.add_argument("--output", type=Path, default=None, help="Optional edited DOCX output path.")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N detected videos.")
    parser.add_argument("--force", action="store_true", help="Re-run extraction even when a completed folder exists.")
    parser.add_argument("--no-stitch", action="store_true", help="Keep the 10 percent sample as raw clips instead of stitching.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script_root = Path(__file__).resolve().parent
    repo_root = script_root.parents[1]
    python_executable = resolve_python_executable()
    command = build_wrapper_command(
        python_executable=python_executable,
        script_root=script_root,
        docx_path=args.docx_path,
        output_docx_path=args.output,
        limit=args.limit,
        force=args.force,
        no_stitch=args.no_stitch,
    )

    print("Running pre-processing wrapper...")
    print(f"Python: {python_executable}")
    print("Wrapper module: procurement.video_sampling.run_docx_extractions")
    print(f"DOCX: {args.docx_path}")

    subprocess.run(
        command,
        check=True,
        cwd=repo_root,
        env=credential_free_media_environment(),
    )


if __name__ == "__main__":
    main()
