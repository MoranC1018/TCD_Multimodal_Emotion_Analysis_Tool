"""Small shared boundary helpers for spreadsheet-safe text exports."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any, Iterable


_FORMULA_PREFIXES = frozenset(("=", "+", "-", "@", "\t", "\r"))
_STRICT_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")


def neutralize_spreadsheet_value(value: Any) -> Any:
    """Prefix formula-like text with an apostrophe while preserving other values."""

    if not isinstance(value, str):
        return value
    effective = value.lstrip(" \ufeff")
    if _STRICT_NUMBER.fullmatch(effective):
        return value
    if effective[:1] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def neutralize_spreadsheet_row(row: Any) -> Any:
    if isinstance(row, Mapping):
        return {key: neutralize_spreadsheet_value(value) for key, value in row.items()}
    return [neutralize_spreadsheet_value(value) for value in row]


class SpreadsheetSafeWriter:
    """Apply formula neutralization to rows before delegating to ``csv`` writers."""

    def __init__(self, writer: Any) -> None:
        self._writer = writer

    def writeheader(self) -> Any:
        fieldnames = getattr(self._writer, "fieldnames", None)
        if fieldnames is None:
            return self._writer.writeheader()
        return self.writerow({fieldname: fieldname for fieldname in fieldnames})

    def writerow(self, row: Any) -> Any:
        return self._writer.writerow(neutralize_spreadsheet_row(row))

    def writerows(self, rows: Iterable[Any]) -> Any:
        return self._writer.writerows(neutralize_spreadsheet_row(row) for row in rows)
