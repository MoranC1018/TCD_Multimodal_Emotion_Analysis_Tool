"""Validate and preserve RockSteady provenance for final text outputs."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class UpstreamProvenance:
    """Verified upstream evidence, or an explicit legacy-unverified marker."""

    status: str
    kind: str
    manifest_path: Path | None
    manifest_sha256: str | None
    expected_categories: tuple[str, ...] | None
    details: Mapping[str, object]

    @property
    def verified(self) -> bool:
        return self.status.startswith("verified_")

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status,
            "kind": self.kind,
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "manifest_sha256": self.manifest_sha256,
            "details": dict(self.details),
        }
        return payload


@dataclass(frozen=True)
class SegmentAlignmentContract:
    """Mapping from exported analysis IDs to source Whisper positions."""

    status: str
    manifest_path: Path | None
    manifest_sha256: str | None
    source_indexes: Mapping[int, int]
    source_segment_ids: Mapping[int, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "manifest_sha256": self.manifest_sha256,
            "segments": len(self.source_indexes),
        }


def inspect_upstream_provenance(
    input_dir: Path,
    csv_paths: Sequence[Path],
) -> UpstreamProvenance:
    """Validate the strongest manifest available beside ``input_dir``.

    The adapter's batch manifest contains a complete CSV inventory.  The
    mechanically derived core view has a smaller manifest that records its
    category set and file count.  Inputs without either remain supported for
    manual/legacy use, but are explicitly labelled unverified and can never be
    reported as provenance-verified.
    """

    adapter_manifest = input_dir / "_manifests" / "rocksteady_run_manifest.json"
    derived_manifest = input_dir / "derived_view_manifest.json"
    if adapter_manifest.is_file():
        return _inspect_adapter_manifest(input_dir, csv_paths, adapter_manifest)
    if derived_manifest.is_file():
        return _inspect_derived_manifest(input_dir, csv_paths, derived_manifest)
    return UpstreamProvenance(
        status="legacy_unverified",
        kind="standalone-rocksteady-csv",
        manifest_path=None,
        manifest_sha256=None,
        expected_categories=None,
        details={
            "reason": "No supported upstream manifest was found beside the CSV root.",
            "csv_files": len(csv_paths),
        },
    )


def load_segment_alignment_contract(
    prepare_root: Path,
    *,
    country: str,
    speaker: str,
    video: str,
    upstream_verified: bool,
    legacy_segment_count: int,
) -> SegmentAlignmentContract:
    """Read the preparation-stage identity mapping for one video.

    Version 2 maps the contiguous one-based IDs sent to RockSteady back to the
    original zero-based Whisper list positions.  Verified pipeline inputs must
    have this evidence; manifest-less standalone inputs retain positional
    compatibility but are explicitly marked ``legacy_unverified``.
    """

    manifest_path = prepare_root / country / speaker / video / ".prepare_manifest.json"
    if not manifest_path.is_file():
        if upstream_verified:
            raise ValueError(
                "Verified RockSteady inputs require a preparation mapping, but it is missing: "
                f"{manifest_path}. Re-run the prepare stage before postprocessing."
            )
        return SegmentAlignmentContract(
            status="legacy_unverified",
            manifest_path=None,
            manifest_sha256=None,
            source_indexes={index: index - 1 for index in range(1, legacy_segment_count + 1)},
            source_segment_ids={index: None for index in range(1, legacy_segment_count + 1)},
        )

    manifest = _read_json_object(manifest_path)
    if manifest.get("schema_version") != "2.0":
        raise ValueError(
            f"A present prepare mapping must use schema 2.0: {manifest_path}. "
            "Re-run the prepare stage; positional fallback is only used when no mapping exists."
        )

    expected_identity = "/".join(part for part in (country, speaker, video) if part)
    if manifest.get("video_identity") != expected_identity:
        raise ValueError(
            f"Prepare manifest identity mismatch at {manifest_path}: "
            f"expected {expected_identity!r}, found {manifest.get('video_identity')!r}"
        )
    segment_count = _require_nonnegative_int(
        manifest.get("segment_count"), manifest_path, "segment_count"
    )
    entries = manifest.get("segments")
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise ValueError(f"Prepare manifest segments must be an object list: {manifest_path}")
    if segment_count != len(entries):
        raise ValueError(
            f"Prepare manifest segment_count differs from its mapping rows: {manifest_path}"
        )

    source_indexes: dict[int, int] = {}
    source_segment_ids: dict[int, object] = {}
    for row_number, entry in enumerate(entries, start=1):
        analysis_id = entry.get("analysis_segment_id")
        source_index = entry.get("source_segment_index")
        if isinstance(analysis_id, bool) or not isinstance(analysis_id, int) or analysis_id < 1:
            raise ValueError(
                f"Invalid analysis_segment_id in {manifest_path}, mapping row {row_number}"
            )
        if isinstance(source_index, bool) or not isinstance(source_index, int) or source_index < 0:
            raise ValueError(
                f"Invalid source_segment_index in {manifest_path}, mapping row {row_number}"
            )
        if analysis_id in source_indexes:
            raise ValueError(f"Duplicate analysis_segment_id {analysis_id} in {manifest_path}")
        source_indexes[analysis_id] = source_index
        source_segment_ids[analysis_id] = entry.get("source_segment_id")

    expected_analysis_ids = set(range(1, segment_count + 1))
    if set(source_indexes) != expected_analysis_ids:
        raise ValueError(
            f"Prepare manifest analysis_segment_id values are not contiguous 1..{segment_count}: "
            f"{manifest_path}"
        )
    if len(set(source_indexes.values())) != len(source_indexes):
        raise ValueError(f"Prepare manifest repeats a source_segment_index: {manifest_path}")

    declared_content_hash = _require_sha256(
        manifest.get("content_sha256"), manifest_path, "content_sha256"
    )
    expected_names = {
        f"{video}__segment_{analysis_id:06d}.txt"
        for analysis_id in expected_analysis_ids
    }
    actual_names = {path.name for path in manifest_path.parent.glob("*.txt")}
    if actual_names != expected_names:
        raise ValueError(
            f"Prepare text-file inventory differs from its mapping at {manifest_path}: "
            f"missing={sorted(expected_names - actual_names)[:8]}, "
            f"extra={sorted(actual_names - expected_names)[:8]}"
        )
    content_digest = hashlib.sha256()
    entries_by_analysis_id = {
        int(entry["analysis_segment_id"]): entry for entry in entries
    }
    for analysis_id in sorted(expected_analysis_ids):
        name = f"{video}__segment_{analysis_id:06d}.txt"
        try:
            text = (manifest_path.parent / name).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ValueError(
                f"Cannot read prepared segment {manifest_path.parent / name}: {error}"
            ) from error
        content_digest.update(name.encode("utf-8"))
        content_digest.update(b"\0")
        content_digest.update(text.encode("utf-8"))
        content_digest.update(b"\0")
        content_digest.update(
            json.dumps(entries_by_analysis_id[analysis_id], sort_keys=True).encode("utf-8")
        )
        content_digest.update(b"\0")
    if content_digest.hexdigest() != declared_content_hash:
        raise ValueError(f"Prepare content_sha256 does not match its files/mapping: {manifest_path}")

    return SegmentAlignmentContract(
        status="verified",
        manifest_path=manifest_path.resolve(),
        manifest_sha256=sha256_file(manifest_path),
        source_indexes=source_indexes,
        source_segment_ids=source_segment_ids,
    )


def _inspect_adapter_manifest(
    input_dir: Path,
    csv_paths: Sequence[Path],
    manifest_path: Path,
) -> UpstreamProvenance:
    manifest = _read_json_object(manifest_path)
    schema_version = manifest.get("schema_version")
    if schema_version not in {1, "1", "1.0", 2, "2", "2.0"}:
        raise ValueError(f"Unsupported RockSteady run manifest schema: {manifest_path}")
    modern_manifest = schema_version in {2, "2", "2.0"}
    if modern_manifest:
        if manifest.get("kind") != "rocksteady-analysis-batch":
            raise ValueError(f"Unexpected RockSteady run manifest kind: {manifest_path}")
        if str(manifest.get("status", "")).casefold() != "completed":
            raise ValueError(f"RockSteady run manifest is not completed: {manifest_path}")

    settings = _require_mapping(manifest.get("settings"), manifest_path, "settings")
    configured_categories = _require_string_array(
        settings.get("categories"),
        manifest_path,
        "settings.categories",
        allow_empty=True,
    )
    if str(settings.get("value_type", "")).casefold() != "total":
        raise ValueError(
            f"RockSteady manifest is not a Total-mode run: {manifest_path} "
            f"(value_type={settings.get('value_type')!r})"
        )

    summary = _require_mapping(manifest.get("summary"), manifest_path, "summary")
    videos_value = manifest.get("videos")
    if not isinstance(videos_value, list) or not all(isinstance(item, dict) for item in videos_value):
        raise ValueError(f"RockSteady manifest videos must be an object list: {manifest_path}")
    videos: list[Mapping[str, Any]] = videos_value
    inventory_sha256: str | None = None
    if modern_manifest:
        inventory_sha256 = _require_sha256(
            manifest.get("inventory_sha256"), manifest_path, "inventory_sha256"
        )
        if _inventory_digest(videos) != inventory_sha256:
            raise ValueError(
                f"RockSteady manifest inventory digest differs from its videos: {manifest_path}"
            )
    total = _require_nonnegative_int(summary.get("total"), manifest_path, "summary.total")
    completed = _require_nonnegative_int(summary.get("completed"), manifest_path, "summary.completed")
    skipped = _require_nonnegative_int(summary.get("skipped"), manifest_path, "summary.skipped")
    failed = _require_nonnegative_int(summary.get("failed"), manifest_path, "summary.failed")
    if failed or total != len(videos) or completed + skipped != total:
        raise ValueError(
            f"RockSteady manifest does not describe a complete successful batch: {manifest_path}. "
            f"summary={dict(summary)}, video_records={len(videos)}"
        )

    allowed_statuses = {"completed", "skipped"}
    invalid_statuses = [
        str(video.get("status", ""))
        for video in videos
        if str(video.get("status", "")).casefold() not in allowed_statuses
    ]
    if invalid_statuses:
        raise ValueError(
            f"RockSteady manifest contains unsuccessful video records {invalid_statuses[:5]}: "
            f"{manifest_path}"
        )

    expected_inventory = {
        _normalize_relative_path(_require_string(video.get("output"), manifest_path, "videos[].output"))
        for video in videos
    }
    if len(expected_inventory) != len(videos):
        raise ValueError(f"RockSteady manifest contains duplicate output paths: {manifest_path}")
    actual_inventory = {
        _normalize_relative_path(path.relative_to(input_dir).as_posix()) for path in csv_paths
    }
    _require_matching_inventory(manifest_path, expected_inventory, actual_inventory)
    paths_by_relative = {
        _normalize_relative_path(path.relative_to(input_dir).as_posix()): path
        for path in csv_paths
    }

    validated_category_sets: list[tuple[str, ...]] = []
    for video in videos:
        validation = _require_mapping(video.get("validation"), manifest_path, "videos[].validation")
        video_categories = _require_string_list(
            validation.get("categories"), manifest_path, "videos[].validation.categories"
        )
        validated_category_sets.append(video_categories)
        expected_rows = _require_nonnegative_int(
            validation.get("rows"), manifest_path, "videos[].validation.rows"
        )
        relative = _normalize_relative_path(
            _require_string(video.get("output"), manifest_path, "videos[].output")
        )
        if _csv_data_row_count(paths_by_relative[relative]) != expected_rows:
            raise ValueError(
                f"RockSteady CSV row count differs from {manifest_path}: {video.get('output')}"
            )
    if not validated_category_sets:
        raise ValueError(f"RockSteady manifest contains no completed video validation: {manifest_path}")
    categories = validated_category_sets[0]
    category_contract = tuple(name.casefold() for name in categories)
    for video, video_categories in zip(videos, validated_category_sets):
        if tuple(name.casefold() for name in video_categories) != category_contract:
            raise ValueError(
                f"Per-video category validation is inconsistent in {manifest_path}: "
                f"{video.get('output')}"
            )
    if configured_categories and tuple(
        name.casefold() for name in configured_categories
    ) != category_contract:
        raise ValueError(
            f"Per-video category validation differs from batch settings in {manifest_path}"
        )

    hash_fields = [_output_hash(video) for video in videos]
    if any(hash_fields) and not all(hash_fields):
        raise ValueError(f"RockSteady manifest has only a partial output-hash inventory: {manifest_path}")
    hashes_verified = bool(hash_fields and all(hash_fields))
    if hashes_verified:
        for video, expected_hash in zip(videos, hash_fields):
            relative = _normalize_relative_path(
                _require_string(video.get("output"), manifest_path, "videos[].output")
            )
            _require_sha256(expected_hash, manifest_path, "videos[].output_sha256")
            actual_hash = sha256_file(paths_by_relative[relative])
            if actual_hash.casefold() != str(expected_hash).casefold():
                raise ValueError(
                    f"RockSteady CSV hash differs from {manifest_path}: {video.get('output')}"
                )

    dictionary_records = manifest.get("dictionaries")
    rocksteady_jar = manifest.get("rocksteady_jar")
    return UpstreamProvenance(
        status="verified_sha256" if hashes_verified else "verified_inventory_only",
        kind="rocksteady-adapter-batch",
        manifest_path=manifest_path.resolve(),
        manifest_sha256=sha256_file(manifest_path),
        expected_categories=categories,
        details={
            "schema_version": manifest.get("schema_version"),
            "inventory_sha256": inventory_sha256,
            "upstream_inventory_sha256": manifest.get("upstream_inventory_sha256"),
            "analyser": settings.get("analyser"),
            "value_type": settings.get("value_type"),
            "categories": list(categories),
            "configured_categories": list(configured_categories),
            "category_selection": (
                "explicit" if configured_categories else "all-dictionary-categories"
            ),
            "dictionary_combination": settings.get("combination"),
            "dictionaries": dictionary_records if isinstance(dictionary_records, list) else [],
            "rocksteady_jar": rocksteady_jar if isinstance(rocksteady_jar, dict) else {},
            "csv_inventory_verified": True,
            "csv_hashes_verified": hashes_verified,
            "csv_files": len(actual_inventory),
        },
    )


def _inspect_derived_manifest(
    input_dir: Path,
    csv_paths: Sequence[Path],
    manifest_path: Path,
) -> UpstreamProvenance:
    manifest = _read_json_object(manifest_path)
    if manifest.get("schema_version") not in {1, "1", "1.0", 2, "2", "2.0"}:
        raise ValueError(f"Unsupported derived-view manifest schema: {manifest_path}")
    if manifest.get("kind") != "derived-rocksteady-category-view":
        raise ValueError(f"Unexpected derived-view manifest kind: {manifest_path}")
    categories = _require_string_list(manifest.get("categories"), manifest_path, "categories")
    modern_files = manifest.get("files")
    hash_status = "verified_count_only"
    inventory_detail: dict[str, object]
    if isinstance(modern_files, list):
        if not all(isinstance(item, dict) for item in modern_files):
            raise ValueError(f"Derived-view files must be an object list: {manifest_path}")
        files: list[Mapping[str, Any]] = modern_files
        status = str(manifest.get("status", "")).casefold()
        summary = _require_mapping(manifest.get("summary"), manifest_path, "summary")
        summary_total = _require_nonnegative_int(
            summary.get("total"), manifest_path, "summary.total"
        )
        summary_completed = _require_nonnegative_int(
            summary.get("completed"), manifest_path, "summary.completed"
        )
        summary_failed = _require_nonnegative_int(
            summary.get("failed"), manifest_path, "summary.failed"
        )
        if (
            status != "completed"
            or summary_failed
            or summary_total != len(files)
            or summary_completed != len(files)
        ):
            raise ValueError(f"Derived-view manifest is not a completed successful run: {manifest_path}")
        expected_inventory = {
            _normalize_relative_path(
                _require_string(item.get("output"), manifest_path, "files[].output")
            )
            for item in files
        }
        if len(expected_inventory) != len(files):
            raise ValueError(f"Derived-view manifest has duplicate output paths: {manifest_path}")
        actual_inventory = {
            _normalize_relative_path(path.relative_to(input_dir).as_posix()) for path in csv_paths
        }
        _require_matching_inventory(manifest_path, expected_inventory, actual_inventory)
        paths_by_relative = {
            _normalize_relative_path(path.relative_to(input_dir).as_posix()): path
            for path in csv_paths
        }
        for item in files:
            if str(item.get("status", "")).casefold() != "completed":
                raise ValueError(f"Derived-view file is not completed in {manifest_path}")
            relative = _normalize_relative_path(str(item.get("output")))
            expected_hash = _require_sha256(
                item.get("output_sha256"), manifest_path, "files[].output_sha256"
            )
            if sha256_file(paths_by_relative[relative]).casefold() != expected_hash.casefold():
                raise ValueError(f"Derived-view CSV hash differs from {manifest_path}: {item.get('output')}")
            expected_rows = _require_nonnegative_int(item.get("rows"), manifest_path, "files[].rows")
            if _csv_data_row_count(paths_by_relative[relative]) != expected_rows:
                raise ValueError(
                    f"Derived-view CSV row count differs from {manifest_path}: "
                    f"{item.get('output')}"
                )
        inventory_sha = _require_sha256(
            manifest.get("inventory_sha256"), manifest_path, "inventory_sha256"
        )
        if _inventory_digest(files) != inventory_sha:
            raise ValueError(f"Derived-view inventory digest differs from its files: {manifest_path}")
        hash_status = "verified_sha256"
        inventory_detail = {
            "csv_inventory_verified": True,
            "csv_hashes_verified": True,
            "inventory_sha256": inventory_sha,
        }
    else:
        expected_count = _require_nonnegative_int(
            manifest.get("csv_files"), manifest_path, "csv_files"
        )
        if expected_count != len(csv_paths):
            raise ValueError(
                f"Derived-view CSV inventory count differs from its manifest: {manifest_path}. "
                f"Expected {expected_count}, found {len(csv_paths)}."
            )
        inventory_detail = {
            "csv_inventory_count_verified": True,
            "csv_hashes_verified": False,
        }

    source_root_text = _require_string(manifest.get("source_root"), manifest_path, "source_root")
    source_root = Path(source_root_text)
    if not source_root.is_absolute():
        source_root = (manifest_path.parent / source_root).resolve()
    source_manifest = source_root / "_manifests" / "rocksteady_run_manifest.json"
    source_evidence: dict[str, object] = {
        "source_root": str(source_root),
        "source_manifest_path": str(source_manifest) if source_manifest.is_file() else None,
        "source_manifest_sha256": sha256_file(source_manifest) if source_manifest.is_file() else None,
    }

    return UpstreamProvenance(
        status=hash_status,
        kind="derived-rocksteady-category-view",
        manifest_path=manifest_path.resolve(),
        manifest_sha256=sha256_file(manifest_path),
        expected_categories=categories,
        details={
            "schema_version": manifest.get("schema_version"),
            "categories": list(categories),
            "csv_files": len(csv_paths),
            **inventory_detail,
            **source_evidence,
        },
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read upstream manifest {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Upstream manifest must contain a JSON object: {path}")
    return value


def _require_mapping(value: object, path: Path, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Upstream manifest field {field} must be an object: {path}")
    return value


def _require_string(value: object, path: Path, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Upstream manifest field {field} must be a non-empty string: {path}")
    return value.strip()


def _require_string_list(value: object, path: Path, field: str) -> tuple[str, ...]:
    return _require_string_array(value, path, field, allow_empty=False)


def _require_string_array(
    value: object,
    path: Path,
    field: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "an array" if allow_empty else "a non-empty array"
        raise ValueError(f"Upstream manifest field {field} must be {qualifier}: {path}")
    result = tuple(_require_string(item, path, field) for item in value)
    if len({item.casefold() for item in result}) != len(result):
        raise ValueError(f"Upstream manifest field {field} contains duplicate values: {path}")
    return result


def _output_hash(record: Mapping[str, Any]) -> object:
    for key in ("output_sha256", "sha256"):
        value = record.get(key)
        if value not in (None, ""):
            return value
    validation = record.get("validation")
    if isinstance(validation, dict):
        for key in ("output_sha256", "sha256"):
            value = validation.get(key)
            if value not in (None, ""):
                return value
    return None


def _require_sha256(value: object, path: Path, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdefABCDEF" for char in value
    ):
        raise ValueError(f"Upstream manifest field {field} must be a SHA-256 hex digest: {path}")
    return value.casefold()


def _inventory_digest(items: Sequence[Mapping[str, Any]]) -> str:
    canonical = json.dumps(
        list(items), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _csv_data_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for row in reader if any(cell.strip() for cell in row))


def _require_nonnegative_int(value: object, path: Path, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Upstream manifest field {field} must be a non-negative integer: {path}")
    return value


def _normalize_relative_path(value: str) -> str:
    return Path(value.replace("\\", "/")).as_posix().casefold()


def _require_matching_inventory(
    manifest_path: Path,
    expected: set[str],
    actual: set[str],
) -> None:
    if expected == actual:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    raise ValueError(
        f"RockSteady CSV inventory differs from {manifest_path}: "
        f"missing={missing[:8]}, extra={extra[:8]}"
    )
