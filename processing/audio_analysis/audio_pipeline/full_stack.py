from __future__ import annotations

import csv
import re
import shutil
from pathlib import Path
from typing import Callable

from spreadsheet_safety import SpreadsheetSafeWriter


AUDIO_ANALYSIS_FILENAME = "audio_analysis.csv"


def export_batch_to_analysis_audio_outputs(
    audio_output_root: Path,
    *,
    repo_root: Path | None = None,
    run_name: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Copy per-video audio outputs into the analysis audio input area."""

    audio_output_root = audio_output_root.expanduser().resolve()
    resolved_repo_root = (repo_root or find_project_root(audio_output_root)).expanduser().resolve()
    audio_outputs_root = resolved_repo_root / "analysis" / "audio_outputs"
    destination_root = (
        audio_outputs_root
        / safe_folder_name(run_name or audio_output_root.name)
    )
    clear_destination_root(destination_root, audio_outputs_root)
    destination_root.mkdir(parents=True, exist_ok=True)

    copied_rows: list[dict[str, str]] = []
    for source_csv in sorted(audio_output_root.rglob(AUDIO_ANALYSIS_FILENAME), key=lambda item: str(item).casefold()):
        relative_path = source_csv.relative_to(audio_output_root)
        destination_csv = destination_root / relative_path
        destination_csv.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_csv, destination_csv)
        source_manifest = source_csv.parent / "audio_analysis_manifest.json"
        destination_manifest = destination_csv.parent / "audio_analysis_manifest.json"
        manifest_value = ""
        if source_manifest.exists():
            shutil.copy2(source_manifest, destination_manifest)
            manifest_value = str(destination_manifest)
        copied_rows.append(
            {
                "source_audio_analysis_csv": str(source_csv),
                "analysis_audio_analysis_csv": str(destination_csv),
                "analysis_audio_manifest_json": manifest_value,
                "relative_path": str(relative_path),
            }
        )

    write_manifest(destination_root / "audio_outputs_manifest.csv", copied_rows)
    emit(progress, f"Copied {len(copied_rows)} audio analysis CSV(s) to {destination_root}.")
    return destination_root


def find_project_root(start: Path) -> Path:
    """Find the repo root that owns procurement, processing, and analysis."""

    start = start.expanduser().resolve()
    search_points = [start, *start.parents]
    for path in search_points:
        if (path / "procurement").is_dir() and (path / "processing").is_dir() and (path / "analysis").is_dir():
            return path
    raise FileNotFoundError(
        "Could not find the Multimodal Emotion Analysis Tool project root. Pass repo_root explicitly "
        "or run from inside the project checkout."
    )


def write_manifest(path: Path, rows: list[dict[str, str]]) -> Path:
    fields = [
        "relative_path",
        "source_audio_analysis_csv",
        "analysis_audio_analysis_csv",
        "analysis_audio_manifest_json",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = SpreadsheetSafeWriter(csv.DictWriter(handle, fieldnames=fields))
        writer.writeheader()
        writer.writerows(rows)
    return path


def clear_destination_root(destination_root: Path, audio_outputs_root: Path) -> None:
    destination = destination_root.resolve()
    allowed_root = audio_outputs_root.resolve()
    if not destination.exists():
        return
    try:
        destination.relative_to(allowed_root)
    except ValueError as exc:
        raise RuntimeError(f"Refusing to clean path outside analysis/audio_outputs: {destination}") from exc
    if destination == allowed_root:
        raise RuntimeError(f"Refusing to clean audio_outputs root itself: {destination}")
    shutil.rmtree(destination)


def safe_folder_name(value: str) -> str:
    cleaned = re.sub(r"\s+", "_", value.strip())
    cleaned = re.sub(r"[^\w.\-]+", "_", cleaned, flags=re.UNICODE)
    cleaned = cleaned.strip("._")
    return cleaned or "audio_output"


def emit(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)
