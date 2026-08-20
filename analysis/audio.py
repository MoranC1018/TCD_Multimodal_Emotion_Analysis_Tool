from __future__ import annotations

import csv
import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from analysis.histograms import (
    AnalysisResult,
    ColumnInfo,
    ParsedExport,
    analyse_domain_split_parsed_exports,
    analysis_root,
)


AUDIO_ANALYSIS_FILENAME = "audio_analysis.csv"
OPENSMILE_FEATURES_FILENAME = "opensmile_features.csv"

OPENSMILE_METADATA_COLUMNS = {
    "Row",
    "WindowStart",
    "WindowEnd",
    "name",
    "frameTime",
}

CATEGORICAL_COLUMNS = [
    "Anger",
    "Contempt",
    "Disgust",
    "Fear",
    "Joy",
    "Sadness",
    "Surprise",
    "Neutral",
    "Other",
]

DIMENSIONAL_COLUMNS = [
    "Arousal",
    "Dominance",
    "Valence",
]

AUDIO_EXPORT_HEADER = ["Row", "Timestamp", *CATEGORICAL_COLUMNS, *DIMENSIONAL_COLUMNS]


@dataclass(frozen=True)
class AudioAnalysisCsv:
    metadata: dict[str, str]
    rows: Sequence[dict[str, str]]
    header: list[str]


def analyse_audio_folder(
    input_folder: str | Path,
    output_root: str | Path | None = None,
    *,
    write_graphs: bool = True,
    include_logscale: bool = False,
) -> AnalysisResult:
    """Run analysis reports for an audio analysis output folder."""

    input_dir = resolve_audio_input_folder(input_folder)
    if not input_dir.exists() or not input_dir.is_dir():
        raise NotADirectoryError(f"Input folder does not exist: {input_dir}")

    selected_csvs, opensmile_csvs, discovery_log = discover_audio_analysis_inputs(input_dir)
    if not selected_csvs and not opensmile_csvs:
        raise ValueError(missing_audio_analysis_message(input_dir))

    exports = [read_audio_analysis_export(path) for path in selected_csvs]
    exports.extend(read_opensmile_features_export(path) for path in opensmile_csvs)
    return analyse_domain_split_parsed_exports(
        input_dir=input_dir,
        output_root=output_root,
        exports=exports,
        discovery_log=discovery_log,
        write_graphs=write_graphs,
        include_logscale=include_logscale,
        include_landmarks=False,
        include_timing=False,
        exclude_geometry=False,
    )


def default_audio_input_root() -> Path:
    return analysis_root() / "audio_outputs"


def resolve_audio_input_folder(input_folder: str | Path) -> Path:
    candidate = Path(input_folder)
    if candidate.is_absolute() or candidate.exists():
        return candidate.expanduser().resolve()
    return (default_audio_input_root() / candidate).resolve()


def discover_audio_analysis_inputs(input_dir: Path) -> tuple[list[Path], list[Path], list[str]]:
    analysis_paths = sorted(input_dir.rglob(AUDIO_ANALYSIS_FILENAME), key=lambda item: str(item).casefold())
    opensmile_paths = sorted(input_dir.rglob(OPENSMILE_FEATURES_FILENAME), key=lambda item: str(item).casefold())
    log_lines = [f"Selected {path.relative_to(input_dir)}." for path in analysis_paths]
    log_lines.extend(f"Selected {path.relative_to(input_dir)}." for path in opensmile_paths)
    return analysis_paths, opensmile_paths, log_lines


def missing_audio_analysis_message(input_dir: Path) -> str:
    manifest = input_dir / "audio_analysis_manifest.csv"
    if manifest.exists():
        return (
            f"No {AUDIO_ANALYSIS_FILENAME} files found under {input_dir}. "
            "A batch manifest exists there, but the per-video audio output files are missing. "
            "Rerun the audio extraction stage for this input folder, then run analysis again."
        )
    return (
        f"No {AUDIO_ANALYSIS_FILENAME} or {OPENSMILE_FEATURES_FILENAME} files found under {input_dir}. "
        "Point this command at a raw audio extraction output folder, not an already-postprocessed report folder."
    )


def read_audio_analysis_export(path: Path) -> ParsedExport:
    """Convert one audio_analysis.csv into the parsed-export shape used downstream.

    The extraction stage keeps model probabilities as raw 0-1 values. This
    adapter scales categorical probabilities to 0-100 so the existing histogram
    table code can use the same bins as iMotions-style emotion scores. Dimensional
    valence is mapped from 0-1 to -100..100 to match the existing valence table.
    """

    path = path.expanduser().resolve()
    audio_csv = read_audio_analysis_csv(path)
    source_rows = audio_csv.rows

    speaker, video = audio_source_parts(path, source_rows, audio_csv.metadata)

    return ParsedExport(
        source=audio_source_name_from_parts(speaker, video),
        path=path,
        header=AUDIO_EXPORT_HEADER.copy(),
        info=build_audio_column_info(audio_csv.metadata),
        rows=ConvertedAudioRowSequence(source_rows),
        speaker=speaker,
        video=video,
    )


def read_opensmile_features_export(path: Path) -> ParsedExport:
    """Convert opensmile_features.csv into raw acoustic descriptor reports."""

    path = path.expanduser().resolve()
    rows, raw_header = read_plain_csv_dicts(path)
    metadata = {}
    audio_sidecar = path.with_name(AUDIO_ANALYSIS_FILENAME)
    if audio_sidecar.exists():
        metadata = read_audio_analysis_csv(audio_sidecar).metadata

    numeric_columns: set[str] = set()
    candidate_columns = [column for column in raw_header if column not in OPENSMILE_METADATA_COLUMNS]
    for row in rows:
        for column in candidate_columns:
            if column not in numeric_columns and to_float(row.get(column)) is not None:
                numeric_columns.add(column)
        if len(numeric_columns) == len(candidate_columns):
            break
    feature_header = [column for column in candidate_columns if column in numeric_columns]

    speaker, video = audio_source_parts(path, rows, metadata)
    opensmile_video = f"{video}__opensmile_features" if video else "opensmile_features"
    return ParsedExport(
        source=audio_source_name_from_parts(speaker, opensmile_video),
        path=path,
        header=feature_header,
        info=build_opensmile_column_info(feature_header),
        rows=rows,
        speaker=speaker,
        video=opensmile_video,
    )


def read_plain_csv_dicts(path: Path) -> tuple[Sequence[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        first_line = handle.readline()
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","

    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        raw_header = next(reader, None)
        row_count = sum(1 for row in reader if any(str(value).strip() for value in row))

    if raw_header is None:
        return [], []

    header = [(column or "").strip() for column in raw_header]
    return PlainCsvRowSequence(path, delimiter, header, row_count), header


class PlainCsvRowSequence(Sequence[dict[str, str]]):
    """Repeatably stream wide OpenSMILE CSV rows from disk."""

    def __init__(
        self,
        path: Path,
        delimiter: str,
        header: list[str],
        row_count: int,
        *,
        header_line_index: int = 0,
    ) -> None:
        self.path = path
        self.delimiter = delimiter
        self.header = header
        self.row_count = row_count
        self.header_line_index = header_line_index

    def __len__(self) -> int:
        return self.row_count

    def __iter__(self) -> Iterator[dict[str, str]]:
        with self.path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.reader(handle, delimiter=self.delimiter)
            for _ in range(self.header_line_index + 1):
                next(reader, None)
            for raw_row in reader:
                if not any(str(value).strip() for value in raw_row):
                    continue
                padded = raw_row + [""] * max(0, len(self.header) - len(raw_row))
                yield {
                    column: padded[index] if index < len(padded) else ""
                    for index, column in enumerate(self.header)
                }

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


class ConvertedAudioRowSequence(Sequence[dict[str, str]]):
    """Transform audio emotion rows on demand without retaining a second copy."""

    def __init__(self, source_rows: Sequence[dict[str, str]]) -> None:
        self.source_rows = source_rows

    def __len__(self) -> int:
        return len(self.source_rows)

    def __iter__(self) -> Iterator[dict[str, str]]:
        for index, row in enumerate(self.source_rows, start=1):
            yield converted_audio_row(row, index)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return list(self)[index]
        normalized = index if index >= 0 else len(self) + index
        if normalized < 0 or normalized >= len(self):
            raise IndexError(index)
        return converted_audio_row(self.source_rows[normalized], normalized + 1)


def converted_audio_row(row: dict[str, str], index: int) -> dict[str, str]:
    """Map one model-output row into the shared Analysis column contract."""

    return {
        "Row": clean_integer(row.get("WindowIndex")) or str(index),
        "Timestamp": seconds_to_milliseconds(row.get("StartSeconds")),
        "Anger": probability_to_score(row.get("Anger")),
        "Contempt": probability_to_score(row.get("Contempt")),
        "Disgust": probability_to_score(row.get("Disgust")),
        "Fear": probability_to_score(row.get("Fear")),
        "Joy": probability_to_score(row.get("Happiness")),
        "Sadness": probability_to_score(row.get("Sadness")),
        "Surprise": probability_to_score(row.get("Surprise")),
        "Neutral": probability_to_score(row.get("Neutral")),
        "Other": probability_to_score(row.get("Other")),
        "Arousal": probability_to_score(row.get("Arousal")),
        "Dominance": probability_to_score(row.get("Dominance")),
        "Valence": valence_to_signed_score(row.get("Valence")),
    }


def read_audio_analysis_csv(path: Path) -> AudioAnalysisCsv:
    """Inspect compact or legacy audio CSVs and stream their data rows."""

    metadata: dict[str, str] = {}
    header: list[str] = []
    header_line_index: int | None = None
    row_count = 0
    after_data_marker = False
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for line_index, row in enumerate(csv.reader(handle)):
            if header_line_index is None:
                if row and row[0] == "#DATA":
                    after_data_marker = True
                    continue
                if after_data_marker:
                    if not any(str(value).strip() for value in row):
                        continue
                    header = list(row)
                    header_line_index = line_index
                    continue
                if line_index == 0 and row and not row[0].startswith("#"):
                    header = list(row)
                    header_line_index = line_index
                    continue
                if row and row[0].startswith("#") and len(row) > 1:
                    metadata[row[0].lstrip("#")] = row[1]
                continue
            if any(str(value).strip() for value in row):
                row_count += 1

    if header_line_index is None:
        return AudioAnalysisCsv(metadata=metadata, rows=[], header=[])
    rows = PlainCsvRowSequence(
        path,
        ",",
        header,
        row_count,
        header_line_index=header_line_index,
    )
    return AudioAnalysisCsv(metadata=metadata, rows=rows, header=header)


def build_audio_column_info(metadata: dict[str, str] | None = None) -> dict[str, ColumnInfo]:
    metadata = metadata or {}
    categorical_provider = model_provider_label(
        metadata.get("ModelCategoricalName", ""),
        metadata.get("ModelCategoricalVersion", ""),
        metadata.get("CategoricalModelAvailable", ""),
        metadata.get("ModelErrors", ""),
    )
    dimensional_provider = model_provider_label(
        metadata.get("ModelDimensionalName", ""),
        metadata.get("ModelDimensionalVersion", ""),
        metadata.get("DimensionalModelAvailable", ""),
        metadata.get("ModelErrors", ""),
    )
    info = {
        "Row": ColumnInfo(
            unique_name="Row",
            original_name="Row",
            display_name="Row",
            category="Timestamp",
            group="Counter",
            unit="Index",
            channel_identifier="Row",
        ),
        "Timestamp": ColumnInfo(
            unique_name="Timestamp",
            original_name="Timestamp",
            display_name="Timestamp",
            category="Timestamp",
            group="Timestamp",
            unit="Millisecond",
            channel_identifier="Timestamp",
        ),
    }

    for column in CATEGORICAL_COLUMNS:
        info[column] = ColumnInfo(
            unique_name=column,
            original_name=column,
            display_name=column,
            category="AUDIO(Categorical Emotion)",
            group="Emotion",
            unit="Index",
            description=f"Audio model probability for {column}, scaled from 0-1 to 0-100.",
            provided_by=categorical_provider,
            channel_identifier=f"AUDIO_Emotion_{column}",
            scale_hint="0_to_100",
        )

    dimensional_scales = {
        "Arousal": (
            "Audio model probability for Arousal, scaled from source 0-1 to output 0-100.",
            "0_to_100",
        ),
        "Dominance": (
            "Audio model probability for Dominance, scaled from source 0-1 to output 0-100.",
            "0_to_100",
        ),
        "Valence": (
            "Audio model value for Valence, scaled from source 0-1 to output -100 to 100.",
            "minus100_to_100",
        ),
    }
    for column in DIMENSIONAL_COLUMNS:
        description, scale_hint = dimensional_scales[column]
        info[column] = ColumnInfo(
            unique_name=column,
            original_name=column,
            display_name=column,
            category="AUDIO(Dimensional Affect)",
            group="Affect",
            unit="Index",
            description=description,
            provided_by=dimensional_provider,
            channel_identifier=f"AUDIO_Affect_{column}",
            scale_hint=scale_hint,
        )

    return info


def build_opensmile_column_info(header: list[str]) -> dict[str, ColumnInfo]:
    info: dict[str, ColumnInfo] = {}
    for column in header:
        info[column] = ColumnInfo(
            unique_name=column,
            original_name=column,
            display_name=column,
            category="AUDIO(OpenSMILE Feature)",
            group=opensmile_feature_group(column),
            unit="OpenSMILE raw",
            description=f"Raw OpenSMILE acoustic feature column `{column}`.",
            provided_by="OpenSMILE",
            channel_identifier=f"OpenSMILE_{column}",
            scale_hint="raw_acoustic",
        )
    return info


def opensmile_feature_group(column: str) -> str:
    text = column.casefold()
    if "f0" in text or "pitch" in text:
        return "Pitch"
    if "loudness" in text or "energy" in text or "intensity" in text:
        return "Loudness/Energy"
    if "jitter" in text or "shimmer" in text or "hnr" in text:
        return "Voice Quality"
    if "mfcc" in text or "spectral" in text:
        return "Spectral"
    return "Acoustic Feature"


def model_provider_label(name: str, version: str, available: str, errors: str) -> str:
    parts = []
    if name:
        parts.append(f"{name}@{version}" if version else name)
    if available:
        parts.append(f"available={available}")
    return "; ".join(parts)


def audio_source_name(path: Path, rows: Sequence[dict[str, str]], metadata: dict[str, str] | None = None) -> str:
    speaker, video = audio_source_parts(path, rows, metadata)
    return audio_source_name_from_parts(speaker, video)


def audio_source_name_from_parts(speaker: str, video: str) -> str:
    return "__".join(part for part in [safe_label(speaker), safe_label(video)] if part)


def audio_source_parts(
    path: Path,
    rows: Sequence[dict[str, str]],
    metadata: dict[str, str] | None = None,
) -> tuple[str, str]:
    metadata = metadata or {}
    speaker = metadata.get("SpeakerName", "").strip()
    title = metadata.get("VideoTitle", "").strip()
    youtube_id = metadata.get("YoutubeID", "").strip()
    if speaker or title or youtube_id:
        video = f"{title}_[{youtube_id}]" if youtube_id else title
        return speaker, video

    if rows:
        speaker = rows[0].get("SpeakerName", "").strip()
        title = rows[0].get("VideoTitle", "").strip()
        youtube_id = rows[0].get("YoutubeID", "").strip()
        if speaker or title or youtube_id:
            video = f"{title}_[{youtube_id}]" if youtube_id else title
            return speaker, video

    if path.parent.parent != path.parent:
        return path.parent.parent.name, path.parent.name
    return "", path.parent.name or path.stem


def safe_label(value: str) -> str:
    cleaned = re.sub(r"\s+", "_", value.strip())
    cleaned = re.sub(r"[^\w.\-\[\]]+", "_", cleaned, flags=re.UNICODE)
    cleaned = cleaned.strip("._")
    return cleaned or "audio_source"


def seconds_to_milliseconds(value: str | None) -> str:
    number = to_float(value)
    if number is None:
        return ""
    return format_number(number * 1000)


def probability_to_score(value: str | None) -> str:
    number = to_float(value)
    if number is None:
        return ""
    return format_number(number * 100)


def valence_to_signed_score(value: str | None) -> str:
    number = to_float(value)
    if number is None:
        return ""
    if 0 <= number <= 1:
        number = (number * 200) - 100
    return format_number(number)


def clean_integer(value: str | None) -> str:
    number = to_float(value)
    if number is None:
        return ""
    return str(int(number))


def to_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def format_number(value: float) -> str:
    if abs(value) < 0.0000005:
        value = 0
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Postprocess audio_analysis.csv outputs.")
    parser.add_argument(
        "input_folder",
        type=Path,
        help="Audio output folder, or a folder name under analysis/audio_outputs.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Optional alternate report root. Defaults to analysis/output.",
    )
    parser.add_argument("--no-graphs", action="store_true", help="Skip SVG histogram graph generation.")
    parser.add_argument("--logscale", action="store_true", help="Also write log-scale histogram outputs.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = analyse_audio_folder(
        args.input_folder,
        output_root=args.output_root,
        write_graphs=not args.no_graphs,
        include_logscale=args.logscale,
    )
    print(f"Output folder: {result.output_dir}")
    print(f"Emotion reports: {result.domain_output_dirs.get('emotion', result.output_dir)}")
    print(f"Raw reports: {result.domain_output_dirs.get('raw', '')}")
    print("Layout: emotion/<run>/<speaker>/<video> and raw/<run>/<speaker>/<video>, each with combined")
    print(f"Report files: {len(result.histogram_paths)} histogram CSV/XLSX outputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
