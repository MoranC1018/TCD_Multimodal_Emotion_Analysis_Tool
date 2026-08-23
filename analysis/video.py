"""Provider detection boundary for canonical Video Analysis."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from analysis.imotions import inspect_imotions_csv, read_imotions_video_folder
from analysis.native_face import read_native_face_folder
from analysis.histograms import ColumnInfo, ParsedExport
from analysis.video_contract import (
    VIDEO_COMMON_METRICS,
    VIDEO_METRICS,
    VIDEO_NORMALIZATION_VERSION,
    VideoProvider,
    available_video_metrics,
    video_measure_guide_rows,
)


VideoSourceMethod = Literal["run", "import"]


@dataclass(frozen=True)
class DetectedVideoSource:
    provider: VideoProvider
    source_path: Path
    source_method: VideoSourceMethod
    evidence: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    source_format: Literal["raw", "analysis_report"] = "raw"


@dataclass(frozen=True)
class VideoMetricProvenance:
    source_id: str
    canonical_measure: str
    original_field: str
    channel_identifier: str


@dataclass(frozen=True)
class VideoOutputProvenance:
    """Immutable, JSON-ready provenance for one canonical Video input boundary."""

    requested_modality: Literal["video"]
    resolved_provider: VideoProvider
    source_method: VideoSourceMethod
    source_path: Path
    detection_evidence: tuple[str, ...]
    detection_warnings: tuple[str, ...]
    normalization_contract_version: str
    canonical_availability: tuple[dict[str, str], ...]
    original_columns: tuple[VideoMetricProvenance, ...]

    def to_manifest_payload(self) -> dict[str, object]:
        return {
            "requested_modality": self.requested_modality,
            "resolved_provider": self.resolved_provider,
            "source_method": self.source_method,
            "source_path": str(self.source_path),
            "detection_evidence": list(self.detection_evidence),
            "detection_warnings": list(self.detection_warnings),
            "normalization_contract_version": self.normalization_contract_version,
            "canonical_availability": [dict(row) for row in self.canonical_availability],
            "original_columns": [
                {
                    "source_id": item.source_id,
                    "canonical_measure": item.canonical_measure,
                    "original_field": item.original_field,
                    "channel_identifier": item.channel_identifier,
                }
                for item in self.original_columns
            ],
        }

    def to_column_manifest_rows(self) -> tuple[dict[str, str], ...]:
        rows: list[dict[str, str]] = []
        for availability in self.canonical_availability:
            metric = availability["canonical_measure"]
            actual = tuple(
                item for item in self.original_columns if item.canonical_measure == metric
            )
            rows.append(
                {
                    "requested_modality": self.requested_modality,
                    "resolved_provider": self.resolved_provider,
                    "source_method": self.source_method,
                    "source_path": str(self.source_path),
                    "detection_evidence": " | ".join(self.detection_evidence),
                    "detection_warnings": " | ".join(self.detection_warnings),
                    "normalization_contract_version": self.normalization_contract_version,
                    **availability,
                    "original_provider_fields": " | ".join(
                        dict.fromkeys(item.original_field for item in actual)
                    ),
                    "channel_identifiers": " | ".join(
                        dict.fromkeys(item.channel_identifier for item in actual)
                    ),
                }
            )
        return tuple(rows)


@dataclass(frozen=True)
class CanonicalVideoResult:
    provider: VideoProvider
    source_ids: tuple[str, ...]
    rows: tuple[dict[str, float | None], ...]
    evidence: tuple[str, ...]
    warnings: tuple[str, ...]
    normalization_version: str
    provenance: tuple[VideoMetricProvenance, ...] = ()

    def output_provenance(
        self, detected: DetectedVideoSource
    ) -> VideoOutputProvenance:
        """Bind detection evidence to normalized output without inspecting worksheets."""

        if detected.provider != self.provider:
            raise ValueError(
                "Detected Video provider does not match the canonical result provider"
            )
        if detected.evidence != self.evidence or detected.warnings != self.warnings:
            raise ValueError(
                "Detected Video evidence or warnings do not match the canonical result"
            )
        return VideoOutputProvenance(
            requested_modality="video",
            resolved_provider=self.provider,
            source_method=detected.source_method,
            source_path=detected.source_path,
            detection_evidence=self.evidence,
            detection_warnings=self.warnings,
            normalization_contract_version=self.normalization_version,
            canonical_availability=video_measure_guide_rows(self.provider),
            original_columns=self.provenance,
        )


def load_canonical_video(detected: DetectedVideoSource) -> CanonicalVideoResult:
    """Load one detected provider into source-level canonical Video rows."""

    if detected.source_method == "import":
        providers = _imported_manifest_providers(detected.source_path)
        contradictory = tuple(provider for provider in providers if provider != detected.provider)
        if contradictory:
            raise ValueError(
                "Imported Video has contradictory provider metadata for detected provider "
                f"{detected.provider!r}: {', '.join(contradictory)}"
            )
    if detected.provider == "pyfeat_native_face":
        exports = (
            _read_pyfeat_analysis_reports(detected.source_path)
            if detected.source_format == "analysis_report"
            else read_native_face_folder(detected.source_path)
        )
    elif detected.provider == "imotions_affdex":
        exports = read_imotions_video_folder(
            detected.source_path,
            allow_legacy_reports=detected.source_method == "import",
        )
    else:
        raise ValueError(f"Unsupported Video provider: {detected.provider!r}")
    ordered = sorted(exports, key=lambda export: _natural_key(export.source))
    return _canonical_result(detected, ordered)


def validate_video_reference_override_keys(keys: Sequence[str]) -> tuple[str, ...]:
    """Reject removed provider-sheet aliases with an exact canonical migration target."""

    validated = tuple(str(key) for key in keys)
    removed = {
        "nativeface",
        "pyfeatnativeface",
        "videoimotions",
        "imotionsvideo",
    }
    for key in validated:
        sheet, separator, metric = key.partition("|")
        if _normalized(sheet) not in removed:
            continue
        replacement = f"Video|{metric}" if separator else "Video"
        raise ValueError(
            f"Reference override {key!r} targets a removed provider-specific Video sheet; "
            f"use {replacement!r} instead. Provider identity is now recorded in provenance."
        )
    return validated


def _canonical_result(
    detected: DetectedVideoSource,
    exports: Sequence[ParsedExport],
) -> CanonicalVideoResult:
    rows: list[dict[str, float | None]] = []
    provenance: list[VideoMetricProvenance] = []
    available = available_video_metrics(detected.provider)
    for export in exports:
        row: dict[str, float | None] = {}
        for metric in VIDEO_METRICS:
            values = [_optional_number(item.get(metric)) for item in export.rows]
            present = [value for value in values if value is not None]
            row[metric] = sum(present) / len(present) if present else None
            info = export.info.get(metric)
            if info is not None and metric in available:
                provenance.append(
                    VideoMetricProvenance(
                        source_id=export.source,
                        canonical_measure=metric,
                        original_field=info.original_name,
                        channel_identifier=info.channel_identifier,
                    )
                )
        rows.append(row)
    return CanonicalVideoResult(
        provider=detected.provider,
        source_ids=tuple(export.source for export in exports),
        rows=tuple(rows),
        evidence=detected.evidence,
        warnings=detected.warnings,
        normalization_version=VIDEO_NORMALIZATION_VERSION,
        provenance=tuple(provenance),
    )


def _optional_number(value: object) -> float | None:
    text = str(value or "").strip()
    return float(text) if text else None


def _natural_key(value: str) -> tuple[tuple[int, object], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    )


def detect_video_source(
    source_path: Path,
    source_method: VideoSourceMethod,
) -> DetectedVideoSource:
    """Resolve exactly one supported Video provider without writing to its tree."""

    if source_method not in {"run", "import"}:
        raise ValueError(f"Unsupported Video source method: {source_method!r}")
    root = Path(source_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise NotADirectoryError(f"Video source folder does not exist: {root}")

    imported_providers: dict[VideoProvider, list[Path]] = {}
    if source_method == "import":
        imported_providers = _imported_manifest_providers(root)
        if len(imported_providers) > 1:
            paths = sorted(
                {path.relative_to(root).as_posix() for values in imported_providers.values() for path in values}
            )
            raise ValueError(
                "Source has conflicting imported Video provider metadata in: "
                + ", ".join(paths)
            )

    native_metadata = _native_provider_metadata(root)
    bound_video_manifests = _bound_face_video_manifests(root)
    bound_run_manifests = _bound_face_run_manifests(root)
    raw_native_signature = bool(
        next(root.rglob("face_core.csv"), None)
        or bound_video_manifests
        or bound_run_manifests
    )

    native_evidence: list[str] = []
    native_source_format: Literal["raw", "analysis_report"] = "raw"
    if raw_native_signature:
        try:
            exports = read_native_face_folder(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"Py-Feat / Native Face validation failed: {exc}") from exc
        if source_method == "import" and imported_providers.get("pyfeat_native_face"):
            try:
                _read_pyfeat_analysis_reports(root)
            except (OSError, RuntimeError, ValueError) as exc:
                raise ValueError(f"Py-Feat Analysis report validation failed: {exc}") from exc
            raise ValueError(
                "Py-Feat import root contains both raw artifacts and provider-tagged "
                "Analysis reports; select exactly one format root."
            )
        native_evidence.append(
            "Verified Py-Feat / Native Face run "
            f"({len(exports)} completed video manifest{'s' if len(exports) != 1 else ''})."
        )
        native_evidence.extend(
            f"Verified native artifact: {export.path.relative_to(root).as_posix()}"
            for export in exports
        )
        native_evidence.extend(
            f"Native provider metadata: {path.relative_to(root).as_posix()}"
            for path in native_metadata
        )
        native_evidence.extend(
            f"Bound native Face video manifest: {path.relative_to(root).as_posix()}"
            for path in bound_video_manifests
        )
        native_evidence.extend(
            f"Bound native Face run manifest: {path.relative_to(root).as_posix()}"
            for path in bound_run_manifests
        )
    elif source_method == "import" and imported_providers.get("pyfeat_native_face"):
        try:
            exports = _read_pyfeat_analysis_reports(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"Py-Feat Analysis report validation failed: {exc}") from exc
        native_source_format = "analysis_report"
        native_evidence.append(
            "Validated provider-tagged Py-Feat Analysis reports "
            f"({len(exports)} source{'s' if len(exports) != 1 else ''})."
        )
        native_evidence.extend(
            f"Authoritative Py-Feat report metadata: {path.relative_to(root).as_posix()}"
            for path in imported_providers["pyfeat_native_face"]
        )
        native_evidence.extend(
            f"Validated Py-Feat report: {export.path.relative_to(root).as_posix()}"
            for export in exports
        )
    elif native_metadata or imported_providers.get("pyfeat_native_face"):
        try:
            read_native_face_folder(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"Py-Feat / Native Face validation failed: {exc}") from exc

    imotions_evidence = _accepted_imotions_csv_evidence(root)
    imotions_evidence.extend(
        f"Authoritative iMotions provider metadata: {path.relative_to(root).as_posix()}"
        for path in imported_providers.get("imotions_affdex", [])
    )

    warnings: list[str] = []
    if not imotions_evidence and source_method == "import":
        legacy_reports = _legacy_imotions_reports(root)
        if legacy_reports:
            imotions_evidence.extend(
                f"Legacy iMotions report shape: {path.relative_to(root).as_posix()}"
                for path in legacy_reports
            )
            warnings.append(
                "Legacy iMotions report-shape inference was used; add authoritative "
                "column_manifest.csv provider metadata."
            )

    resolved: list[VideoProvider] = []
    if native_evidence:
        resolved.append("pyfeat_native_face")
    if imotions_evidence:
        resolved.append("imotions_affdex")
    if len(resolved) == 2:
        raise ValueError(
            "Source resolves to both supported Video providers (iMotions AFFDEX and "
            "Py-Feat / Native Face); select a root containing exactly one provider."
        )
    if not resolved:
        raise ValueError(
            "No supported Video provider evidence found. Expected iMotions CSV headers "
            "with usable data rows, or verified Py-Feat / Native Face artifacts including "
            "face_core.csv and bound video/run manifests."
        )

    provider = resolved[0]
    evidence = native_evidence if provider == "pyfeat_native_face" else imotions_evidence
    return DetectedVideoSource(
        provider=provider,
        source_path=root,
        source_method=source_method,
        evidence=tuple(evidence),
        source_format=native_source_format if provider == "pyfeat_native_face" else "raw",
        warnings=tuple(warnings),
    )


def _accepted_imotions_csv_evidence(root: Path) -> list[str]:
    evidence: list[str] = []
    for path in sorted(root.rglob("*.csv"), key=lambda item: str(item).casefold()):
        try:
            _metadata, _header, data_rows = inspect_imotions_csv(path, "utf-8-sig")
        except (OSError, UnicodeError, ValueError):
            continue
        if data_rows > 0:
            evidence.append(
                f"Accepted iMotions CSV: {path.relative_to(root).as_posix()} "
                f"({data_rows} usable data row{'s' if data_rows != 1 else ''})."
            )
    return evidence


def _imported_manifest_providers(root: Path) -> dict[VideoProvider, list[Path]]:
    providers: dict[VideoProvider, list[Path]] = {}
    for path in sorted(root.rglob("column_manifest.csv"), key=lambda item: str(item).casefold()):
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    continue
                provider_column = next(
                    (
                        name
                        for name in reader.fieldnames
                        if _normalized(name)
                        in {"provider", "providedby", "resolvedprovider", "videoprovider"}
                    ),
                    None,
                )
                if provider_column is None:
                    continue
                for index, row in enumerate(reader):
                    if index >= 100_000:
                        raise ValueError(f"Imported column manifest has too many rows: {path}")
                    provider = _provider_from_label(row.get(provider_column, ""))
                    if provider is not None:
                        providers.setdefault(provider, []).append(path)
        except (OSError, csv.Error) as exc:
            raise ValueError(f"Cannot read imported Video column manifest {path}: {exc}") from exc
    return {provider: list(dict.fromkeys(paths)) for provider, paths in providers.items()}


def _read_pyfeat_analysis_reports(root: Path) -> tuple[ParsedExport, ...]:
    """Read authoritative Py-Feat Analysis reports through the shared report contract."""

    from analysis.combined_summary import (
        discover_combined_sources_audited,
        validate_report,
    )

    discovery = discover_combined_sources_audited(root, "native_face")
    if discovery.errors:
        raise ValueError(discovery.errors[0])
    if not discovery.sources:
        raise ValueError(
            "No valid speaker-level Py-Feat descriptive_statistics.csv reports were found"
        )

    provider: VideoProvider = "pyfeat_native_face"
    required = tuple(metric for metric in VIDEO_METRICS if metric in available_video_metrics(provider))
    validated_reports = []
    for combined_source in discovery.sources:
        report_path = combined_source.report_path
        report = validate_report(
            report_path,
            "video",
            video_provider=provider,
        )
        template = report[required[0]]
        source_ids = tuple(
            source_id
            for source_id, is_available in zip(template.sources, template.available)
            if is_available
        )
        if not source_ids or any(not source_id for source_id in source_ids):
            raise ValueError(f"{report_path}: Py-Feat report has no unambiguous SourceIDs")
        column_info = _read_provider_report_column_info(
            report_path.with_name("column_manifest.csv"),
            provider,
            source_ids,
            required,
        )
        validated_reports.append((combined_source, report, source_ids, column_info))

    source_id_maps = canonical_report_source_id_maps(
        tuple(
            (combined_source.report_path, combined_source.display_name, source_ids)
            for combined_source, _report, source_ids, _column_info in validated_reports
        )
    )
    exports: list[ParsedExport] = []
    for combined_source, report, _source_ids, column_info in validated_reports:
        report_path = combined_source.report_path
        template = report[required[0]]
        source_id_map = source_id_maps[report_path]
        for index, (source_id, is_available) in enumerate(
            zip(template.sources, template.available)
        ):
            if not is_available:
                continue
            canonical_source_id = source_id_map[source_id]
            row: dict[str, str] = {}
            info: dict[str, ColumnInfo] = {}
            for metric in required:
                series = report[metric]
                if (
                    index >= len(series.available)
                    or not series.available[index]
                    or series.counts[index] <= 0
                ):
                    raise ValueError(
                        f"{report_path}: required Py-Feat metric {metric} has no usable "
                        f"observations for SourceID {source_id!r}"
                    )
                row[metric] = f"{series.means[index]:.12g}"
                info[metric] = column_info[(source_id, metric)]
            exports.append(
                ParsedExport(
                    source=canonical_source_id,
                    path=report_path,
                    header=list(required),
                    info=info,
                    rows=[row],
                    speaker=combined_source.display_name,
                    video=canonical_source_id,
                )
            )
    if not exports:
        raise ValueError("Provider-tagged Py-Feat reports contain no usable sources")
    return tuple(exports)


def canonical_report_source_id_maps(
    reports: Sequence[tuple[Path, str, Sequence[str]]],
) -> dict[Path, dict[str, str]]:
    """Namespace only local report SourceIDs that collide across speaker reports."""

    report_paths_by_source: dict[str, set[Path]] = {}
    for report_path, _display_name, source_ids in reports:
        if any(not source_id for source_id in source_ids):
            raise ValueError(f"Py-Feat report has a blank local SourceID: {report_path}")
        if len(set(source_ids)) != len(source_ids):
            raise ValueError(
                f"Provider-tagged Py-Feat report repeats a local SourceID: {report_path}"
            )
        for source_id in source_ids:
            report_paths_by_source.setdefault(source_id, set()).add(report_path)

    result: dict[Path, dict[str, str]] = {}
    canonical_paths: dict[str, Path] = {}
    for report_path, display_name, source_ids in reports:
        context = " ".join(display_name.strip().split())
        if not context:
            raise ValueError(f"Py-Feat report has no speaker identity: {report_path}")
        mapping: dict[str, str] = {}
        for source_id in source_ids:
            canonical = (
                f"{context}::{source_id}"
                if len(report_paths_by_source[source_id]) > 1
                else source_id
            )
            previous = canonical_paths.get(canonical)
            if previous is not None and previous != report_path:
                raise ValueError(
                    "Provider-tagged Py-Feat source identities remain ambiguous after "
                    f"speaker namespacing: {canonical!r} in {previous} and {report_path}"
                )
            canonical_paths[canonical] = report_path
            mapping[source_id] = canonical
        result[report_path] = mapping
    return result


def _read_provider_report_column_info(
    path: Path,
    provider: VideoProvider,
    source_ids: Sequence[str],
    required_metrics: Sequence[str],
) -> dict[tuple[str, str], ColumnInfo]:
    """Bind report means to authoritative provider/channel metadata."""

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError(f"Provider-tagged report column manifest is empty: {path}")
            fields = {_normalized(name): name for name in reader.fieldnames}
            provider_field = next(
                (
                    fields[name]
                    for name in ("providedby", "provider", "resolvedprovider", "videoprovider")
                    if name in fields
                ),
                None,
            )
            source_field = fields.get("source") or fields.get("sourceid")
            statistic_field = fields.get("statistic") or fields.get("canonicalmeasure")
            original_field = fields.get("sourcecolumn") or fields.get("originalfield")
            if provider_field is None or source_field is None or statistic_field is None:
                raise ValueError(
                    "Provider-tagged report column manifest must include provider, source, "
                    f"and statistic fields: {path}"
                )
            expected_sources = set(source_ids)
            expected_metrics = set(required_metrics)
            result: dict[tuple[str, str], ColumnInfo] = {}
            for index, row in enumerate(reader):
                if index >= 100_000:
                    raise ValueError(f"Imported column manifest has too many rows: {path}")
                raw_provider = str(row.get(provider_field, "") or "").strip()
                row_provider = _provider_from_label(raw_provider)
                if row_provider is None:
                    continue
                if row_provider != provider:
                    raise ValueError(
                        f"Contradictory provider metadata in {path}: {raw_provider!r}"
                    )
                source_id = str(row.get(source_field, "") or "").strip()
                metric = _canonical_report_metric(row.get(statistic_field, ""))
                if source_id not in expected_sources or metric not in expected_metrics:
                    continue
                original = (
                    str(row.get(original_field, "") or "").strip()
                    if original_field is not None
                    else ""
                ) or metric
                channel_field = fields.get("channelidentifier")
                channel = (
                    str(row.get(channel_field, "") or "").strip()
                    if channel_field is not None
                    else ""
                ) or original
                candidate = ColumnInfo(
                    unique_name=metric,
                    original_name=original,
                    display_name=metric,
                    category=str(row.get(fields.get("category", ""), "") or "").strip(),
                    group=str(row.get(fields.get("group", ""), "") or "").strip(),
                    unit=str(row.get(fields.get("unit", ""), "") or "").strip(),
                    description=str(
                        row.get(fields.get("description", ""), "") or ""
                    ).strip(),
                    provided_by=raw_provider,
                    channel_identifier=channel,
                    scale_hint=str(
                        row.get(fields.get("scalehint", ""), "") or ""
                    ).strip(),
                )
                key = (source_id, metric)
                previous = result.get(key)
                if previous is not None and previous != candidate:
                    raise ValueError(
                        f"Ambiguous provider metadata for SourceID {source_id!r} "
                        f"metric {metric!r} in {path}"
                    )
                result[key] = candidate
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"Cannot read provider-tagged report column manifest {path}: {exc}") from exc

    missing = [
        f"{source_id}:{metric}"
        for source_id in source_ids
        for metric in required_metrics
        if (source_id, metric) not in result
    ]
    if missing:
        preview = ", ".join(missing[:8])
        suffix = " ..." if len(missing) > 8 else ""
        raise ValueError(
            f"{path}: missing required provider-tagged Py-Feat column metadata: "
            f"{preview}{suffix}"
        )
    return result


def _canonical_report_metric(value: object) -> str | None:
    text = str(value or "").strip()
    aliases = {"happy": "Joy", "sad": "Sadness"}
    canonical = aliases.get(text.casefold(), text)
    return canonical if canonical in VIDEO_METRICS else None


def _native_provider_metadata(root: Path) -> list[Path]:
    matches: list[Path] = []
    for path in sorted(root.rglob("*.json"), key=lambda item: str(item).casefold()):
        try:
            if path.stat().st_size > 2_000_000:
                continue
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if _payload_declares_provider(payload, "pyfeat_native_face"):
            matches.append(path)
    return matches


def _bound_face_video_manifests(root: Path) -> list[Path]:
    matches: list[Path] = []
    for path in sorted(root.rglob("video_manifest.json"), key=lambda item: str(item).casefold()):
        try:
            if path.stat().st_size > 2_000_000:
                continue
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        outputs = payload.get("outputs")
        core = outputs.get("core") if isinstance(outputs, dict) else None
        if (
            payload.get("output_contract_version") == "1.0"
            and isinstance(core, dict)
            and core.get("path") == "face_core.csv"
        ):
            matches.append(path)
    return matches


def _bound_face_run_manifests(root: Path) -> list[Path]:
    matches: list[Path] = []
    for path in sorted(root.rglob("run_manifest.json"), key=lambda item: str(item).casefold()):
        try:
            if path.stat().st_size > 2_000_000:
                continue
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        outputs = payload.get("outputs") if isinstance(payload, dict) else None
        per_video = outputs.get("per_video") if isinstance(outputs, dict) else None
        if not isinstance(per_video, dict):
            continue
        if (
            per_video.get("core") == "face_core.csv"
            and per_video.get("manifest") == "video_manifest.json"
        ):
            matches.append(path)
    return matches


def _payload_declares_provider(payload: object, wanted: VideoProvider) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = _normalized(str(key))
            if normalized_key in {"provider", "providedby", "resolvedprovider", "videoprovider"}:
                if _provider_from_label(str(value)) == wanted:
                    return True
            if isinstance(value, (dict, list)) and _payload_declares_provider(value, wanted):
                return True
    elif isinstance(payload, list):
        return any(_payload_declares_provider(item, wanted) for item in payload)
    return False


def _provider_from_label(label: str) -> VideoProvider | None:
    normalized = _normalized(label)
    if any(token in normalized for token in ("imotions", "affdex", "affectiva")):
        return "imotions_affdex"
    if any(token in normalized for token in ("pyfeat", "nativeface")):
        return "pyfeat_native_face"
    return None


def _legacy_imotions_reports(root: Path) -> list[Path]:
    provider_specific = {
        "Sentimentality", "Adaptive Valence", "Engagement", "Adaptive Engagement",
    }
    matches: list[Path] = []
    for path in sorted(root.rglob("descriptive_statistics.csv"), key=lambda item: str(item).casefold()):
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                first_cells: set[str] = set()
                cells: set[str] = set()
                for index, row in enumerate(csv.reader(handle)):
                    if index >= 10_000:
                        break
                    if row and row[0].strip():
                        first_cells.add(row[0].strip())
                    cells.update(cell.strip() for cell in row if cell.strip())
        except (OSError, csv.Error):
            continue
        has_imotions_metadata = any(value.casefold().startswith("fea(") for value in cells)
        has_video_measure = bool(
            first_cells & (set(VIDEO_COMMON_METRICS) | provider_specific)
        )
        if has_imotions_metadata and has_video_measure:
            matches.append(path)
    return matches


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())
