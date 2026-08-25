#!/usr/bin/env python3
"""Source-specific feeder for folder-level iMotions CSV exports."""

from __future__ import annotations

import argparse
import csv
import re
from collections import OrderedDict
from pathlib import Path
from processing.io_utils import (
    assert_confined_input_file,
    assert_input_file_budget,
    assert_no_output_path_aliases,
)
from typing import Iterable, Iterator, Sequence

from analysis.histograms import (
    AnalysisResult,
    ColumnInfo,
    CORE_EMOTION_ORDER,
    ParsedExport,
    analyse_domain_split_parsed_exports,
    analysis_root,
    resolve_output_folder,
    safe_filename,
)
from analysis.metadata import load_source_metadata
from analysis.video_contract import VIDEO_METRICS


IMOTIONS_VIDEO_PROVIDER = "iMotions AFFDEX"


def read_imotions_video_folder(
    input_folder: str | Path,
    *,
    allow_legacy_reports: bool = False,
) -> tuple[ParsedExport, ...]:
    """Read iMotions Video sources without writing Analysis output."""

    root = Path(input_folder).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"iMotions input folder does not exist: {root}")
    selected_csvs, _discovery_log = discover_csv_inputs(root)
    if selected_csvs:
        return tuple(
            _canonicalize_video_export(read_imotions_csv(path, input_root=root))
            for path in selected_csvs
        )
    if not allow_legacy_reports:
        raise ValueError(f"No accepted iMotions CSV exports found under {root}")
    return _read_legacy_video_reports(root)


def analyse_imotions_folder(
    input_folder: str | Path,
    output_root: str | Path | None = None,
    *,
    write_graphs: bool = True,
    include_logscale: bool = False,
    include_landmarks: bool = False,
    include_timing: bool = False,
    exclude_geometry: bool = False,
) -> AnalysisResult:
    """Run the complete post-processing pipeline for one iMotions output folder."""

    input_dir = resolve_input_folder(input_folder)
    if not input_dir.exists() or not input_dir.is_dir():
        raise NotADirectoryError(f"Input folder does not exist: {input_dir}")

    selected_csvs, discovery_log = discover_csv_inputs(input_dir)
    if not selected_csvs:
        raise ValueError(f"No CSV files found in {input_dir} or its speaker subfolders.")

    exports = [read_imotions_csv(path, input_root=input_dir) for path in selected_csvs]
    return analyse_domain_split_parsed_exports(
        input_dir=input_dir,
        output_root=output_root,
        exports=exports,
        discovery_log=discovery_log,
        write_graphs=write_graphs,
        include_logscale=include_logscale,
        include_landmarks=include_landmarks,
        include_timing=include_timing,
        exclude_geometry=exclude_geometry,
    )


def default_imotions_root() -> Path:
    """Return the analysis-local iMotions input folder."""

    return analysis_root() / "iMotions_Output"


def default_output_root() -> Path:
    """Return the analysis-local report output folder."""

    return analysis_root() / "output"


def resolve_input_folder(input_folder: str | Path, imotions_root: str | Path | None = None) -> Path:
    """Resolve direct paths and bare names under analysis/iMotions_Output."""

    candidate = Path(input_folder)
    if candidate.exists():
        return candidate.resolve()

    if not candidate.is_absolute():
        root = Path(imotions_root).resolve() if imotions_root else default_imotions_root()
        rooted_candidate = root / candidate
        if rooted_candidate.exists():
            return rooted_candidate.resolve()

    return candidate.resolve()


def discover_csv_inputs(input_folder: Path) -> tuple[list[Path], list[str]]:
    """Select iMotions CSV exports, supporting one speaker folder or a run root.

    A single-speaker input usually contains CSVs directly. A run input, such as
    DemoDay, contains speaker subfolders with CSVs inside. We keep the direct
    behavior when direct CSVs exist; otherwise we recurse into subfolders.
    """

    input_folder = assert_no_output_path_aliases(
        input_folder, description="iMotions input"
    ).resolve(strict=True)
    candidates = []
    for path in input_folder.rglob("*.csv"):
        safe = assert_confined_input_file(path, input_folder, description="iMotions input")
        if looks_like_imotions_csv(safe):
            candidates.append(safe)
    candidates.sort(key=lambda path: str(path).casefold())
    assert_input_file_budget(candidates, description="iMotions input")
    recursive_mode = True

    selected: OrderedDict[str, Path] = OrderedDict()
    scores: dict[str, int] = {}
    log_lines: list[str] = []

    for path in candidates:
        source = source_name(path)
        source_key = dedupe_source_key(input_folder, path, recursive_mode)
        score = path.stat().st_size
        if source_key not in selected:
            selected[source_key] = path
            scores[source_key] = score
            log_lines.append(f"Selected {path.relative_to(input_folder)} as source {source}.")
            continue

        if score > scores[source_key]:
            log_lines.append(
                f"Replaced {selected[source_key].relative_to(input_folder)} with larger re-export "
                f"{path.relative_to(input_folder)} for source {source}."
            )
            selected[source_key] = path
            scores[source_key] = score
        else:
            log_lines.append(f"Skipped duplicate source {source}: {path.relative_to(input_folder)}.")

    return list(selected.values()), log_lines


def looks_like_imotions_csv(path: Path) -> bool:
    """Identify iMotions exports by their data header, not their location."""

    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            for index, row in enumerate(csv.reader(handle)):
                if row and row[0].strip() == "#DATA":
                    return True
                if len(row) >= 2 and row[0].strip() == "Row" and row[1].strip() == "Timestamp":
                    return True
                if index >= 200:
                    break
    except OSError:
        return False
    return False


def dedupe_source_key(input_folder: Path, path: Path, recursive_mode: bool) -> str:
    """Keep same-named videos distinct across speakers while merging re-exports."""

    source = source_name(path)
    if not recursive_mode:
        return source
    relative_parent = path.parent.relative_to(input_folder)
    return f"{relative_parent}::{source}"


def source_name(path: Path) -> str:
    """Return a stable source label derived from an iMotions export filename."""

    name = re.sub(r"\s+", "_", path.stem.strip())
    reexport_suffix = "_April_24_2026"
    if name.endswith(reexport_suffix):
        name = name[: -len(reexport_suffix)]
    return name


def read_imotions_csv(path: Path, encoding: str = "utf-8-sig", input_root: Path | None = None) -> ParsedExport:
    """Read iMotions metadata while keeping data rows repeatable and disk-backed."""

    metadata_rows, raw_header, data_count = inspect_imotions_csv(path, encoding)
    header = make_unique(raw_header)
    info = build_column_info(metadata_rows, raw_header, header)
    if data_count <= 0:
        raise ValueError(f"No iMotions data rows were found in {path}")

    return ParsedExport(
        source=source_name(path),
        path=path,
        header=header,
        info=info,
        rows=ImotionsRowSequence(path, header, encoding, data_count),
        speaker=imotions_speaker_name(path, input_root),
        video=source_name(path),
    )


def _canonicalize_video_export(export: ParsedExport) -> ParsedExport:
    fields: dict[str, str] = {}
    canonical_info: dict[str, ColumnInfo] = {}
    for unique_name in export.header:
        info = export.info.get(unique_name)
        if info is None:
            continue
        canonical = _canonical_video_metric(info)
        if canonical is None or canonical in fields:
            continue
        fields[canonical] = unique_name
        canonical_info[canonical] = info
    rows = [
        {canonical: row.get(source_field, "") for canonical, source_field in fields.items()}
        for row in export.rows
    ]
    return ParsedExport(
        source=export.source,
        path=export.path,
        header=list(fields),
        info=canonical_info,
        rows=rows,
        speaker=export.speaker,
        video=export.video,
    )


def _canonical_video_metric(info: ColumnInfo) -> str | None:
    aliases = {"happy": "Joy", "sad": "Sadness"}
    candidates = (info.display_name, info.original_name, info.unique_name)
    canonical = next(
        (
            aliases.get(candidate.strip().casefold(), candidate.strip())
            for candidate in candidates
            if candidate.strip()
            and aliases.get(candidate.strip().casefold(), candidate.strip()) in VIDEO_METRICS
        ),
        None,
    )
    if canonical == "Arousal" and not info.category.strip().casefold().startswith("fea("):
        return None
    return canonical


def _read_legacy_video_reports(root: Path) -> tuple[ParsedExport, ...]:
    reports = sorted(
        root.rglob("descriptive_statistics.csv"),
        key=lambda path: str(path).casefold(),
    )
    if not reports:
        raise ValueError(f"No accepted or legacy iMotions Video reports found under {root}")
    report_sections = tuple(
        (report, tuple(_legacy_report_means(report)))
        for report in reports
    )
    source_report_paths: dict[str, set[Path]] = {}
    for report, sections in report_sections:
        for _metric, _category, _unit, sources, _means in sections:
            for source in sources:
                source_report_paths.setdefault(source, set()).add(report)
    authoritative_source_ids = _legacy_authoritative_source_ids(root)
    channel_info = _legacy_channel_info(root)
    source_rows: OrderedDict[str, dict[str, str]] = OrderedDict()
    source_paths: dict[str, Path] = {}
    metric_info: dict[str, ColumnInfo] = {}
    for report, sections in report_sections:
        for metric, category, unit, sources, means in sections:
            canonical = _legacy_metric_name(metric, category)
            if canonical is None:
                continue
            original_field, channel_identifier = channel_info.get(
                canonical,
                (metric, metric),
            )
            metric_info[canonical] = ColumnInfo(
                unique_name=canonical,
                original_name=original_field,
                display_name=canonical,
                category=category,
                group="Emotion",
                unit=unit,
                provided_by=IMOTIONS_VIDEO_PROVIDER,
                channel_identifier=channel_identifier,
                scale_hint=(
                    "minus100_to_100"
                    if canonical in {"Valence", "Adaptive Valence", "Arousal"}
                    else "0_to_100"
                ),
            )
            for source, mean in zip(sources, means):
                source_key = _legacy_source_key(
                    root,
                    report,
                    source,
                    source_report_paths,
                    authoritative_source_ids,
                )
                row = source_rows.setdefault(source_key, {})
                previous = row.get(canonical, "")
                if previous and mean and previous != mean:
                    raise ValueError(
                        f"Contradictory legacy iMotions values for {source_key} {canonical}"
                    )
                if mean:
                    row[canonical] = mean
                source_paths.setdefault(source_key, report)
    if not source_rows:
        raise ValueError(f"No canonical iMotions Video measures found under {root}")
    return tuple(
        ParsedExport(
            source=source,
            path=source_paths[source],
            header=list(metric_info),
            info=dict(metric_info),
            rows=[row],
            speaker="",
            video=source,
        )
        for source, row in source_rows.items()
    )


def _legacy_source_key(
    root: Path,
    report: Path,
    source: str,
    source_report_paths: dict[str, set[Path]],
    authoritative_source_ids: set[str],
) -> str:
    if source in authoritative_source_ids or len(source_report_paths.get(source, ())) <= 1:
        return source
    speaker_root = report.parent.parent.parent
    try:
        prefix = speaker_root.relative_to(root).as_posix()
    except ValueError:
        prefix = speaker_root.name
    return f"{prefix}::{source}"


def _legacy_authoritative_source_ids(root: Path) -> set[str]:
    source_ids: set[str] = set()
    for path in sorted(root.rglob("source_manifest.json"), key=lambda item: str(item).casefold()):
        try:
            metadata = load_source_metadata(path)
        except (OSError, ValueError):
            continue
        source_ids.update(source.source_id for source in metadata.sources)
    for path in sorted(root.rglob("column_manifest.csv"), key=lambda item: str(item).casefold()):
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    continue
                source_id_field = next(
                    (
                        name
                        for name in reader.fieldnames
                        if re.sub(r"[^a-z0-9]", "", name.casefold()) == "sourceid"
                    ),
                    None,
                )
                if source_id_field is None:
                    continue
                for index, row in enumerate(reader):
                    if index >= 100_000:
                        raise ValueError(f"Imported column manifest has too many rows: {path}")
                    source_id = str(row.get(source_id_field, "")).strip()
                    if source_id:
                        source_ids.add(source_id)
        except (OSError, csv.Error):
            continue
    return source_ids


def _legacy_report_means(
    path: Path,
) -> Iterator[tuple[str, str, str, list[str], list[str]]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        rows = list(csv.reader(handle))
    index = 0
    while index < len(rows):
        if len(rows[index]) != 1 or not rows[index][0].strip():
            index += 1
            continue
        metric = rows[index][0].strip()
        index += 1
        section: list[list[str]] = []
        while index < len(rows) and rows[index]:
            section.append(rows[index])
            index += 1
        metadata = section[0] if section else []
        category = _section_value(metadata, "category")
        unit = _section_value(metadata, "unit")
        source_row = next((row for row in section if row and row[0] == "metric"), [])
        mean_row = next((row for row in section if row and row[0] == "mean"), [])
        if len(source_row) > 1 and len(mean_row) > 1:
            yield metric, category, unit, source_row[1:], mean_row[1:]


def _section_value(row: Sequence[str], key: str) -> str:
    try:
        return row[row.index(key) + 1]
    except (ValueError, IndexError):
        return ""


def _legacy_metric_name(metric: str, category: str) -> str | None:
    info = ColumnInfo(
        unique_name=metric,
        original_name=metric,
        display_name=metric,
        category=category,
        group="",
        unit="",
    )
    return _canonical_video_metric(info)


def _legacy_channel_info(root: Path) -> dict[str, tuple[str, str]]:
    channels: dict[str, tuple[str, str]] = {}
    for path in sorted(root.rglob("column_manifest.csv"), key=lambda item: str(item).casefold()):
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                continue
            normalized = {re.sub(r"[^a-z0-9]", "", name.casefold()): name for name in reader.fieldnames}
            statistic_field = normalized.get("statistic") or normalized.get("canonicalmeasure")
            source_field = normalized.get("sourcecolumn") or normalized.get("originalfield")
            channel_field = normalized.get("channelidentifier")
            if statistic_field is None or source_field is None:
                continue
            for row in reader:
                metric = str(row.get(statistic_field, "")).strip()
                if metric not in VIDEO_METRICS:
                    continue
                original = str(row.get(source_field, "")).strip() or metric
                channel = str(row.get(channel_field, "")).strip() if channel_field else original
                channels.setdefault(metric, (original, channel or original))
    return channels


class ImotionsRowSequence(Sequence[dict[str, str]]):
    """Repeatably stream normalized iMotions rows without retaining the CSV."""

    def __init__(self, path: Path, header: list[str], encoding: str, row_count: int) -> None:
        self.path = path
        self.header = header
        self.encoding = encoding
        self.row_count = row_count

    def __len__(self) -> int:
        return self.row_count

    def __iter__(self) -> Iterator[dict[str, str]]:
        with self.path.open("r", encoding=self.encoding, errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            header_seen = False
            after_data_marker = False
            for row in reader:
                if not header_seen:
                    if row and row[0].strip() == "#DATA":
                        after_data_marker = True
                        continue
                    if (
                        after_data_marker
                        and not is_blank_row(row)
                    ) or (
                        len(row) >= 2
                        and row[0].strip() == "Row"
                        and row[1].strip() == "Timestamp"
                    ):
                        header_seen = True
                    continue
                if is_blank_row(row) or (row and str(row[0]).strip().startswith("#")):
                    continue
                if not is_imotions_data_row(row):
                    break
                yield row_to_mapping(self.header, row)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return list(self)[index]
        normalized = index if index >= 0 else self.row_count + index
        if normalized < 0:
            raise IndexError(index)
        for row_index, row in enumerate(self):
            if row_index == normalized:
                return row
        raise IndexError(index)


def inspect_imotions_csv(path: Path, encoding: str) -> tuple[list[list[str]], list[str], int]:
    """Read only the small metadata preamble and count usable data rows."""

    metadata_rows: list[list[str]] = []
    raw_header: list[str] | None = None
    data_count = 0
    after_data_marker = False
    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        for row in csv.reader(handle):
            if raw_header is None:
                if row and row[0].strip() == "#DATA":
                    after_data_marker = True
                    continue
                is_standard_header = (
                    len(row) >= 2
                    and row[0].strip() == "Row"
                    and row[1].strip() == "Timestamp"
                )
                if is_standard_header or (after_data_marker and not is_blank_row(row)):
                    raw_header = list(row)
                    continue
                metadata_rows.append(list(row))
                continue
            if is_blank_row(row) or (row and str(row[0]).strip().startswith("#")):
                continue
            if not is_imotions_data_row(row):
                break
            data_count += 1
    if raw_header is None:
        raise ValueError(f"Could not find an iMotions data header in {path}")
    return metadata_rows, raw_header, data_count


def imotions_speaker_name(path: Path, input_root: Path | None = None) -> str:
    """Return the speaker folder for direct and run-level iMotions inputs."""

    generic_export_folders = {"sensordata", "rawdata", "export", "exports"}

    def folder_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.casefold())

    if input_root is not None:
        try:
            relative_parent = path.parent.relative_to(input_root)
            if relative_parent.parts:
                candidate = relative_parent.parts[0]
                if folder_key(candidate) not in generic_export_folders:
                    return safe_filename(candidate)
                root_candidate = input_root.name
                if folder_key(root_candidate) in generic_export_folders:
                    root_candidate = input_root.parent.name
                return safe_filename(root_candidate)
        except ValueError:
            pass
    candidate = path.parent.name
    if input_root is not None and folder_key(candidate) in generic_export_folders:
        candidate = input_root.name
        if folder_key(candidate) in generic_export_folders:
            candidate = input_root.parent.name
    return safe_filename(candidate)


def find_header_index(rows: Sequence[Sequence[str]], path: Path) -> int:
    """Find the real data header, accepting either #DATA or Row/Timestamp exports."""

    for index, row in enumerate(rows):
        if row and row[0].strip() == "#DATA":
            for candidate_index in range(index + 1, len(rows)):
                candidate = rows[candidate_index]
                if len(candidate) >= 2 and candidate[0].strip() == "Row" and candidate[1].strip() == "Timestamp":
                    return candidate_index
            if index + 1 < len(rows):
                return index + 1
            raise ValueError(f"#DATA marker in {path} is not followed by a header row.")

    for index, row in enumerate(rows):
        if len(row) >= 2 and row[0].strip() == "Row" and row[1].strip() == "Timestamp":
            return index

    raise ValueError(f"Could not find an iMotions data header in {path}")


def build_column_info(
    metadata_rows: Sequence[Sequence[str]],
    raw_header: Sequence[str],
    unique_header: Sequence[str],
) -> dict[str, ColumnInfo]:
    """Build per-column metadata aligned to the data header."""

    n = len(raw_header)
    meta = {
        "display_name": metadata_values(metadata_rows, "#Display name", n),
        "category": metadata_values(metadata_rows, "#Category", n),
        "group": metadata_values(metadata_rows, "#Group", n),
        "unit": metadata_values(metadata_rows, "#Unit", n),
        "description": metadata_values(metadata_rows, "#Description", n),
        "device": metadata_values(metadata_rows, "#Device", n),
        "provided_by": metadata_values(metadata_rows, "#Provided By", n),
        "channel_identifier": metadata_values(metadata_rows, "#Channel identifier", n),
    }

    info: dict[str, ColumnInfo] = {}
    for index, unique_name in enumerate(unique_header):
        info[unique_name] = ColumnInfo(
            unique_name=unique_name,
            original_name=str(raw_header[index]).strip() if index < len(raw_header) else unique_name,
            display_name=value_at(meta["display_name"], index),
            category=value_at(meta["category"], index),
            group=value_at(meta["group"], index),
            unit=value_at(meta["unit"], index),
            description=value_at(meta["description"], index),
            device=value_at(meta["device"], index),
            provided_by=value_at(meta["provided_by"], index),
            channel_identifier=value_at(meta["channel_identifier"], index),
            scale_hint=imotions_scale_hint(
                category=value_at(meta["category"], index),
                unit=value_at(meta["unit"], index),
                channel_identifier=value_at(meta["channel_identifier"], index),
                display_name=value_at(meta["display_name"], index),
                original_name=str(raw_header[index]).strip() if index < len(raw_header) else unique_name,
            ),
        )
    return info


def imotions_scale_hint(
    *,
    category: str,
    unit: str,
    channel_identifier: str,
    display_name: str,
    original_name: str,
) -> str:
    """Mark iMotions AFFDEX score columns that should not be auto-scaled."""

    text = f"{category} {channel_identifier} {display_name} {original_name}".lower()
    if "valence" in text:
        return "minus100_to_100"

    label = (display_name or original_name).strip()
    if category.strip().lower() == "fea(emotions)" and label in CORE_EMOTION_ORDER:
        return ""

    if category.strip().lower().startswith("fea(") and unit.strip().lower() == "index":
        return "0_to_100"
    return ""


def metadata_values(rows: Sequence[Sequence[str]], key: str, n_header_cols: int) -> list[str]:
    """Return metadata values aligned with the data header length."""

    found = next((row for row in rows if row and row[0].strip() == key), None)
    if not found:
        return [""] * n_header_cols

    values = [str(value).strip() for value in found[1:]]
    if len(values) == n_header_cols:
        return values[:n_header_cols]
    if len(values) == n_header_cols - 1:
        return [""] + values
    return (values + [""] * n_header_cols)[:n_header_cols]


def make_unique(names: Iterable[str]) -> list[str]:
    """Make duplicate header names unique while preserving the first occurrence."""

    seen: dict[str, int] = {}
    out: list[str] = []
    for raw in names:
        name = str(raw).strip() or "Unnamed"
        count = seen.get(name, 0)
        out.append(name if count == 0 else f"{name}.{count}")
        seen[name] = count + 1
    return out


def value_at(values: Sequence[str], index: int) -> str:
    return values[index] if index < len(values) else ""


def row_to_mapping(header: Sequence[str], row: Sequence[str]) -> dict[str, str]:
    return {name: row[index] if index < len(row) else "" for index, name in enumerate(header) if name}


def is_blank_row(row: Sequence[object]) -> bool:
    return all(cell is None or str(cell).strip() == "" for cell in row)


def is_imotions_data_row(row: Sequence[object]) -> bool:
    """Reject comments and footer summaries while accepting data after blank lines."""

    if len(row) < 2 or is_blank_row(row) or str(row[0]).strip().startswith("#"):
        return False
    try:
        float(str(row[0]).strip())
        float(str(row[1]).strip())
    except (TypeError, ValueError):
        return False
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create folder-level iMotions histograms and post-processing reports.")
    parser.add_argument("input_folder", type=Path, help="Folder containing direct iMotions CSV exports.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Optional alternate report root. Defaults to analysis/output.",
    )
    parser.add_argument("--no-graphs", action="store_true", help="Skip SVG histogram graph generation.")
    parser.add_argument(
        "--logscale",
        action="store_true",
        help="Also write log10(count + 1) histogram CSVs and graphs under other_findings.",
    )
    parser.add_argument("--include-landmarks", action="store_true", help="Include raw landmark feature columns in histograms.")
    parser.add_argument("--include-timing", action="store_true", help="Include timing and counter columns in histograms.")
    parser.add_argument("--exclude-geometry", action="store_true", help="Exclude geometry columns from histogram output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = analyse_imotions_folder(
        args.input_folder,
        output_root=args.output_root,
        write_graphs=not args.no_graphs,
        include_logscale=args.logscale,
        include_landmarks=args.include_landmarks,
        include_timing=args.include_timing,
        exclude_geometry=args.exclude_geometry,
    )
    print(f"Output folder: {result.output_dir}")
    print(f"Emotion reports: {result.domain_output_dirs.get('emotion', result.output_dir)}")
    print(f"Raw reports: {result.domain_output_dirs.get('raw', '')}")
    print("Layout: emotion/<speaker-or-run>/<video> and raw/<speaker-or-run>/<video>, each with combined")
    print(f"Report files: {len(result.histogram_paths)} histogram CSV/XLSX outputs")
    print(f"Graphs: {len(result.graph_paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
