"""Derive stable core RockSteady CSVs from one canonical full-category run."""

from __future__ import annotations

import csv
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from processing.io_utils import atomic_write_json, exclusive_process_lock
from spreadsheet_safety import SpreadsheetSafeWriter

from .contracts import TEXT_SCHEMA_VERSION, file_sha256, inventory_digest
from .filesystem import assert_safe_output_target, create_stage_directory, replace_stage_directory
from .rocksteady_transaction import rocksteady_pair_transaction


IDENTIFIER_COLUMNS = ("Title", "Date of First Article", "Articles", "Terms", "URL")
DERIVED_MANIFEST = "derived_view_manifest.json"


def derive_category_view(
    source_root: Path,
    target_root: Path,
    categories: Sequence[str],
    *,
    source_relative_paths: Sequence[str | Path] | None = None,
    upstream_inventory_sha256: str | None = None,
    manifest_source_root: Path | None = None,
) -> int:
    """Derive one category snapshot under its standalone stage lock."""

    source = Path(source_root).resolve()
    target = Path(target_root).resolve()
    lock_path = target.parent / f".{target.name}.derived-view.lock"
    with rocksteady_pair_transaction(
        source,
        target,
        purpose=f"protecting RockSteady all/core pair {source} and {target}",
    ), exclusive_process_lock(lock_path, purpose=f"publishing derived RockSteady view {target}"):
        pattern = f".{target.name}_staging_*"
        preexisting = {path.resolve() for path in target.parent.glob(pattern)}
        try:
            return _derive_category_view_unlocked(
                source,
                target,
                categories,
                source_relative_paths=source_relative_paths,
                upstream_inventory_sha256=upstream_inventory_sha256,
                manifest_source_root=manifest_source_root,
            )
        except BaseException:
            for candidate in target.parent.glob(pattern):
                if candidate.resolve() not in preexisting and candidate.is_dir():
                    shutil.rmtree(candidate, ignore_errors=True)
            raise


def _derive_category_view_unlocked(
    source_root: Path,
    target_root: Path,
    categories: Sequence[str],
    *,
    source_relative_paths: Sequence[str | Path] | None = None,
    upstream_inventory_sha256: str | None = None,
    manifest_source_root: Path | None = None,
) -> int:
    """Atomically write identifier columns plus the requested categories.

    ``source_relative_paths`` is authoritative when supplied, preventing CSVs
    left by an older dataset from leaking into a resumed run.
    """

    source_root = Path(source_root).resolve()
    target_root = assert_safe_output_target(target_root, source_root)
    if source_relative_paths is None:
        sources = sorted(path for path in source_root.rglob("*.csv") if "_manifests" not in path.parts)
    else:
        relative_paths = [Path(path) for path in source_relative_paths]
        if len({path.as_posix().casefold() for path in relative_paths}) != len(relative_paths):
            raise ValueError("Canonical RockSteady inventory contains duplicate CSV paths")
        sources = []
        for relative in relative_paths:
            if relative.is_absolute() or ".." in relative.parts or relative.suffix.casefold() != ".csv":
                raise ValueError(f"Invalid canonical RockSteady CSV inventory path: {relative}")
            source = source_root / relative
            if not source.is_file():
                raise FileNotFoundError(f"Canonical RockSteady CSV is missing: {source}")
            sources.append(source)
    if not sources:
        raise ValueError(f"No canonical RockSteady CSV files found under {source_root}")

    staging = create_stage_directory(target_root, "derived-view")
    items: list[dict[str, object]] = []
    try:
        for source in sources:
            relative = source.relative_to(source_root)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("r", encoding="utf-8-sig", newline="") as input_handle:
                reader = csv.DictReader(input_handle)
                missing = [
                    column
                    for column in (*IDENTIFIER_COLUMNS, *categories)
                    if column not in (reader.fieldnames or [])
                ]
                if missing:
                    raise ValueError(f"Canonical RockSteady CSV {source} is missing: {', '.join(missing)}")
                fields = [*IDENTIFIER_COLUMNS, *categories]
                with target.open("w", encoding="utf-8", newline="") as output_handle:
                    writer = SpreadsheetSafeWriter(
                        csv.DictWriter(output_handle, fieldnames=fields)
                    )
                    writer.writeheader()
                    row_count = 0
                    for row in reader:
                        writer.writerow({field: row.get(field, "") for field in fields})
                        row_count += 1
            items.append(
                {
                    "identity": relative.with_suffix("").as_posix(),
                    "source": relative.as_posix(),
                    "output": relative.as_posix(),
                    "source_sha256": file_sha256(source),
                    "output_sha256": file_sha256(target),
                    "rows": row_count,
                    "status": "completed",
                }
            )
        manifest = {
            "schema_version": TEXT_SCHEMA_VERSION,
            "kind": "derived-rocksteady-category-view",
            "status": "completed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_root": str(
                Path(manifest_source_root).resolve()
                if manifest_source_root is not None
                else source_root
            ),
            "categories": list(categories),
            "upstream_inventory_sha256": upstream_inventory_sha256,
            "inventory_sha256": inventory_digest(items),
            "summary": {"total": len(items), "completed": len(items), "failed": 0},
            "files": items,
        }
        atomic_write_json(staging / DERIVED_MANIFEST, manifest)
        replace_stage_directory(staging, target_root, "derived-view")
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return len(sources)
