"""Shared CSV/DOCX source catalog parsing for procurement workflows."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from procurement.video_sampling import run_docx_extractions
from procurement.input_limits import DocxPackageError, read_docx_snapshot


POOLED_SPEAKER_LABEL = "Pooled (no speaker)"
IGNORED_HEADER_KEYS = frozenset({"uploaddate", "engagement", "dateaccessed", "length"})
MAX_CATALOG_CSV_BYTES = 8 * 1024 * 1024
MAX_CATALOG_ROWS = 100_000
MAX_CATALOG_COLUMNS = 1_024
MAX_CATALOG_CELL_CHARS = 1_048_576


@dataclass(frozen=True)
class CatalogSource:
    """One immutable catalog row in user-supplied order."""

    source_id: str
    link: str
    resolved_link: str
    source_kind: str
    speaker: str
    metadata: dict[str, str]
    row_number: int
    youtube_id: str = ""

    @property
    def speaker_display(self) -> str:
        return self.speaker or POOLED_SPEAKER_LABEL


@dataclass(frozen=True)
class SourceCatalog:
    """A format-independent source catalog."""

    path: Path
    format: str
    sha256: str
    original_headers: tuple[str, ...]
    ignored_headers: tuple[str, ...]
    metadata_headers: tuple[str, ...]
    sources: tuple[CatalogSource, ...]


def normalise_header(value: object) -> str:
    """Return a Unicode-normalized lookup key for one user header."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"[\s_-]+", "", normalized)


def display_header(value: object) -> str:
    """Preserve a human-facing label exactly apart from outer whitespace."""

    return str(value or "").strip()


def read_catalog(path: Path | str, *, expected_sha256: str = "") -> SourceCatalog:
    """Parse one bounded CSV or DOCX catalog into the shared row model."""

    catalog_path = Path(path).expanduser().resolve()
    suffix = catalog_path.suffix.casefold()
    if suffix not in {".csv", ".docx"}:
        raise ValueError("Source catalogs must be CSV or DOCX files.")
    if not catalog_path.exists() or not catalog_path.is_file():
        raise FileNotFoundError(f"Source catalog does not exist: {catalog_path}")

    if suffix == ".csv":
        snapshot = _read_csv_snapshot(catalog_path)
        tables = [_read_csv_table(catalog_path, snapshot)]
    else:
        try:
            snapshot = read_docx_snapshot(catalog_path)
        except DocxPackageError as exc:
            raise RuntimeError(f"Could not open DOCX as a Word package: {catalog_path}") from exc
        tables = _read_docx_tables(catalog_path, snapshot)
    catalog_sha256 = hashlib.sha256(snapshot).hexdigest()
    if expected_sha256 and catalog_sha256 != str(expected_sha256).strip().casefold():
        raise ValueError("Source catalog changed since it was scanned; scan it again before processing.")

    original_headers: list[str] = []
    ignored_headers: list[str] = []
    metadata_headers: list[str] = []
    sources: list[CatalogSource] = []
    for headers, rows in tables:
        if not headers and not rows:
            continue
        header_map = _header_map(headers)
        if "link" not in header_map:
            raise ValueError("Source catalog is missing the required Link header.")
        _extend_unique(original_headers, (display_header(header) for header in headers if display_header(header)))
        _extend_unique(
            ignored_headers,
            (display_header(headers[index]) for key, index in header_map.items() if key in IGNORED_HEADER_KEYS),
        )
        table_metadata_columns = [
            (display_header(headers[index]), index)
            for key, index in header_map.items()
            if key not in {"link", "speaker", *IGNORED_HEADER_KEYS}
        ]
        table_metadata_headers = [label for label, _index in table_metadata_columns]
        _extend_unique(metadata_headers, table_metadata_headers)
        for row_number, values in rows:
            if not any(str(value or "").strip() for value in values):
                continue
            link = _cell(values, header_map["link"])
            if not link:
                raise ValueError(f"Catalog row {row_number} has a blank Link value.")
            speaker = _cell(values, header_map["speaker"]) if "speaker" in header_map else ""
            metadata = {
                label: value
                for label, index in table_metadata_columns
                if (value := _cell(values, index))
            }
            source_kind, resolved_link, youtube_id = _resolve_link(link, catalog_path.parent)
            sources.append(
                CatalogSource(
                    source_id=f"source-{len(sources) + 1:04d}",
                    link=link,
                    resolved_link=resolved_link,
                    source_kind=source_kind,
                    speaker=" ".join(speaker.split()),
                    metadata=metadata,
                    row_number=row_number,
                    youtube_id=youtube_id,
                )
            )

    if not sources:
        raise ValueError("Source catalog contains no nonblank Link rows.")
    return SourceCatalog(
        path=catalog_path,
        format=suffix.lstrip("."),
        sha256=catalog_sha256,
        original_headers=tuple(original_headers),
        ignored_headers=tuple(ignored_headers),
        metadata_headers=tuple(metadata_headers),
        sources=tuple(sources),
    )


def _read_csv_snapshot(path: Path) -> bytes:
    with path.open("rb") as handle:
        snapshot = handle.read(MAX_CATALOG_CSV_BYTES + 1)
    if len(snapshot) > MAX_CATALOG_CSV_BYTES:
        raise ValueError(f"Catalog CSV exceeds {MAX_CATALOG_CSV_BYTES} bytes: {path}")
    return snapshot


def _read_csv_table(path: Path, snapshot: bytes) -> tuple[list[str], list[tuple[int, list[str]]]]:
    try:
        text = snapshot.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Catalog CSV must be UTF-8: {path}") from exc
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as exc:
        raise ValueError(f"Could not parse catalog CSV: {path}") from exc
    if not rows:
        raise ValueError("Source catalog is empty and has no Link header.")
    if len(rows) - 1 > MAX_CATALOG_ROWS:
        raise ValueError(f"Catalog contains more than {MAX_CATALOG_ROWS} data rows: {path}")
    _validate_table_limits(rows, path)
    return rows[0], [(row_number, row) for row_number, row in enumerate(rows[1:], start=2)]


def _read_docx_tables(path: Path, snapshot: bytes) -> list[tuple[list[str], list[tuple[int, list[str]]]]]:
    document = run_docx_extractions.open_docx_snapshot(snapshot, path)
    tables: list[tuple[list[str], list[tuple[int, list[str]]]]] = []
    for table in document.tables:
        rows = list(table.rows)
        if not rows:
            continue
        headers = [cell.text for cell in rows[0].cells]
        _validate_table_limits([headers, *([cell.text for cell in row.cells] for row in rows[1:])], path)
        table_rows: list[tuple[int, list[str]]] = []
        link_index = next(
            (index for index, header in enumerate(headers) if normalise_header(header) == "link"),
            None,
        )
        if link_index is None:
            continue
        for row_number, row in enumerate(rows[1:], start=2):
            values = [cell.text for cell in row.cells]
            if link_index < len(row.cells):
                targets = run_docx_extractions.extract_word_hyperlink_targets_from_cell(
                    row.cells[link_index], document.part
                )
                if targets:
                    values[link_index] = targets[0]
            table_rows.append((row_number, values))
        _validate_table_limits([headers, *(values for _row, values in table_rows)], path)
        tables.append((headers, table_rows))
    if not tables:
        raise ValueError("Source catalog is missing the required Link header.")
    return tables


def _validate_table_limits(rows: Sequence[Sequence[str]], path: Path) -> None:
    for row in rows:
        if len(row) > MAX_CATALOG_COLUMNS:
            raise ValueError(f"Catalog contains more than {MAX_CATALOG_COLUMNS} columns: {path}")
        if any(len(str(cell or "")) > MAX_CATALOG_CELL_CHARS for cell in row):
            raise ValueError(f"Catalog contains a cell longer than {MAX_CATALOG_CELL_CHARS} characters: {path}")


def _header_map(headers: Sequence[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, header in enumerate(headers):
        key = normalise_header(header)
        if not key:
            continue
        if key in result:
            raise ValueError(f"Source catalog has duplicate normalised header '{key}'.")
        result[key] = index
    return result


def _resolve_link(link: str, catalog_directory: Path) -> tuple[str, str, str]:
    youtube_url = run_docx_extractions.normalise_youtube_url(link)
    if youtube_url:
        video_id = run_docx_extractions.get_youtube_video_id(youtube_url) or ""
        return "youtube", youtube_url, video_id

    clean_link = link.strip()
    if len(clean_link) >= 2 and clean_link[0] == clean_link[-1] and clean_link[0] in {'"', "'"}:
        clean_link = clean_link[1:-1].strip()
    local_path = Path(clean_link).expanduser()
    if not local_path.is_absolute():
        local_path = catalog_directory / local_path
    resolved = local_path.resolve()
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"Catalog local source does not exist or is not a file: {resolved}")
    return "local", str(resolved), ""


def _cell(values: Sequence[str], index: int) -> str:
    if index >= len(values):
        return ""
    return str(values[index] or "").strip()


def _extend_unique(target: list[str], values: Iterable[str]) -> None:
    seen = set(target)
    for value in values:
        if value and value not in seen:
            target.append(value)
            seen.add(value)
