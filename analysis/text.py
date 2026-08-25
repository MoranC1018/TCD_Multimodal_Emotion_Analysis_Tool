#!/usr/bin/env python3
"""RockSteady text-emotion analysis: analysis and export splitting.

Two sub-commands:

analyse  - run histogram/stats reports on a folder of per-speaker CSVs
split    - split a combined RockSteady export into one CSV per speaker

Usage::

    python -m analysis.text analyse INPUT_FOLDER
    python -m analysis.text split --input FILE --reference DIR --output-dir DIR
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from analysis.histograms import (
    AnalysisResult,
    ColumnInfo,
    ParsedExport,
    analyse_parsed_exports,
    analysis_root,
    resolve_output_folder,
)
from processing.io_utils import (
    assert_no_output_path_aliases,
    assert_safe_output_path,
    atomic_write_csv,
)


CORE_EMOTION_COLUMNS = {"Anger", "Disgust", "Fear", "Joy", "Sadness", "Surprise"}
SENTIMENT_COLUMNS = {"Negative", "Positive"}


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="latin-1", errors="replace")


# ---------------------------------------------------------------------------
# analyse: RockSteady folder analysis
# ---------------------------------------------------------------------------

def analyse_rocksteady_folder(
    input_folder: str | Path,
    output_root: str | Path | None = None,
    *,
    write_graphs: bool = True,
    include_logscale: bool = False,
) -> AnalysisResult:
    """Run the complete post-processing pipeline for one RockSteady output folder."""
    input_dir = resolve_input_folder(input_folder)
    if not input_dir.exists() or not input_dir.is_dir():
        raise NotADirectoryError(f"Input folder does not exist: {input_dir}")

    selected_files, discovery_log = discover_inputs(input_dir)
    if not selected_files:
        raise ValueError(f"No RockSteady CSV/XLSX files found in {input_dir}")

    exports = [read_rocksteady_file(path) for path in selected_files]
    return analyse_parsed_exports(
        input_dir=input_dir,
        output_dir=resolve_output_folder(input_dir, output_root),
        exports=exports,
        discovery_log=discovery_log,
        write_graphs=write_graphs,
        include_logscale=include_logscale,
    )


def default_rocksteady_root() -> Path:
    return analysis_root() / "text_output"


def resolve_input_folder(
    input_folder: str | Path,
    rocksteady_root: str | Path | None = None,
) -> Path:
    candidate = Path(input_folder)
    if candidate.exists():
        return candidate.resolve()
    if not candidate.is_absolute():
        root = Path(rocksteady_root).resolve() if rocksteady_root else default_rocksteady_root()
        rooted = root / candidate
        if rooted.exists():
            return rooted.resolve()
    return candidate.resolve()


def discover_inputs(input_folder: Path) -> tuple[list[Path], list[str]]:
    """Find CSV and XLSX files in the folder, de-duplicating by source name."""
    candidates = sorted(
        path
        for path in input_folder.glob("*")
        if path.is_file() and path.suffix.lower() in {".csv", ".xlsx"}
    )
    selected: list[Path] = []
    log_lines: list[str] = []
    seen_sources: set[str] = set()
    for path in candidates:
        source = _source_name(path)
        if source in seen_sources:
            log_lines.append(f"Skipped duplicate source {source}: {path.name}.")
            continue
        seen_sources.add(source)
        selected.append(path)
        log_lines.append(f"Selected {path.name} as source '{source}'.")
    return selected, log_lines


def _source_name(path: Path) -> str:
    name = re.sub(r"\s+", "_", path.stem.strip())
    return name or path.name


def read_rocksteady_file(path: Path) -> ParsedExport:
    """Read a RockSteady export (Percentage mode) and build a ParsedExport.

    Emotion and sentiment columns are already in 0-100 percentage range.
    scale_hint="0_to_100" tells the shared histogram engine not to rescale them.
    """
    raw_text = _read_text(path)
    rows_raw = list(csv.reader(raw_text.splitlines()))

    if not rows_raw:
        return ParsedExport(source=_source_name(path), path=path, header=[], info={}, rows=[])

    header = rows_raw[0]
    n_cols = len(header)

    info: dict[str, ColumnInfo] = {}
    for col in header:
        col_lower = col.strip().lower()
        if col_lower in {em.lower() for em in CORE_EMOTION_COLUMNS}:
            category = "emotion"
            scale_hint = "0_to_100"
            unit = ""
        elif col_lower in {s.lower() for s in SENTIMENT_COLUMNS}:
            category = "score"
            scale_hint = "0_to_100"
            unit = "index"
        else:
            category = ""
            scale_hint = ""
            unit = ""
        info[col] = ColumnInfo(unique_name=col, original_name=col, display_name=col, category=category, scale_hint=scale_hint, unit=unit)

    terms_col = next((h for h in header if h.strip().lower() == "terms"), None)

    data_rows: list[dict[str, str]] = []
    for raw_row in rows_raw[1:]:
        if not any(cell.strip() for cell in raw_row):
            continue
        if len(raw_row) == n_cols + 1:
            raw_row = [raw_row[0] + "," + raw_row[1]] + list(raw_row[2:])
        row_dict = {header[i]: (raw_row[i] if i < len(raw_row) else "") for i in range(n_cols)}
        repeat = 1
        if terms_col:
            try:
                repeat = max(1, int(float(row_dict.get(terms_col, "") or "1")))
            except ValueError:
                pass
        data_rows.extend([row_dict] * repeat)

    return ParsedExport(source=_source_name(path), path=path, header=header, info=info, rows=data_rows)


# ---------------------------------------------------------------------------
# split: combined export splitter
# ---------------------------------------------------------------------------

def build_title_to_speaker(reference_dir: Path) -> dict[str, str]:
    """Return {speech_title_stem: speaker_name} from a reference input folder."""
    mapping: dict[str, str] = {}
    for speaker_path in sorted(reference_dir.iterdir()):
        if not speaker_path.is_dir():
            continue
        speaker = speaker_path.name
        for speech_file in speaker_path.iterdir():
            if speech_file.is_file():
                mapping[speech_file.stem] = speaker
    return mapping


def read_csv_flexible(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read a RockSteady CSV/XLSX file; return (header, rows)."""
    raw_rows = list(csv.reader(_read_text(path).splitlines()))
    if not raw_rows:
        return [], []

    header = raw_rows[0]
    n_cols = len(header)
    data_rows: list[dict[str, str]] = []
    for raw in raw_rows[1:]:
        if not any(cell.strip() for cell in raw):
            continue
        if len(raw) == n_cols + 1:
            raw = [raw[0] + "," + raw[1]] + list(raw[2:])
        data_rows.append({header[i]: (raw[i] if i < len(raw) else "") for i in range(n_cols)})
    return header, data_rows


def match_title(title: str, mapping: dict[str, str]) -> str | None:
    """Return the speaker for a given title, or None if unmatched."""
    if title in mapping:
        return mapping[title]
    best: str | None = None
    best_len = 0
    for stem, speaker in mapping.items():
        if title.startswith(stem) or stem.startswith(title):
            overlap = min(len(title), len(stem))
            if overlap > best_len:
                best_len = overlap
                best = speaker
    return best


def write_speaker_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    parent = assert_no_output_path_aliases(path.parent, description="Text split output")
    parent.mkdir(parents=True, exist_ok=True)
    assert_no_output_path_aliases(path, description="Text split output")
    atomic_write_csv(path, rows, header)


def split(input_path: Path, reference_dir: Path, output_dir: Path) -> None:
    if not input_path.exists():
        sys.exit(f"Input file not found: {input_path}")
    if not reference_dir.exists() or not reference_dir.is_dir():
        sys.exit(f"Reference folder not found: {reference_dir}")

    output_dir = assert_safe_output_path(
        output_dir,
        protected_sources=(input_path, reference_dir),
        description="Text split output",
    )
    mapping = build_title_to_speaker(reference_dir)
    if not mapping:
        sys.exit(f"No speech files found under {reference_dir}")

    print(f"Reference mapping: {len(mapping)} speeches across {len(set(mapping.values()))} speakers")
    for speaker in sorted(set(mapping.values())):
        titles = [t for t, s in mapping.items() if s == speaker]
        print(f"  {speaker}: {len(titles)} speeches")

    header, rows = read_csv_flexible(input_path)
    if not rows:
        sys.exit("Input file is empty.")
    print(f"\nInput rows: {len(rows)}")

    by_speaker: dict[str, list[dict[str, str]]] = {}
    unmatched: list[dict[str, str]] = []
    title_col = header[0] if header else "Title"

    for row in rows:
        title = row.get(title_col, "").strip()
        speaker = match_title(title, mapping)
        if speaker:
            by_speaker.setdefault(speaker, []).append(row)
        else:
            unmatched.append(row)
            print(f"  [unmatched] {title[:80]}")

    output_dir.mkdir(parents=True, exist_ok=True)
    assert_no_output_path_aliases(output_dir, description="Text split output")
    for speaker, speaker_rows in sorted(by_speaker.items()):
        safe_speaker = re.sub(r'[<>:"/\\|?*\s]+', "_", speaker).strip("_")
        speaker_dir = output_dir / safe_speaker
        speaker_dir.mkdir(parents=True, exist_ok=True)
        for row in speaker_rows:
            title = row.get(title_col, "").strip()
            safe_title = re.sub(r'[<>:"/\\|?*]+', "_", title).strip("_") or "untitled"
            out_path = speaker_dir / f"{safe_title}.csv"
            write_speaker_csv(out_path, header, [row])
            print(f"  Wrote {safe_speaker}/{out_path.name}")

    if unmatched:
        unmatched_path = output_dir / "unmatched.csv"
        write_speaker_csv(unmatched_path, header, unmatched)
        print(f"  Wrote {len(unmatched)} unmatched rows -> {unmatched_path.name}")
    else:
        print("  All rows matched.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="RockSteady text-emotion analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyse = sub.add_parser("analyse", help="Run histogram/stats reports on a folder of per-video CSVs.")
    p_analyse.add_argument("input_folder", type=Path, help="Folder containing RockSteady CSV/XLSX files (one per speaker).")
    p_analyse.add_argument("--output-root", type=Path, default=None, help="Alternate report root. Defaults to analysis/output.")
    p_analyse.add_argument("--no-graphs", action="store_true", help="Skip SVG graph generation.")
    p_analyse.add_argument("--logscale", action="store_true", help="Also write log10(count + 1) histogram CSVs and graphs.")

    p_split = sub.add_parser("split", help="Split a combined RockSteady export into one CSV per speaker.")
    p_split.add_argument("--input", type=Path, required=True, help="Combined CSV/XLSX file to split.")
    p_split.add_argument("--reference", type=Path, required=True, help="Folder whose subdirectories are speaker names.")
    p_split.add_argument("--output-dir", type=Path, required=True, help="Folder to write the per-speaker CSV files into.")

    args = parser.parse_args()

    if args.command == "analyse":
        result = analyse_rocksteady_folder(
            args.input_folder,
            output_root=args.output_root,
            write_graphs=not args.no_graphs,
            include_logscale=args.logscale,
        )
        print(f"Output folder:  {result.output_dir}")
        print(f"Other findings: {result.other_findings_dir}")
        print(f"Histogram CSVs: {len(result.histogram_paths)}")
        print(f"Graphs:         {len(result.graph_paths)}")

    elif args.command == "split":
        split(args.input, args.reference, args.output_dir)


if __name__ == "__main__":
    main()
