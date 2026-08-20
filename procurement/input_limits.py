"""Bounded readers for untrusted DOCX packages and small control JSON files."""

from __future__ import annotations

import json
import io
import zipfile
from pathlib import Path
from typing import Any


MIB = 1024 * 1024
MAX_DOCX_COMPRESSED_BYTES = 128 * MIB
MAX_DOCX_ARCHIVE_ENTRIES = 2048
MAX_DOCX_TOTAL_EXPANDED_BYTES = 128 * MIB
MAX_DOCX_ENTRY_EXPANDED_BYTES = 32 * MIB
MAX_DOCX_COMPRESSION_RATIO = 250.0
MAX_CLEAN_SPEAKER_JSON_BYTES = 1 * MIB
MAX_CLEAN_SPEAKER_JSON_ITEMS = 50_000
MAX_FACE_REFERENCE_JSON_BYTES = 256 * 1024
MAX_FACE_REFERENCE_JSON_ITEMS = 8_192
MAX_TERM_DICTIONARY_JSON_BYTES = 1 * MIB
MAX_TERM_DICTIONARY_JSON_ITEMS = 50_000
MAX_TERM_DICTIONARY_CATEGORIES = 256
MAX_TERM_DICTIONARY_PATTERNS = 4_096
MAX_TERM_PATTERN_CHARS = 2_048
MAX_WORKFLOW_MANIFEST_JSON_BYTES = 1 * MIB
MAX_WORKFLOW_MANIFEST_JSON_ITEMS = 50_000


class DocxPackageError(ValueError):
    """Base class for a rejected DOCX package."""


class DocxPackageFormatError(DocxPackageError):
    """A package is unavailable or malformed and may be a cloud placeholder."""


class DocxPackageLimitError(DocxPackageError):
    """A package exceeds a security budget and must not be retried."""


def read_bounded_prefix(path: Path, length: int = 4) -> bytes:
    """Read at most ``length`` bytes without materialising the whole file."""

    with path.open("rb") as handle:
        return handle.read(length)


def validate_docx_package(path: Path) -> None:
    """Reject oversized or highly compressed Word packages before python-docx."""

    docx_path = path.expanduser().resolve()
    read_docx_snapshot(docx_path)


def read_docx_snapshot(path: Path) -> bytes:
    """Read and validate one immutable, bounded snapshot of a Word package."""

    docx_path = path.expanduser().resolve()
    try:
        with docx_path.open("rb") as handle:
            snapshot = handle.read(MAX_DOCX_COMPRESSED_BYTES + 1)
    except OSError as exc:
        raise DocxPackageFormatError(f"Could not inspect DOCX package: {docx_path}") from exc
    if len(snapshot) > MAX_DOCX_COMPRESSED_BYTES:
        raise DocxPackageLimitError(
            f"DOCX compressed size exceeds {MAX_DOCX_COMPRESSED_BYTES} bytes: {docx_path}"
        )
    if not snapshot.startswith(b"PK"):
        raise DocxPackageFormatError(f"DOCX is not a ZIP-based Word package: {docx_path}")

    try:
        with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
            entries = archive.infolist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise DocxPackageFormatError(f"DOCX is not a valid ZIP package: {docx_path}") from exc
    if len(entries) > MAX_DOCX_ARCHIVE_ENTRIES:
        raise DocxPackageLimitError(
            f"DOCX archive entry count exceeds {MAX_DOCX_ARCHIVE_ENTRIES}: {docx_path}"
        )

    total_expanded = 0
    for entry in entries:
        if entry.flag_bits & 0x1:
            raise DocxPackageLimitError(f"DOCX contains an encrypted ZIP entry: {entry.filename}")
        if entry.file_size > MAX_DOCX_ENTRY_EXPANDED_BYTES:
            raise DocxPackageLimitError(
                f"DOCX ZIP entry expanded size exceeds {MAX_DOCX_ENTRY_EXPANDED_BYTES} bytes: "
                f"{entry.filename}"
            )
        total_expanded += entry.file_size
        if total_expanded > MAX_DOCX_TOTAL_EXPANDED_BYTES:
            raise DocxPackageLimitError(
                f"DOCX total expanded size exceeds {MAX_DOCX_TOTAL_EXPANDED_BYTES} bytes: {docx_path}"
            )
        if entry.file_size:
            ratio = entry.file_size / max(1, entry.compress_size)
            if ratio > MAX_DOCX_COMPRESSION_RATIO:
                raise DocxPackageLimitError(
                    f"DOCX ZIP entry compression ratio exceeds {MAX_DOCX_COMPRESSION_RATIO:g}: "
                    f"{entry.filename}"
                )
    return snapshot


def read_control_json(
    path: Path,
    *,
    label: str,
    max_bytes: int,
    max_items: int,
) -> Any:
    """Read one bounded UTF-8 JSON control file and cap its semantic nodes."""

    control_path = path.expanduser().resolve()
    with control_path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"{label} JSON exceeds {max_bytes} bytes: {control_path}")
    payload = json.loads(raw.decode("utf-8-sig"))
    item_count = count_json_items(payload, stop_after=max_items)
    if item_count > max_items:
        raise ValueError(f"{label} JSON contains more than {max_items} items: {control_path}")
    return payload


def count_json_items(value: Any, *, stop_after: int) -> int:
    """Count container members iteratively and stop once the budget is exceeded."""

    count = 0
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            count += len(current)
            pending.extend(current.values())
        elif isinstance(current, list):
            count += len(current)
            pending.extend(current)
        if count > stop_after:
            return count
    return count


def read_term_dictionary(path: Path) -> dict[str, list[str]]:
    """Read a bounded licence-term dictionary before regex compilation."""

    payload = read_control_json(
        path,
        label="licence term dictionary",
        max_bytes=MAX_TERM_DICTIONARY_JSON_BYTES,
        max_items=MAX_TERM_DICTIONARY_JSON_ITEMS,
    )
    if not isinstance(payload, dict):
        raise ValueError("Dictionary JSON must be an object mapping categories to lists of regex strings.")
    if len(payload) > MAX_TERM_DICTIONARY_CATEGORIES:
        raise ValueError(
            f"Dictionary JSON contains more than {MAX_TERM_DICTIONARY_CATEGORIES} categories."
        )
    total_patterns = 0
    validated: dict[str, list[str]] = {}
    for category, patterns in payload.items():
        if not isinstance(category, str) or not isinstance(patterns, list) or not all(
            isinstance(pattern, str) for pattern in patterns
        ):
            raise ValueError(f"Dictionary category {category!r} must be a list of regex strings.")
        total_patterns += len(patterns)
        if total_patterns > MAX_TERM_DICTIONARY_PATTERNS:
            raise ValueError(
                f"Dictionary JSON contains more than {MAX_TERM_DICTIONARY_PATTERNS} regex patterns."
            )
        if any(len(pattern) > MAX_TERM_PATTERN_CHARS for pattern in patterns):
            raise ValueError(
                f"Dictionary category {category!r} contains a regex longer than "
                f"{MAX_TERM_PATTERN_CHARS} characters."
            )
        validated[category] = list(patterns)
    return validated
