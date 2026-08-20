"""Read imported transcript construct results without invoking text processing."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from analysis.combined_summary import (
    TEXT_CONSTRUCTS,
    TextConstructSummary,
    resolve_speaker,
)


class TextResultsError(ValueError):
    """Raised when an imported transcript summary violates its data contract."""


@dataclass(frozen=True)
class TextResultsDiscovery:
    summary_path: Path
    summaries: tuple[TextConstructSummary, ...]


_IDENTITY_COLUMNS = (
    "Country",
    "Speaker",
    "Speaker ID",
    "Videos",
    "Valid segments",
    "RockSteady terms",
)
_SENTIMENT_ALIASES = {
    "Positive Sentiment": ("Positive Sentiment", "Positive valence"),
    "Negative Sentiment": ("Negative Sentiment", "Negative valence"),
}
_REQUIRED_COLUMNS = frozenset((*_IDENTITY_COLUMNS, *TEXT_CONSTRUCTS[2:]))
_CONSTRUCT_RANGES = {
    "Positive Sentiment": (0.0, 1.0),
    "Negative Sentiment": (0.0, 1.0),
    "Arousal / Activation": (-1.0, 1.0),
    "Dominance / Power": (-1.0, 1.0),
    "Affiliation / Social orientation": (-1.0, 1.0),
}


def _candidate_header(path: Path) -> tuple[str, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return tuple(next(csv.reader(handle), ()))
    except (OSError, UnicodeError, csv.Error):
        return ()


def _compatible_header(header: tuple[str, ...] | list[str]) -> bool:
    available = set(header)
    return _REQUIRED_COLUMNS.issubset(available) and all(
        any(alias in available for alias in aliases)
        for aliases in _SENTIMENT_ALIASES.values()
    )


def _find_summary(root: Path) -> Path:
    candidates = [
        path.resolve()
        for path in root.rglob("speaker_level_summary.csv")
        if _compatible_header(_candidate_header(path))
    ]
    if not candidates:
        raise TextResultsError(
            "No compatible multimodal/speaker_level_summary.csv was found in the text results folder"
        )
    if len(candidates) > 1:
        listed = ", ".join(str(path) for path in sorted(candidates))
        raise TextResultsError(f"Multiple compatible text speaker summaries were found: {listed}")
    return candidates[0]


def _required_integer(row: dict[str, str], column: str, row_number: int) -> int:
    try:
        number = int(str(row.get(column, "")).strip())
    except ValueError as exc:
        raise TextResultsError(f"Row {row_number}: {column} must be a non-negative integer") from exc
    if number < 0:
        raise TextResultsError(f"Row {row_number}: {column} must be a non-negative integer")
    return number


def _construct_value(
    row: dict[str, str], source_column: str, construct: str, row_number: int
) -> float | None:
    raw = str(row.get(source_column, "")).strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise TextResultsError(
            f"Row {row_number}: {source_column} must be numeric or blank"
        ) from exc
    lower, upper = _CONSTRUCT_RANGES[construct]
    if not math.isfinite(value) or value < lower or value > upper:
        raise TextResultsError(
            f"Row {row_number}: {source_column} must be between {lower:g} and {upper:g}"
        )
    return value


def discover_text_results(root: str | Path) -> TextResultsDiscovery:
    """Validate and load the speaker-level five-construct transcript summary."""

    source_root = Path(root).expanduser().resolve()
    if not source_root.is_dir():
        raise TextResultsError(f"Text results folder does not exist: {source_root}")
    summary_path = _find_summary(source_root)
    summaries: dict[str, TextConstructSummary] = {}
    try:
        with summary_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not _compatible_header(reader.fieldnames):
                raise TextResultsError("Text speaker summary is missing required columns")
            for row_number, row in enumerate(reader, start=2):
                speaker_label = str(row.get("Speaker", "")).strip()
                speaker_reference = str(row.get("Speaker ID", "")).strip()
                if not speaker_label or not speaker_reference:
                    raise TextResultsError(f"Row {row_number}: Speaker and Speaker ID are required")
                try:
                    speaker = resolve_speaker(speaker_label)
                except ValueError as exc:
                    raise TextResultsError(f"Row {row_number}: {exc}") from exc
                if speaker.speaker_id in summaries:
                    raise TextResultsError(f"Duplicate text summary for {speaker.display_name}")
                country = str(row.get("Country", "")).strip()
                _required_integer(row, "Videos", row_number)
                _required_integer(row, "Valid segments", row_number)
                _required_integer(row, "RockSteady terms", row_number)
                constructs: dict[str, float | None] = {}
                for construct in TEXT_CONSTRUCTS:
                    aliases = _SENTIMENT_ALIASES.get(construct, (construct,))
                    source_column = next(alias for alias in aliases if alias in reader.fieldnames)
                    constructs[construct] = _construct_value(
                        row, source_column, construct, row_number
                    )
                if not any(value is not None for value in constructs.values()):
                    raise TextResultsError(
                        f"Row {row_number}: at least one transcript construct must be available"
                    )
                summaries[speaker.speaker_id] = TextConstructSummary(
                    speaker_id=speaker.speaker_id,
                    display_name=speaker.display_name,
                    country=country,
                    constructs=constructs,
                    source_path=summary_path,
                )
    except (OSError, UnicodeError, csv.Error) as exc:
        raise TextResultsError(f"Could not read text speaker summary: {summary_path}") from exc
    if not summaries:
        raise TextResultsError("Text speaker summary contains no speaker rows")
    ordered = tuple(summaries.values())
    return TextResultsDiscovery(summary_path, ordered)
