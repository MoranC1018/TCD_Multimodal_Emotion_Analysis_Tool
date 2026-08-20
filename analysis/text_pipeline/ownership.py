"""Ownership, path-safety, and locking rules for text postprocessing outputs.

The postprocessor replaces directories as a unit.  That is only safe when the
target is either empty or demonstrably belongs to this component.  This module
keeps that policy separate from report generation so both the single-variant
and paired entry points enforce exactly the same rules.
"""

from __future__ import annotations

import csv
import json
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from analysis.text_pipeline.provenance import sha256_file
from processing.io_utils import (
    assert_no_output_path_aliases,
    assert_safe_output_path,
    atomic_write_json,
    exclusive_process_lock,
)


OUTPUT_OWNER_FILE = ".text_postprocessing_owner.json"
OUTPUT_OWNER_KIND = "multimodal-emotion-analysis-text-postprocessing-output"
OUTPUT_OWNER_SCHEMA = "1.0"
BATCH_MANIFEST_FILE = "text_postprocessing_batch_manifest.json"
PAIR_KIND = "text-postprocessing-selected-extra-pair"
KNOWN_VARIANTS = frozenset({"original", "eng", "selected", "extra"})
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class OwnershipAssessment:
    """Why an existing target is safe to replace."""

    state: str
    detail: str


def normalize_run_id(run_id: str | None) -> str:
    """Return a printable run identifier, generating one when omitted."""

    if run_id is None:
        return str(uuid.uuid4())
    value = str(run_id).strip()
    if not value:
        raise ValueError("run_id must not be empty")
    if len(value) > 200 or any(character in value for character in "\r\n\0"):
        raise ValueError("run_id must be a single printable value of at most 200 characters")
    return value


def validate_output_boundaries(output_dir: Path, sources: Sequence[Path]) -> Path:
    """Reject source/output overlap in either direction.

    A directory-level publication would otherwise be capable of consuming its
    own staging tree or replacing input evidence.  Resolve paths before the
    comparison so ``..`` and symlink aliases cannot bypass the check.
    """

    return assert_safe_output_path(
        output_dir,
        repository_root=REPOSITORY_ROOT,
        protected_sources=sources,
        description="Text postprocessing output",
    )


def validate_distinct_variant_inputs(selected_input: Path, extra_input: Path) -> None:
    """Require selected and extra inputs to be independent directory trees."""

    selected = Path(selected_input).expanduser().resolve()
    extra = Path(extra_input).expanduser().resolve()
    if selected == extra or selected in extra.parents or extra in selected.parents:
        raise ValueError(
            "Selected and extra RockSteady input roots must be distinct, non-overlapping "
            f"directories: selected={selected}, extra={extra}"
        )


@contextmanager
def text_output_lock(
    output_dir: Path,
    *,
    scope: str,
    variant: str | None = None,
) -> Iterator[None]:
    """Serialize a complete run across single and paired entry points.

    For a normal ``.../<family>/selected`` or ``extra`` target, the lock is
    named after the shared family root.  A paired run targeting ``<family>``
    therefore takes the same lock and cannot race either single-variant run.
    The lock lives beside the family root, rather than inside it, because the
    family directory itself is atomically replaced.
    """

    output = assert_safe_output_path(
        output_dir,
        repository_root=REPOSITORY_ROOT,
        description="Text postprocessing output",
    )
    if scope == "pair":
        family_root = output
    elif scope == "variant":
        normalized_variant = (variant or "").strip().casefold()
        family_root = (
            output.parent
            if normalized_variant in KNOWN_VARIANTS
            and output.name.strip().casefold() == normalized_variant
            else output
        )
    else:
        raise ValueError(f"Unknown text output ownership scope: {scope!r}")
    lock_path = family_root.parent / f".{family_root.name}.text-postprocessing.lock"
    with exclusive_process_lock(
        lock_path,
        purpose=f"running text postprocessing for {family_root}",
    ):
        yield


def assert_publishable_output(
    output_dir: Path,
    *,
    scope: str,
    variant: str | None = None,
) -> OwnershipAssessment:
    """Prove that replacing ``output_dir`` will not delete an unknown tree."""

    output = assert_safe_output_path(
        output_dir,
        repository_root=REPOSITORY_ROOT,
        description="Text postprocessing output",
    )
    if not output.exists():
        return OwnershipAssessment("absent", "target does not exist")
    if output.is_symlink():
        raise ValueError(f"Refusing to replace a symlinked output directory: {output}")
    if not output.is_dir():
        raise NotADirectoryError(f"Text postprocessing output is not a directory: {output}")
    try:
        entries = list(output.iterdir())
    except OSError as error:
        raise PermissionError(f"Cannot inspect text postprocessing output {output}: {error}") from error
    if not entries:
        return OwnershipAssessment("empty", "target directory is empty")
    if all(
        entry.name == ".gitkeep" and entry.is_file() and not entry.is_symlink()
        for entry in entries
    ):
        return OwnershipAssessment(
            "empty_placeholder",
            "target contains only the repository placeholder .gitkeep",
        )

    owner_path = output / OUTPUT_OWNER_FILE
    if owner_path.exists():
        owner = _read_json_object(owner_path, "output owner")
        _validate_owner(owner, owner_path, scope=scope, variant=variant)
        if scope == "variant":
            _validate_variant_tree(output, require_owner=True)
        else:
            _validate_pair_tree(output, require_owner=True)
        return OwnershipAssessment("owned", f"valid owner marker: {owner_path}")

    if scope == "variant":
        try:
            _validate_legacy_variant(output, expected_variant=variant)
        except (ValueError, OSError) as error:
            raise ValueError(
                "Refusing to replace a non-empty directory that is not an owned or "
                f"recognized legacy text-postprocessing output: {output}. {error}"
            ) from error
    elif scope == "pair":
        try:
            _validate_legacy_pair(output)
        except (ValueError, OSError) as error:
            raise ValueError(
                "Refusing to replace a non-empty directory that is not an owned or "
                f"recognized legacy selected/extra output family: {output}. {error}"
            ) from error
    else:
        raise ValueError(f"Unknown text output ownership scope: {scope!r}")
    return OwnershipAssessment(
        "legacy",
        "recognized a complete legacy text-postprocessing output; the next successful "
        "publication will add an owner marker",
    )


def write_output_owner(
    output_dir: Path,
    *,
    scope: str,
    run_id: str,
    variant: str | None = None,
) -> Path:
    """Write the machine-readable owner marker into a completed staging tree."""

    normalized_variant = _normalize_variant(variant) if scope == "variant" else None
    managed_entries = (
        ["selected", "extra", "multimodal", BATCH_MANIFEST_FILE]
        if scope == "pair"
        else [
            "output_manifest.json",
            "video_level_summary.csv",
            "speaker_level_summary.csv",
            "descriptor_statistics_by_video.csv",
            "segment_alignment_audit.csv",
            "segment_counts/",
            "segment_relative/",
            "segment_level/",
            "readable/",
            "graphs/",
            "POSTPROCESSING_REPORT.md",
            "POSTPROCESSING_REPORT_EN.md",
            "run_log.txt",
        ]
    )
    payload = {
        "schema_version": OUTPUT_OWNER_SCHEMA,
        "kind": OUTPUT_OWNER_KIND,
        "component": "analysis.text_pipeline.postprocess",
        "scope": scope,
        "variant": normalized_variant,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "managed_entries": managed_entries,
    }
    path = Path(output_dir) / OUTPUT_OWNER_FILE
    atomic_write_json(path, payload)
    return path


def _validate_owner(
    owner: Mapping[str, object],
    owner_path: Path,
    *,
    scope: str,
    variant: str | None,
) -> None:
    if owner.get("schema_version") != OUTPUT_OWNER_SCHEMA:
        raise ValueError(f"Unsupported text output owner schema at {owner_path}")
    if owner.get("kind") != OUTPUT_OWNER_KIND or owner.get("component") != "analysis.text_pipeline.postprocess":
        raise ValueError(f"Foreign or malformed output owner marker at {owner_path}")
    if owner.get("scope") != scope:
        raise ValueError(
            f"Output ownership scope mismatch at {owner_path}: expected {scope!r}, "
            f"found {owner.get('scope')!r}"
        )
    if scope == "variant" and owner.get("variant") != _normalize_variant(variant):
        raise ValueError(
            f"Output variant ownership mismatch at {owner_path}: expected "
            f"{_normalize_variant(variant)!r}, found {owner.get('variant')!r}"
        )
    run_id = owner.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError(f"Output owner marker has no run_id: {owner_path}")


def _validate_variant_tree(output: Path, *, require_owner: bool) -> Mapping[str, object]:
    manifest_path = output / "output_manifest.json"
    manifest = _read_json_object(manifest_path, "variant output manifest")
    if manifest.get("schema_version") not in {
        1,
        "1",
        "1.0",
        2,
        "2",
        "2.0",
        "2.1",
    }:
        raise ValueError(f"Unsupported text output manifest schema: {manifest_path}")
    if str(manifest.get("status", "")).casefold() != "completed":
        raise ValueError(f"Text output manifest is not completed: {manifest_path}")
    kind = manifest.get("kind")
    if kind not in {None, "text-postprocessing-variant"}:
        raise ValueError(f"Unexpected text output manifest kind at {manifest_path}: {kind!r}")
    if not isinstance(manifest.get("inputs"), dict) or not isinstance(manifest.get("summary"), dict):
        raise ValueError(f"Text output manifest lacks inputs/summary contracts: {manifest_path}")

    inventory = manifest.get("output_inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError(
            f"Text output manifest has no verifiable output_inventory: {manifest_path}"
        )
    expected_files = {Path("output_manifest.json")}
    for row_number, item in enumerate(inventory, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Invalid output_inventory row {row_number}: {manifest_path}")
        relative_value = item.get("path")
        digest = item.get("sha256")
        if not isinstance(relative_value, str) or not _is_safe_relative_path(relative_value):
            raise ValueError(f"Unsafe output_inventory path at {manifest_path}: {relative_value!r}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError(f"Invalid output_inventory SHA-256 at {manifest_path}: {relative_value}")
        relative = Path(relative_value)
        if relative in expected_files:
            raise ValueError(f"Duplicate output_inventory path at {manifest_path}: {relative_value}")
        expected_files.add(relative)
        artifact = output / relative
        if not artifact.is_file() or artifact.is_symlink():
            raise ValueError(f"Managed text output artifact is missing or unsafe: {artifact}")
        expected_bytes = item.get("bytes")
        if isinstance(expected_bytes, int) and artifact.stat().st_size != expected_bytes:
            raise ValueError(f"Managed text output artifact size changed: {artifact}")
        if sha256_file(artifact).casefold() != digest.casefold():
            raise ValueError(f"Managed text output artifact hash changed: {artifact}")

    actual_files = {
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_file()
    }
    unsafe_links = [
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_symlink()
    ]
    if unsafe_links:
        raise ValueError(
            f"Managed text output contains symbolic links: {output}; "
            f"links={sorted(map(str, unsafe_links))[:8]}"
        )
    if actual_files != expected_files:
        raise ValueError(
            "Refusing to replace a text output containing unowned or missing files: "
            f"{output}; extra={sorted(map(str, actual_files - expected_files))[:8]}, "
            f"missing={sorted(map(str, expected_files - actual_files))[:8]}"
        )
    expected_dirs: set[Path] = set()
    for relative_file in expected_files:
        for parent in relative_file.parents:
            if parent == Path("."):
                break
            expected_dirs.add(parent)
    actual_dirs = {
        path.relative_to(output)
        for path in output.rglob("*")
        if path.is_dir() and not path.is_symlink()
    }
    if actual_dirs != expected_dirs:
        raise ValueError(
            "Refusing to replace a text output containing unowned or missing directories: "
            f"{output}; extra={sorted(map(str, actual_dirs - expected_dirs))[:8]}, "
            f"missing={sorted(map(str, expected_dirs - actual_dirs))[:8]}"
        )
    if require_owner and Path(OUTPUT_OWNER_FILE) not in expected_files:
        raise ValueError(f"Owned output inventory omits its owner marker: {manifest_path}")
    if require_owner:
        owner_path = output / OUTPUT_OWNER_FILE
        owner = _read_json_object(owner_path, "variant output owner")
        if manifest.get("run_id") != owner.get("run_id"):
            raise ValueError(f"Variant owner/manifest run_id mismatch at {output}")
        if manifest.get("variant") != owner.get("variant"):
            raise ValueError(f"Variant owner/manifest variant mismatch at {output}")
    return manifest


def _validate_legacy_variant(output: Path, *, expected_variant: str | None) -> None:
    files = {path.relative_to(output) for path in output.rglob("*") if path.is_file()}
    if Path(OUTPUT_OWNER_FILE) in files:
        raise ValueError(f"Malformed owner state in legacy output: {output}")
    manifest_path = output / "output_manifest.json"
    if manifest_path.is_file():
        manifest = _validate_variant_tree(output, require_owner=False)
    else:
        _validate_pre_manifest_variant(output)
        manifest = {}
    inferred = _infer_manifest_variant(output, manifest)
    normalized_expected = _normalize_variant(expected_variant)
    if inferred is not None and inferred != normalized_expected:
        raise ValueError(
            f"Legacy text output variant mismatch at {output}: expected "
            f"{normalized_expected!r}, inferred {inferred!r}"
        )


def _validate_pair_tree(output: Path, *, require_owner: bool) -> Mapping[str, object]:
    expected_top = {"selected", "extra", "multimodal", BATCH_MANIFEST_FILE}
    if require_owner:
        expected_top.add(OUTPUT_OWNER_FILE)
    actual_top = {entry.name for entry in output.iterdir()}
    if actual_top != expected_top:
        raise ValueError(
            f"Refusing to replace a paired text output with foreign/missing entries: {output}; "
            f"extra={sorted(actual_top - expected_top)}, missing={sorted(expected_top - actual_top)}"
        )
    for variant in ("selected", "extra"):
        child = output / variant
        if not child.is_dir() or child.is_symlink():
            raise ValueError(f"Paired text output variant is not a safe directory: {child}")
    selected_manifest = _validate_variant_tree(output / "selected", require_owner=True)
    extra_manifest = _validate_variant_tree(output / "extra", require_owner=True)
    _require_manifest_variant(selected_manifest, output / "selected", "selected")
    _require_manifest_variant(extra_manifest, output / "extra", "extra")
    _validate_multimodal_tree(output / "multimodal")

    batch_path = output / BATCH_MANIFEST_FILE
    batch = _read_json_object(batch_path, "paired output manifest")
    if (
        batch.get("schema_version") != "1.0"
        or batch.get("kind") != PAIR_KIND
        or str(batch.get("status", "")).casefold() != "completed"
    ):
        raise ValueError(f"Paired text output manifest is not a completed pair: {batch_path}")
    batch_run_id = batch.get("run_id")
    if not isinstance(batch_run_id, str) or not batch_run_id.strip():
        raise ValueError(f"Paired text output manifest has no run_id: {batch_path}")
    if require_owner:
        parent_owner = _read_json_object(output / OUTPUT_OWNER_FILE, "paired output owner")
        if parent_owner.get("run_id") != batch_run_id:
            raise ValueError(f"Paired owner/manifest run_id mismatch at {output}")
    if (
        selected_manifest.get("run_id") != batch_run_id
        or extra_manifest.get("run_id") != batch_run_id
    ):
        raise ValueError(f"Paired variants do not share the parent run_id: {batch_path}")
    variants = batch.get("variants")
    if not isinstance(variants, dict):
        raise ValueError(f"Paired text output manifest has no variants contract: {batch_path}")
    for name in ("selected", "extra"):
        record = variants.get(name)
        if not isinstance(record, dict):
            raise ValueError(f"Paired manifest is missing the {name} record: {batch_path}")
        expected_hash = record.get("output_manifest_sha256")
        manifest_file = output / name / "output_manifest.json"
        if not isinstance(expected_hash, str) or sha256_file(manifest_file) != expected_hash:
            raise ValueError(f"Paired manifest hash differs for {name}: {batch_path}")
    return batch


def _validate_legacy_pair(output: Path) -> None:
    """Recognize the old parent layout without deleting arbitrary siblings."""

    allowed = {"selected", "extra"}
    actual = {entry.name for entry in output.iterdir()}
    if "multimodal" in actual:
        allowed.add("multimodal")
    if actual != allowed:
        raise ValueError(
            "Refusing to replace a non-empty directory that is not an owned or recognized "
            f"legacy selected/extra output family: {output}; entries={sorted(actual)[:12]}"
        )
    if "multimodal" in actual:
        _validate_multimodal_tree(output / "multimodal")
    for variant in ("selected", "extra"):
        child = output / variant
        if not child.is_dir() or child.is_symlink():
            raise ValueError(f"Legacy paired output entry is not a safe directory: {child}")
        owner_path = child / OUTPUT_OWNER_FILE
        if owner_path.is_file():
            owner = _read_json_object(owner_path, "variant output owner")
            _validate_owner(owner, owner_path, scope="variant", variant=variant)
            manifest = _validate_variant_tree(child, require_owner=True)
            _require_manifest_variant(manifest, child, variant)
        else:
            _validate_legacy_variant(child, expected_variant=variant)


def _validate_pre_manifest_variant(output: Path) -> None:
    """Recognise the exact report tree produced before output manifests existed.

    This permits a transactional replacement of this project's historical
    output without pretending it has modern provenance.  Every entry and file
    type is constrained; an arbitrary non-empty directory remains protected.
    """

    required_files = {
        "descriptor_statistics_by_video.csv",
        "video_level_summary.csv",
        "speaker_level_summary.csv",
        "segment_alignment_audit.csv",
        "POSTPROCESSING_REPORT.md",
        "POSTPROCESSING_REPORT_EN.md",
        "run_log.txt",
    }
    required_directories = {"segment_counts", "segment_relative", "segment_level", "graphs"}
    actual_top = {entry.name for entry in output.iterdir()}
    expected_top = required_files | required_directories
    has_readable = "readable" in actual_top
    if has_readable:
        expected_top.add("readable")
    if actual_top != expected_top:
        raise ValueError(
            f"Historical text output has foreign/missing top-level entries: {output}; "
            f"extra={sorted(actual_top - expected_top)}, missing={sorted(expected_top - actual_top)}"
        )

    for name in required_files:
        path = output / name
        assert_no_output_path_aliases(path, description="historical text output")
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"Historical text output file is missing or empty: {path}")
        if path.suffix.casefold() == ".csv":
            _require_readable_csv(path)

    for directory_name in ("segment_counts", "segment_relative", "segment_level"):
        directory = output / directory_name
        assert_no_output_path_aliases(directory, description="historical text output")
        csv_files = sorted(directory.rglob("*.csv"))
        if not csv_files:
            raise ValueError(f"Historical text output has no CSV files under {directory}")
        actual_files = {path for path in directory.rglob("*") if path.is_file()}
        if actual_files != set(csv_files):
            raise ValueError(f"Historical text output has foreign files under {directory}")
        for path in csv_files:
            assert_no_output_path_aliases(path, description="historical text output")
            relative = path.relative_to(directory)
            if len(relative.parts) not in {2, 3}:
                raise ValueError(
                    f"Historical text CSV is not Speaker/Video.csv or "
                    f"Country/Speaker/Video.csv: {path}"
                )
            _require_readable_csv(path)

    if has_readable:
        _validate_readable_text_tables(output / "readable")

    graphs = output / "graphs"
    assert_no_output_path_aliases(graphs, description="historical text output")
    graph_files = [path for path in graphs.rglob("*") if path.is_file()]
    if not graph_files:
        raise ValueError(f"Historical text output has no graphs under {graphs}")
    for path in graph_files:
        assert_no_output_path_aliases(path, description="historical text output")
        if path.suffix.casefold() != ".svg" or path.stat().st_size <= 0:
            raise ValueError(f"Historical graph is not a non-empty SVG: {path}")
        prefix = path.read_text(encoding="utf-8-sig", errors="strict")[:1024].casefold()
        if "<svg" not in prefix:
            raise ValueError(f"Historical graph does not contain an SVG document: {path}")


def _validate_readable_text_tables(output: Path) -> None:
    """Validate the exact human-readable selected/extra table family."""

    assert_no_output_path_aliases(output, description="readable Text tables")
    required_files = {
        "README.md",
        "category_guide.csv",
        "video_level_summary.csv",
        "speaker_level_summary.csv",
    }
    actual_top = {entry.name for entry in output.iterdir()}
    expected_top = required_files | {"segment_level", "graphs"}
    if actual_top != expected_top:
        raise ValueError(
            f"Readable Text tables have foreign/missing entries: {output}; "
            f"extra={sorted(actual_top - expected_top)}, missing={sorted(expected_top - actual_top)}"
        )
    for name in required_files - {"README.md"}:
        _require_readable_csv(output / name)
    readme = output / "README.md"
    if not readme.is_file() or readme.stat().st_size <= 0:
        raise ValueError(f"Readable Text README is missing or empty: {readme}")
    segment_root = output / "segment_level"
    csv_files = sorted(segment_root.rglob("*.csv"))
    if not csv_files:
        raise ValueError(f"Readable Text tables contain no segment CSV files: {segment_root}")
    if {path for path in segment_root.rglob("*") if path.is_file()} != set(csv_files):
        raise ValueError(f"Readable Text segment tree contains foreign files: {segment_root}")
    for path in csv_files:
        if len(path.relative_to(segment_root).parts) not in {2, 3}:
            raise ValueError(
                f"Readable Text segment path is not Speaker/Video or "
                f"Country/Speaker/Video: {path}"
            )
        _require_readable_csv(path)
    graph_root = output / "graphs"
    graph_files = [path for path in graph_root.rglob("*") if path.is_file()]
    if not graph_files:
        raise ValueError(f"Readable Text tables contain no SVG graphs: {graph_root}")
    for path in graph_files:
        if path.suffix.casefold() != ".svg" or path.stat().st_size <= 0:
            raise ValueError(f"Readable Text graph is invalid: {path}")
        if "<svg" not in path.read_text(encoding="utf-8-sig")[:1024].casefold():
            raise ValueError(f"Readable Text graph is not SVG: {path}")


def _validate_multimodal_tree(output: Path) -> None:
    """Validate the complete readable Transcript multimodal output family."""

    assert_no_output_path_aliases(output, description="Transcript multimodal output")
    if not output.is_dir() or output.is_symlink():
        raise ValueError(f"Transcript multimodal output is not a safe directory: {output}")
    required_files = {
        "README.md",
        "alignment_contract.json",
        "construct_mapping.csv",
        "video_level_summary.csv",
        "speaker_level_summary.csv",
    }
    required_directories = {"segment_level", "graphs"}
    actual_top = {entry.name for entry in output.iterdir()}
    expected_top = required_files | required_directories
    if actual_top != expected_top:
        raise ValueError(
            f"Transcript multimodal output has foreign/missing entries: {output}; "
            f"extra={sorted(actual_top - expected_top)}, missing={sorted(expected_top - actual_top)}"
        )
    for name in ("construct_mapping.csv", "video_level_summary.csv", "speaker_level_summary.csv"):
        _require_readable_csv(output / name)
    readme = output / "README.md"
    if not readme.is_file() or readme.stat().st_size <= 0:
        raise ValueError(f"Transcript multimodal README is missing or empty: {readme}")
    contract = _read_json_object(output / "alignment_contract.json", "multimodal contract")
    if (
        contract.get("schema_version") != "1.0"
        or contract.get("kind") != "transcript-multimodal-alignment"
        or contract.get("modality") != "transcript"
    ):
        raise ValueError(f"Transcript multimodal contract is invalid: {output}")

    segment_root = output / "segment_level"
    segment_files = sorted(segment_root.rglob("*.csv"))
    if not segment_files:
        raise ValueError(f"Transcript multimodal output has no segment files: {segment_root}")
    if {path for path in segment_root.rglob("*") if path.is_file()} != set(segment_files):
        raise ValueError(f"Transcript multimodal segment tree contains foreign files: {segment_root}")
    for path in segment_files:
        relative = path.relative_to(segment_root)
        if len(relative.parts) not in {2, 3}:
            raise ValueError(
                f"Transcript multimodal segment path is not Speaker/Video or "
                f"Country/Speaker/Video: {path}"
            )
        _require_readable_csv(path)

    graph_root = output / "graphs"
    graph_files = [path for path in graph_root.rglob("*") if path.is_file()]
    if not graph_files:
        raise ValueError(f"Transcript multimodal output has no SVG graphs: {graph_root}")
    for path in graph_files:
        if path.suffix.casefold() != ".svg" or path.stat().st_size <= 0:
            raise ValueError(f"Transcript multimodal graph is invalid: {path}")
        if "<svg" not in path.read_text(encoding="utf-8-sig")[:1024].casefold():
            raise ValueError(f"Transcript multimodal graph is not SVG: {path}")


def _require_readable_csv(path: Path) -> None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), None)
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError(f"Cannot read historical text CSV {path}: {error}") from error
    if not header or any(not str(column).strip() for column in header):
        raise ValueError(f"Historical text CSV has no usable header: {path}")


def _require_manifest_variant(
    manifest: Mapping[str, object], output: Path, expected: str
) -> None:
    declared = manifest.get("variant")
    if declared not in {None, expected}:
        raise ValueError(
            f"Text output manifest variant mismatch at {output}: expected {expected!r}, "
            f"found {declared!r}"
        )


def _infer_manifest_variant(output: Path, manifest: Mapping[str, object]) -> str | None:
    declared = manifest.get("variant")
    if isinstance(declared, str) and declared.casefold() in KNOWN_VARIANTS:
        return declared.casefold()
    if output.name.casefold() in KNOWN_VARIANTS:
        return output.name.casefold()
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        return None
    source_value = inputs.get("rocksteady_csv_root")
    if not isinstance(source_value, str):
        return None
    source = Path(source_value)
    name = source.name.strip().casefold()
    if name == "rocksteady output" and source.parent.name.strip().casefold() == "extra":
        return "extra"
    return name if name in KNOWN_VARIANTS else None


def _normalize_variant(variant: str | None) -> str:
    value = str(variant or "custom").strip().casefold()
    return value if value in KNOWN_VARIANTS else "custom"


def _read_json_object(path: Path, label: str) -> Mapping[str, object]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing or unsafe {label}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read {label} {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label.capitalize()} must be a JSON object: {path}")
    return payload


def _is_safe_relative_path(value: str) -> bool:
    candidate = Path(value)
    return bool(value) and not candidate.is_absolute() and ".." not in candidate.parts
