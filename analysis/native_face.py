"""Verified Py-Feat outputs adapted to the shared Analysis report contract."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Sequence

from analysis.histograms import (
    AnalysisResult,
    ColumnInfo,
    ParsedExport,
    analyse_domain_split_parsed_exports,
)
from processing.audio_analysis.audio_pipeline.source_context import (
    RUN_SIDECAR_NAMES,
    snapshot_run_sidecars,
)
from processing.face_analysis.outputs import artifact_metadata


NATIVE_FACE_PROVIDER = "Py-Feat / Native Face"
NATIVE_FACE_EMOTIONS = (
    "Anger", "Contempt", "Disgust", "Fear", "Joy", "Sadness", "Surprise",
    "Neutral", "Confusion",
)
NATIVE_FACE_DIMENSIONS = ("Valence", "Arousal")
NATIVE_FACE_METRICS = (*NATIVE_FACE_EMOTIONS, *NATIVE_FACE_DIMENSIONS)
NATIVE_FACE_HEADER = ["Row", "Timestamp", *NATIVE_FACE_METRICS]


def analyse_native_face_folder(
    input_folder: str | Path,
    output_root: str | Path | None = None,
    *,
    write_graphs: bool = True,
    include_logscale: bool = False,
) -> AnalysisResult:
    """Build Analysis reports from verified native Face video outputs."""

    root = Path(input_folder).expanduser().resolve()
    exports = read_native_face_folder(root)
    manifests = [export.path.with_name("video_manifest.json") for export in exports]
    destination = (
        Path(os.path.abspath(Path(output_root).expanduser()))
        if output_root is not None
        else root / "analysis"
    )
    return analyse_domain_split_parsed_exports(
        input_dir=root,
        output_root=destination,
        exports=exports,
        discovery_log=[f"Selected {path.relative_to(root)}." for path in manifests],
        write_graphs=write_graphs,
        include_logscale=include_logscale,
        include_landmarks=False,
        include_timing=False,
        exclude_geometry=False,
    )


def read_native_face_folder(input_folder: str | Path) -> tuple[ParsedExport, ...]:
    """Read and bind one native Face run without writing Analysis output."""

    root = Path(input_folder).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Native Face input folder does not exist: {root}")
    manifests = sorted(root.rglob("video_manifest.json"), key=lambda path: str(path).casefold())
    if not manifests:
        raise ValueError(f"No completed native Face video manifests found under {root}")
    exports = tuple(read_native_face_export(path.with_name("face_core.csv")) for path in manifests)
    _validate_run_binding(root, manifests)
    return exports


def read_native_face_export(path: Path) -> ParsedExport:
    """Read one verified face_core.csv without importing PyArrow or Py-Feat."""

    core = Path(path).expanduser().resolve()
    manifest_path = core.with_name("video_manifest.json")
    manifest = _read_manifest(manifest_path)
    if manifest.get("status") != "completed" or manifest.get("output_contract_version") != "1.0":
        raise ValueError(f"Native Face manifest is incomplete or unsupported: {manifest_path}")
    outputs = manifest.get("outputs")
    stored = outputs.get("core") if isinstance(outputs, dict) else None
    actual = artifact_metadata(core, "core")
    if not isinstance(stored, dict) or stored != actual:
        raise ValueError(f"Native Face core artifact hash or schema does not match {manifest_path}")
    source = manifest.get("source")
    source_record = source if isinstance(source, dict) else {}
    source_id = str(source_record.get("source_id") or manifest.get("media_id") or core.parent.name)
    speaker = str(source_record.get("speaker_display") or source_record.get("speaker") or core.parent.parent.name)
    system = source_record.get("system_metadata")
    title = str(system.get("title") or "") if isinstance(system, dict) else ""
    video = title or source_id
    rows = _read_primary_rows(core)
    return ParsedExport(
        source=source_id,
        path=core,
        header=NATIVE_FACE_HEADER.copy(),
        info=build_native_face_column_info(),
        rows=rows,
        speaker=speaker,
        video=video,
    )


def build_native_face_column_info() -> dict[str, ColumnInfo]:
    info = {
        "Row": ColumnInfo("Row", "Row", "Row", "Timestamp", "Counter", "Index"),
        "Timestamp": ColumnInfo(
            "Timestamp", "Timestamp", "Timestamp", "Timestamp", "Timestamp", "Millisecond"
        ),
    }
    for name in NATIVE_FACE_EMOTIONS:
        info[name] = ColumnInfo(
            unique_name=name,
            original_name=name,
            display_name=name,
            category="NATIVE FACE(Py-Feat Emotion)",
            group="Emotion",
            unit="Index",
            description=(
                f"Py-Feat primary-face probability for {name}, scaled from 0-1 to 0-100."
                if name not in {"Contempt", "Confusion"}
                else f"{name} is unsupported by the native Py-Feat contract and remains blank."
            ),
            provided_by=NATIVE_FACE_PROVIDER,
            channel_identifier=f"NATIVE_FACE_Emotion_{name}",
            scale_hint="0_to_100",
        )
    for name in NATIVE_FACE_DIMENSIONS:
        info[name] = ColumnInfo(
            unique_name=name,
            original_name=name,
            display_name=name,
            category="NATIVE FACE(Py-Feat Affect)",
            group="Affect",
            unit="Index",
            description=f"Py-Feat primary-face {name}, scaled from -1..1 to -100..100.",
            provided_by=NATIVE_FACE_PROVIDER,
            channel_identifier=f"NATIVE_FACE_Affect_{name}",
            scale_hint="minus100_to_100",
        )
    return info


def _read_primary_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, raw in enumerate(reader, start=2):
            if not _truthy(raw.get("face_detected")) or not _truthy(raw.get("is_primary_face")):
                continue
            rows.append(
                {
                    "Row": str(len(rows) + 1),
                    "Timestamp": _scaled(raw.get("timestamp_seconds"), 1000, 0, None, row_number, "timestamp_seconds"),
                    "Anger": _scaled(raw.get("Anger"), 100, 0, 1, row_number, "Anger"),
                    "Contempt": "",
                    "Disgust": _scaled(raw.get("Disgust"), 100, 0, 1, row_number, "Disgust"),
                    "Fear": _scaled(raw.get("Fear"), 100, 0, 1, row_number, "Fear"),
                    "Joy": _scaled(raw.get("Happy"), 100, 0, 1, row_number, "Happy"),
                    "Sadness": _scaled(raw.get("Sad"), 100, 0, 1, row_number, "Sad"),
                    "Surprise": _scaled(raw.get("Surprise"), 100, 0, 1, row_number, "Surprise"),
                    "Neutral": _scaled(raw.get("Neutral"), 100, 0, 1, row_number, "Neutral"),
                    "Confusion": "",
                    "Valence": _scaled(raw.get("valence"), 100, -1, 1, row_number, "valence"),
                    "Arousal": _scaled(raw.get("arousal"), 100, -1, 1, row_number, "arousal"),
                }
            )
    return rows


def _scaled(
    raw: object,
    multiplier: float,
    lower: float,
    upper: float | None,
    row_number: int,
    field: str,
) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"Native Face row {row_number} {field} must be numeric or blank") from exc
    if not math.isfinite(value) or value < lower or (upper is not None and value > upper):
        range_text = f"{lower:g}..{upper:g}" if upper is not None else f">={lower:g}"
        raise ValueError(f"Native Face row {row_number} {field} must be in {range_text}")
    return f"{value * multiplier:.12g}"


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes"}


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read native Face manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Native Face manifest must be an object: {path}")
    return payload


def _validate_run_binding(root: Path, manifests: Sequence[Path]) -> None:
    run_manifest_path = root / "run_manifest.json"
    manifest_payloads = [(path, _read_manifest(path)) for path in manifests]
    completed: list[str] = []
    catalog_bindings: list[tuple[Path, dict[str, object]]] = []
    for path, payload in manifest_payloads:
        source = payload.get("source")
        source_record = source if isinstance(source, dict) else {}
        source_id = str(source_record.get("source_id") or "")
        if source_id:
            completed.append(source_id)
        digest = str(source_record.get("catalog_sha256") or "")
        context = source_record.get("source_context")
        context_sha256 = str(source_record.get("source_context_sha256") or "")
        has_catalog_evidence = bool(digest or context or context_sha256)
        if not has_catalog_evidence:
            continue
        if not source_id or not digest or not isinstance(context, dict) or not context_sha256:
            raise ValueError(f"Native Face catalog binding is incomplete: {path}")
        canonical = json.dumps(
            context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != context_sha256:
            raise ValueError(f"Native Face source context hash does not match: {path}")
        if str(context.get("source_id") or "") != source_id:
            raise ValueError(f"Native Face source context SourceID does not match: {path}")
        if str(context.get("catalog_sha256") or "") != digest:
            raise ValueError(f"Native Face source context catalog digest does not match: {path}")
        for field in (
            "speaker",
            "speaker_display",
            "user_metadata",
            "system_metadata",
            "output_mapping",
        ):
            if source_record.get(field) != context.get(field):
                raise ValueError(
                    f"Native Face outer source field {field} does not match its validated context: {path}"
                )
        catalog_bindings.append((path.with_name("face_core.csv"), dict(context)))

    sidecar_evidence = any(_lexical_entry_exists(root / name) for name in RUN_SIDECAR_NAMES)
    if not run_manifest_path.exists():
        if catalog_bindings or sidecar_evidence:
            raise ValueError("Native Face catalog evidence requires the root run manifest")
        return
    run = _read_manifest(run_manifest_path)
    if run.get("status") not in {"completed", "completed_with_errors"}:
        raise ValueError("Native Face run manifest is not complete")
    raw_expected = run.get("processed_source_ids", [])
    if not isinstance(raw_expected, list):
        raise ValueError("Native Face run manifest processed SourceIDs must be a list")
    expected = tuple(str(value) for value in raw_expected)
    if any(not value for value in expected) or len(expected) != len(set(expected)):
        raise ValueError("Native Face run manifest has invalid or duplicate processed SourceIDs")
    if expected and (len(completed) != len(set(completed)) or set(completed) != set(expected)):
        raise ValueError("Native Face completed SourceIDs do not match the run manifest")
    digest = str(run.get("catalog_sha256") or "")
    has_catalog_evidence = bool(digest or expected or catalog_bindings or sidecar_evidence)
    if has_catalog_evidence:
        if not digest or not expected or len(catalog_bindings) != len(manifest_payloads):
            raise ValueError("Native Face run has incomplete catalog binding")
        for path, payload in manifest_payloads:
            source = payload.get("source")
            source_digest = str(source.get("catalog_sha256") or "") if isinstance(source, dict) else ""
            if source_digest != digest:
                raise ValueError(f"Native Face video catalog digest does not match the run manifest: {path}")
        snapshot_run_sidecars(
            root,
            expected_source_ids=set(expected),
            source_bindings=catalog_bindings,
            require_mapped_input_paths=False,
            expected_catalog_sha256=digest,
        )


def _lexical_entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Postprocess verified Py-Feat / Native Face outputs."
    )
    parser.add_argument("input_folder", type=Path)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--no-graphs", action="store_true")
    parser.add_argument("--logscale", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = analyse_native_face_folder(
        args.input_folder,
        output_root=args.output_root,
        write_graphs=not args.no_graphs,
        include_logscale=args.logscale,
    )
    print(f"Output folder: {result.output_dir}")
    print(f"Provider: {NATIVE_FACE_PROVIDER}")
    print(f"Report files: {len(result.histogram_paths)} histogram CSV/XLSX outputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
