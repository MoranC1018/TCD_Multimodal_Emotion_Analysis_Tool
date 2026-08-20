#!/usr/bin/env python3
"""Reconstruct canonical short-video iMotions CSVs from segment manifests.

The delivery manifest supplies exact video IDs and output names. Full FEA
exports are streamed through the shared segment trimmer. Timing-only source
exports are rebuilt as honest four-row SlideEvents timelines; no facial values
are invented where the source export contains none.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import trim_imotions_sensor_data as trim  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-manifest", required=True)
    parser.add_argument("--metadata-root", required=True)
    parser.add_argument("--report-root", required=True)
    parser.add_argument("--gap-seconds-fallback", type=float, default=0.5)
    return parser.parse_args()


def read_manifest(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def write_manifest(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def make_mapping(row: dict[str, str], record: trim.ManifestRecord) -> trim.CsvMapping:
    sensor = trim.SensorCsv(
        path=Path(row["sensor_csv_full_source"]),
        number=int(row["source_order"]),
        speaker=row["speaker"],
        date_token=row["date_token"],
    )
    video = trim.DocxVideo(
        speaker=row["speaker"],
        video_id=row["video_id"],
        date_digits=row["date_token"],
        order_index=int(row["speaker_order"]) - 1,
        source="canonical_delivery_manifest",
    )
    return trim.CsvMapping(sensor, record, "exact_video_id", video)


def source_has_fea(path: Path) -> bool:
    """Return whether the export metadata declares Affectiva FEA channels."""

    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for line_number, line in enumerate(handle):
            if "FEA(Emotions)" in line or "Affectiva AFFDEX" in line:
                return True
            if line_number >= 30:
                break
    return False


def segment_timing(
    record: trim.ManifestRecord,
    gap_seconds_fallback: float,
) -> tuple[list[dict[str, float]], float, float, float]:
    segments = trim.trim_stitch_edges(
        record.segments,
        edge_trim_seconds=trim.DEFAULT_STITCH_EDGE_TRIM_SECONDS,
        minimum_segment_seconds=trim.DEFAULT_MIN_EDGE_TRIM_SEGMENT_SECONDS,
    )
    gap_seconds = float(record.options.get("gap_seconds", gap_seconds_fallback) or gap_seconds_fallback)
    selected_seconds = sum(segment["end"] - segment["start"] for segment in segments)
    stitched_seconds = selected_seconds + max(0.0, gap_seconds) * max(0, len(segments) - 1)
    return segments, gap_seconds, selected_seconds, stitched_seconds


def reconstruct_event_only(
    row: dict[str, str],
    record: trim.ManifestRecord,
    destination: Path,
    gap_seconds_fallback: float,
) -> dict[str, object]:
    """Rebuild a SlideEvents-only export for the stitched video timeline."""

    source = Path(row["sensor_csv_full_source"])
    segments, gap_seconds, selected_seconds, stitched_seconds = segment_timing(record, gap_seconds_fallback)
    duration_ms = stitched_seconds * 1000.0

    with source.open("r", newline="", encoding="utf-8-sig", errors="replace") as source_handle:
        reader = csv.reader(source_handle)
        metadata_rows: list[list[str]] = []
        header: list[str] | None = None
        for source_row in reader:
            metadata_rows.append(source_row)
            if len(source_row) >= 2 and source_row[0] == "Row" and source_row[1] == "Timestamp":
                header = source_row
                break
    if header is None:
        raise RuntimeError(f"Could not find iMotions data header in {source}")

    column = {name: index for index, name in enumerate(header)}
    required = {"Row", "Timestamp", "SlideEvent", "Duration", "SourceStimuliName"}
    if not required.issubset(column):
        raise RuntimeError(f"Timing-only export lacks required columns: {source}")

    def event_row(index: int, timestamp_ms: float, event: str) -> list[str]:
        values = [""] * len(header)
        values[column["Row"]] = str(index)
        values[column["Timestamp"]] = trim.format_ms(timestamp_ms)
        values[column["SlideEvent"]] = event
        if "EventSource" in column:
            values[column["EventSource"]] = "1"
        if "StimType" in column:
            values[column["StimType"]] = "TestImage"
        if "CollectionPhase" in column:
            values[column["CollectionPhase"]] = "StimuliDisplay"
        values[column["Duration"]] = trim.format_ms(duration_ms) if event.startswith("Start") else ""
        values[column["SourceStimuliName"]] = row["canonical_name"]
        return values

    with destination.open("w", newline="", encoding="utf-8-sig") as target_handle:
        writer = csv.writer(target_handle)
        writer.writerows(metadata_rows)
        writer.writerow(event_row(1, 0.0, "StartSlide"))
        writer.writerow(event_row(2, 0.0, "StartMedia"))
        writer.writerow(event_row(3, duration_ms, "EndMedia"))
        writer.writerow(event_row(4, duration_ms, "EndSlide"))

    return result_row(
        row,
        record,
        destination,
        status="source_timing_only",
        segment_count=len(segments),
        gap_seconds=gap_seconds,
        selected_seconds=selected_seconds,
        stitched_seconds=stitched_seconds,
        scanned_rows=4,
        kept_rows=4,
        source_has_fea=False,
    )


def result_row(
    row: dict[str, str],
    record: trim.ManifestRecord,
    destination: Path,
    *,
    status: str,
    segment_count: int,
    gap_seconds: float,
    selected_seconds: float,
    stitched_seconds: float,
    scanned_rows: int,
    kept_rows: int,
    source_has_fea: bool,
) -> dict[str, object]:
    return {
        "source_csv": row["sensor_csv_full_source"],
        "output_csv": str(destination),
        "speaker": row["speaker"],
        "speaker_order": row["speaker_order"],
        "canonical_name": row["canonical_name"],
        "date_token": row["date_token"],
        "video_id": row["video_id"],
        "status": status,
        "mapping_method": "exact_video_id",
        "manifest": str(record.path),
        "segment_count": segment_count,
        "gap_seconds": gap_seconds,
        "source_video_duration_seconds": record.duration_seconds,
        "selected_duration_seconds": round(selected_seconds, 3),
        "stitched_timeline_seconds": round(stitched_seconds, 3),
        "original_data_rows_scanned": scanned_rows,
        "kept_rows": kept_rows,
        "source_has_fea": source_has_fea,
    }


def trim_fea_export(
    row: dict[str, str],
    record: trim.ManifestRecord,
    destination: Path,
    gap_seconds_fallback: float,
) -> dict[str, object]:
    trim_args = argparse.Namespace(
        stitch_edge_trim_seconds=trim.DEFAULT_STITCH_EDGE_TRIM_SECONDS,
        min_edge_trim_segment_seconds=trim.DEFAULT_MIN_EDGE_TRIM_SEGMENT_SECONDS,
        gap_seconds_fallback=gap_seconds_fallback,
    )
    shared_result = trim.trim_one_csv(make_mapping(row, record), destination.parent, trim_args)
    temporary_output = Path(str(shared_result["output_csv"]))
    if temporary_output != destination:
        destination.unlink(missing_ok=True)
        temporary_output.replace(destination)
    shared_result.update(
        {
            "output_csv": str(destination),
            "canonical_name": row["canonical_name"],
            "speaker_order": row["speaker_order"],
            "source_has_fea": True,
        }
    )
    return shared_result


def trim_row(
    row: dict[str, str],
    record: trim.ManifestRecord,
    gap_seconds_fallback: float,
) -> dict[str, object]:
    destination = Path(row["imotions_short_csv"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source_has_fea(Path(row["sensor_csv_full_source"])):
        return trim_fea_export(row, record, destination, gap_seconds_fallback)
    return reconstruct_event_only(row, record, destination, gap_seconds_fallback)


def write_report_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "speaker", "speaker_order", "canonical_name", "video_id", "status", "source_has_fea",
        "segment_count", "gap_seconds", "selected_duration_seconds", "stitched_timeline_seconds",
        "original_data_rows_scanned", "kept_rows", "source_csv", "output_csv", "manifest",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    canonical_path = Path(args.canonical_manifest).resolve()
    metadata_root = Path(args.metadata_root).resolve()
    report_root = Path(args.report_root).resolve()
    report_root.mkdir(parents=True, exist_ok=True)
    rows, fieldnames = read_manifest(canonical_path)
    records, manifest_errors = trim.load_latest_manifests(metadata_root, {"ok", "needs_review"})

    ids = [row["video_id"] for row in rows]
    duplicate_ids = sorted({video_id for video_id in ids if ids.count(video_id) > 1})
    if duplicate_ids:
        raise RuntimeError(f"Canonical manifest contains duplicate video IDs: {duplicate_ids}")

    failures: list[str] = []
    completed: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        source = Path(row["sensor_csv_full_source"])
        record = records.get(row["video_id"])
        if not source.is_file():
            failures.append(f"Missing source CSV: {source}")
            continue
        if record is None:
            failures.append(f"Missing usable segment manifest: {row['video_id']} ({row['canonical_name']})")
            continue
        print(f"[{index:02d}/{len(rows)}] {row['speaker']} - {row['canonical_name']}", flush=True)
        try:
            completed.append(trim_row(row, record, args.gap_seconds_fallback))
            row["imotions_short_csv_found"] = "True"
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append(f"{row['canonical_name']}: {exc}")
            row["imotions_short_csv_found"] = "False"

    report = {
        "canonical_manifest": str(canonical_path),
        "metadata_root": str(metadata_root),
        "expected_count": len(rows),
        "completed_count": len(completed),
        "fea_source_count": sum(item.get("source_has_fea") is True for item in completed),
        "timing_only_source_count": sum(item.get("source_has_fea") is False for item in completed),
        "failures": failures,
        "manifest_read_errors": manifest_errors,
        "outputs": completed,
    }
    (report_root / "canonical_imotions_trim_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    write_report_csv(report_root / "canonical_imotions_trim_report.csv", completed)
    write_manifest(canonical_path, rows, fieldnames)

    if failures or len(completed) != len(rows):
        print(f"FAILED: reconstructed {len(completed)}/{len(rows)} CSVs.", flush=True)
        for failure in failures:
            print(f"  - {failure}", flush=True)
        return 1
    print(f"Complete: reconstructed all {len(completed)} canonical iMotions CSVs.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
