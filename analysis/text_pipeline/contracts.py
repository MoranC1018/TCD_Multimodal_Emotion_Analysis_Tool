"""Schemas and category discovery for RockSteady text postprocessing.

The RockSteady adapter can expose categories from custom dictionaries.  The
postprocessor must therefore treat its built-in category descriptions as a
catalogue, not as a closed output schema.  This module turns the actual CSV
headers (and, when present, the upstream manifest) into one explicit contract
used by every downstream table, chart, report, and manifest.
"""

from __future__ import annotations

import colorsys
import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Category:
    """One normalized RockSteady category in the current input contract."""

    key: str
    display: str
    source_names: tuple[str, ...]
    color: str
    required: bool = True
    source_column: str | None = None


CATEGORY_CATALOG: tuple[Category, ...] = (
    Category("positive", "Positive Sentiment", ("Positiv", "Positive"), "#16a34a"),
    Category("negative", "Negative Sentiment", ("Negativ", "Negative"), "#dc2626"),
    Category("active", "Active", ("Active",), "#2563eb"),
    Category("passive", "Passive", ("Passive",), "#64748b"),
    Category("strong", "Strong", ("Strong",), "#0891b2"),
    Category("weak", "Weak", ("Weak",), "#d97706"),
    Category("moral", "Moral", ("Moral",), "#be185d", required=False),
    Category("affiliation", "Affiliation", ("Affil", "Affiliation"), "#0f766e", required=False),
    Category("commodity", "Commodity", ("Commodity",), "#92400e", required=False),
    Category("econ_at", "Econ@", ("Econ@",), "#4338ca", required=False),
    Category("economics", "Economics", ("Economics",), "#1d4ed8", required=False),
    Category("energy", "Energy", ("Energy",), "#b45309", required=False),
    Category("finance", "Finance", ("Finance",), "#047857", required=False),
    Category("hostile", "Hostile", ("Hostile",), "#b91c1c", required=False),
    Category("military", "Military", ("Milit", "Military"), "#475569", required=False),
    Category("power", "Power", ("Power",), "#7e22ce", required=False),
    Category("risk", "Risk", ("Risk",), "#be123c", required=False),
)

# Backwards-compatible public name.  This is a catalogue, not the categories
# that must be emitted for every run; ``discover_categories`` builds that set.
CATEGORIES = CATEGORY_CATALOG

CORE_CATEGORY_KEYS = (
    "positive",
    "negative",
    "active",
    "passive",
    "strong",
    "weak",
)

ROCKSTEADY_IDENTITY_COLUMNS = {
    "title",
    "date of first article",
    "articles",
    "terms",
    "url",
}

def read_csv_header(path: Path) -> tuple[str, ...]:
    """Read one CSV header using the encodings accepted by the importer."""

    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with path.open(encoding=encoding, newline="") as handle:
                row = next(csv.reader(handle), None)
        except UnicodeDecodeError as error:
            last_error = error
            continue
        if not row:
            raise ValueError(f"RockSteady CSV has no header: {path}")
        header = tuple(cell.strip() for cell in row)
        if not all(header):
            raise ValueError(f"RockSteady CSV has a blank header name: {path}")
        folded = [name.casefold() for name in header]
        if len(set(folded)) != len(folded):
            raise ValueError(f"RockSteady CSV has duplicate case-insensitive headers: {path}")
        return header
    assert last_error is not None
    raise ValueError(f"Cannot decode RockSteady CSV header {path}: {last_error}")


def category_headers(header: Sequence[str]) -> tuple[str, ...]:
    """Return category columns from one RockSteady header in source order."""

    return tuple(
        name for name in header if name.strip().casefold() not in ROCKSTEADY_IDENTITY_COLUMNS
    )


def discover_categories(
    csv_paths: Sequence[Path],
    *,
    expected_source_names: Sequence[str] | None = None,
) -> tuple[Category, ...]:
    """Build a lossless category contract from every input CSV.

    A verified upstream manifest supplies ``expected_source_names`` and all CSVs
    must match it exactly.  Legacy standalone inputs may have heterogeneous
    optional columns, in which case their union is retained.  If a legacy file
    contains any of the established seven core fields, all seven remain
    required so a truncated conventional export is rejected rather than
    silently interpreted as a custom schema.
    """

    if not csv_paths:
        raise ValueError("Cannot discover categories without RockSteady CSV files")

    per_file: list[tuple[Path, tuple[str, ...]]] = [
        (path, category_headers(read_csv_header(path))) for path in csv_paths
    ]
    if any(not names for _, names in per_file):
        path = next(path for path, names in per_file if not names)
        raise ValueError(f"RockSteady CSV contains no dictionary-category columns: {path}")

    if expected_source_names is not None:
        expected = tuple(str(name).strip() for name in expected_source_names)
        if not expected or any(not name for name in expected):
            raise ValueError("Upstream manifest contains an empty category contract")
        expected_folded = tuple(name.casefold() for name in expected)
        for path, names in per_file:
            if tuple(name.casefold() for name in names) != expected_folded:
                raise ValueError(
                    f"RockSteady category header does not match the upstream manifest: {path}. "
                    f"Expected {list(expected)}; found {list(names)}."
                )
        source_names = expected
    else:
        source_names = _ordered_union(names for _, names in per_file)
        present_aliases = {name.casefold() for name in source_names}
        present_core = {
            category.key
            for category in CATEGORY_CATALOG
            if category.key in CORE_CATEGORY_KEYS
            and any(alias.casefold() in present_aliases for alias in category.source_names)
        }
        if present_core and present_core != set(CORE_CATEGORY_KEYS):
            missing = [
                category.display
                for category in CATEGORY_CATALOG
                if category.key in CORE_CATEGORY_KEYS and category.key not in present_core
            ]
            raise ValueError(
                "RockSteady CSV is missing required Total-mode columns "
                f"{missing}; no verified custom-category manifest was found."
            )

    categories = tuple(_category_from_source_name(name) for name in source_names)
    keys = [category.key.casefold() for category in categories]
    if len(set(keys)) != len(keys):
        raise ValueError(
            "RockSteady category names collapse to duplicate normalized output keys: "
            f"{list(source_names)}"
        )
    return categories


def categories_from_source_names(source_names: Sequence[str]) -> tuple[Category, ...]:
    """Normalize a manifest category list without reading CSV files."""

    return tuple(_category_from_source_name(str(name).strip()) for name in source_names)


def _ordered_union(groups: Iterable[Sequence[str]]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            folded = value.casefold()
            if folded not in seen:
                seen.add(folded)
                result.append(value)
    return tuple(result)


def _category_from_source_name(source_name: str) -> Category:
    for known in CATEGORY_CATALOG:
        if any(source_name.casefold() == alias.casefold() for alias in known.source_names):
            return Category(
                key=known.key,
                display=known.display,
                source_names=known.source_names,
                color=known.color,
                required=known.required,
                source_column=source_name,
            )

    key = re.sub(r"[^a-z0-9]+", "_", source_name.casefold()).strip("_")
    if not key:
        digest = hashlib.sha256(source_name.encode("utf-8")).hexdigest()[:12]
        key = f"category_{digest}"
    color = _stable_category_color(source_name)
    return Category(
        key=key,
        display=source_name,
        source_names=(source_name,),
        color=color,
        required=False,
        source_column=source_name,
    )


def _stable_category_color(source_name: str) -> str:
    """Return a deterministic, high-contrast colour for a custom category."""

    digest = hashlib.sha256(source_name.casefold().encode("utf-8")).digest()
    hue = int.from_bytes(digest[:2], "big") / 65535
    saturation = 0.58 + digest[2] / 255 * 0.20
    value = 0.62 + digest[3] / 255 * 0.18
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"
