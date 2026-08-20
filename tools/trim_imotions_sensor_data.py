#!/usr/bin/env python3
"""Trim full-length iMotions sensor CSVs to clean-speaker beta segments.

The clean-speaker beta pipeline produces selected source-video intervals and a
stitched MP4. This utility applies the same selected intervals to the original
iMotions CSV exports, so downstream analysis can operate as if iMotions had
been run against the stitched videos directly.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from procurement.input_limits import (
    MAX_CLEAN_SPEAKER_JSON_BYTES,
    MAX_CLEAN_SPEAKER_JSON_ITEMS,
    read_control_json,
)


YOUTUBE_ID_RE = re.compile(r"(?:(?:v=)|(?:youtu\.be/)|(?:embed/)|(?:shorts/))([A-Za-z0-9_-]{11})")
BARE_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
ISO_DATE_RE = re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b")
EU_DATE_RE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})\b")
COMPACT_DATE_RE = re.compile(r"\b(20\d{2})(\d{2})(\d{2})\b")
YEAR_MONTH_RE = re.compile(r"\b(20\d{2})[-/.](\d{1,2})\b")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
CSV_NAME_RE = re.compile(r"^(?P<number>\d+)_(?P<country>[^_]+)_(?P<speaker>.+)_(?P<date>\d{4,8})$")

# Keep this aligned with procurement.procurement_beta.runner.
# The current stitcher preserves audited source intervals without an implicit
# edge trim, so the retroactive CSV timeline must do the same by default.
DEFAULT_STITCH_EDGE_TRIM_SECONDS = 0.0
DEFAULT_MIN_EDGE_TRIM_SEGMENT_SECONDS = 10.0 + (DEFAULT_STITCH_EDGE_TRIM_SECONDS * 2)
@dataclass(frozen=True)
class DocxVideo:
    """One YouTube video found in the source DOCX or input-folder manifest."""

    speaker: str
    video_id: str
    date_digits: str
    order_index: int
    source: str


@dataclass(frozen=True)
class SensorCsv:
    """Parsed identity fields from one iMotions CSV filename."""

    path: Path
    number: int
    speaker: str
    date_token: str


@dataclass(frozen=True)
class ManifestRecord:
    """Clean-speaker beta metadata needed to trim one sensor CSV."""

    path: Path
    video_id: str
    speaker: str
    status: str
    options: dict[str, object]
    segments: list[dict[str, float]]
    duration_seconds: float


@dataclass(frozen=True)
class CsvMapping:
    """Resolved link between a sensor CSV and a beta manifest."""

    sensor_csv: SensorCsv
    manifest: ManifestRecord
    mapping_method: str
    docx_video: DocxVideo | None


def main() -> int:
    args = parse_args()
    sensor_dir = Path(args.sensor_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else sensor_dir.parent / "Sensor Data - clean speaker valid rows"
    metadata_root = Path(args.metadata_root).expanduser().resolve()
    input_videos_root = Path(args.input_videos_root).expanduser().resolve() if args.input_videos_root else None
    docx_path = Path(args.docx).expanduser().resolve() if args.docx else None

    output_dir.mkdir(parents=True, exist_ok=True)

    sensor_files = parse_sensor_csvs(sensor_dir)
    docx_videos = load_mapping_videos(docx_path, input_videos_root, sensor_files)
    manifests, manifest_errors = load_latest_manifests(metadata_root, set(args.include_status))
    mappings, map_warnings = map_csvs_to_manifests(sensor_files, docx_videos, manifests)

    print(f"Sensor CSVs found: {len(sensor_files)}", flush=True)
    print(f"Mapping videos found: {len(docx_videos)}", flush=True)
    print(f"Usable beta manifests found: {len(manifests)}", flush=True)
    print(f"CSV-to-manifest matches: {len(mappings)}", flush=True)

    summaries: list[dict[str, object]] = []
    for mapping in mappings:
        summaries.append(trim_one_csv(mapping, output_dir, args))

    report = {
        "sensor_dir": str(sensor_dir),
        "output_dir": str(output_dir),
        "metadata_root": str(metadata_root),
        "docx": str(docx_path) if docx_path else "",
        "input_videos_root": str(input_videos_root) if input_videos_root else "",
        "include_status": list(args.include_status),
        "sensor_csv_count": len(sensor_files),
        "mapping_video_count": len(docx_videos),
        "usable_manifest_count": len(manifests),
        "processed_csv_count": len(summaries),
        "manifest_errors": manifest_errors,
        "mapping_warnings": map_warnings,
        "processed": summaries,
    }
    write_json(output_dir / "sensor_trim_report.json", report)
    write_report_csv(output_dir / "sensor_trim_report.csv", summaries)

    print(f"Wrote trimmed CSVs to: {output_dir}", flush=True)
    print(f"Wrote report: {output_dir / 'sensor_trim_report.json'}", flush=True)
    if map_warnings:
        print(f"Warnings: {len(map_warnings)} unmatched or ambiguous CSVs; see report.", flush=True)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensor-dir", required=True, help="Folder containing full-length iMotions CSV exports.")
    parser.add_argument("--metadata-root", required=True, help="Folder containing clean_speaker_beta_manifest.json files.")
    parser.add_argument("--output-dir", help="Folder for trimmed CSV copies. Defaults beside sensor-dir.")
    parser.add_argument("--docx", help="Source catalog DOCX used to order/map YouTube videos.")
    parser.add_argument("--input-videos-root", help="Fallback package/input_videos folder with speaker subfolders.")
    parser.add_argument("--include-status", nargs="+", default=["ok", "needs_review"], help="Manifest statuses to trim.")
    parser.add_argument("--gap-seconds-fallback", type=float, default=0.5, help="Gap to use if a manifest lacks options.gap_seconds.")
    parser.add_argument("--stitch-edge-trim-seconds", type=float, default=DEFAULT_STITCH_EDGE_TRIM_SECONDS)
    parser.add_argument("--min-edge-trim-segment-seconds", type=float, default=DEFAULT_MIN_EDGE_TRIM_SEGMENT_SECONDS)
    return parser.parse_args()


def parse_sensor_csvs(sensor_dir: Path) -> list[SensorCsv]:
    """Parse all sensor CSV filenames into speaker/date records."""

    results: list[SensorCsv] = []
    for path in sorted(sensor_dir.glob("*.csv")):
        match = CSV_NAME_RE.match(path.stem)
        if not match:
            continue
        results.append(
            SensorCsv(
                path=path,
                number=int(match.group("number")),
                speaker=match.group("speaker").replace("_", " "),
                date_token=match.group("date"),
            )
        )
    return results


def load_mapping_videos(docx_path: Path | None, input_videos_root: Path | None, sensor_files: list[SensorCsv]) -> list[DocxVideo]:
    """Load YouTube video ordering from DOCX first, then package input folders."""

    videos: list[DocxVideo] = []
    if docx_path and docx_path.exists():
        try:
            videos.extend(read_docx_videos(docx_path))
        except Exception as exc:  # noqa: BLE001 - report and continue with fallback.
            print(f"DOCX mapping read failed: {exc}", flush=True)

    if videos:
        return videos

    if input_videos_root and input_videos_root.exists():
        return read_input_folder_videos(input_videos_root, sensor_files)

    return []


def read_docx_videos(path: Path) -> list[DocxVideo]:
    """Extract video IDs, likely speakers, and any visible dates from a DOCX."""

    with zipfile.ZipFile(path) as package:
        rels = read_docx_relationships(package)
        document_xml = package.read("word/document.xml")

    root = ET.fromstring(document_xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    videos: list[DocxVideo] = []
    per_speaker_counts: defaultdict[str, int] = defaultdict(int)

    for table in root.findall(".//w:tbl", ns):
        rows = table.findall("./w:tr", ns)
        if not rows:
            continue
        header_cells = [cell_text(cell, ns) for cell in rows[0].findall("./w:tc", ns)]
        for row in rows[1:]:
            cells = row.findall("./w:tc", ns)
            row_text = " ".join(cell_text(cell, ns) for cell in cells)
            row_speaker = row_label_from_headers(header_cells, cells, ns, ("speaker", "name", "politician"))
            row_date = row_label_from_headers(header_cells, cells, ns, ("date", "uploaded", "upload"))
            date_digits = extract_date_digits(row_date) or extract_date_digits(row_text)
            for column_index, cell in enumerate(cells):
                urls = cell_urls(cell, ns, rels)
                if not urls:
                    continue
                speaker = row_speaker or speaker_from_column_header(header_cells, column_index) or "Unknown Speaker"
                cell_date = extract_date_digits(cell_text(cell, ns))
                for url in urls:
                    video_id = get_youtube_video_id(url)
                    if not video_id:
                        continue
                    per_speaker_counts[normalise_name(speaker)] += 1
                    videos.append(
                        DocxVideo(
                            speaker=speaker,
                            video_id=video_id,
                            date_digits=cell_date or date_digits,
                            order_index=per_speaker_counts[normalise_name(speaker)] - 1,
                            source=str(path),
                        )
                    )
    return dedupe_videos(videos)


def read_docx_relationships(package: zipfile.ZipFile) -> dict[str, str]:
    """Read external hyperlink targets from the Word relationship file."""

    rels_path = "word/_rels/document.xml.rels"
    if rels_path not in package.namelist():
        return {}
    root = ET.fromstring(package.read(rels_path))
    relationships: dict[str, str] = {}
    for rel in root:
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rel_id and target:
            relationships[rel_id] = target
    return relationships


def cell_text(cell: ET.Element, ns: dict[str, str]) -> str:
    return " ".join((text.text or "") for text in cell.findall(".//w:t", ns)).strip()


def cell_urls(cell: ET.Element, ns: dict[str, str], rels: dict[str, str]) -> list[str]:
    """Return visible URLs and hyperlink relationship targets in one DOCX cell."""

    urls: list[str] = []
    visible = cell_text(cell, ns)
    urls.extend(match.group(0) for match in re.finditer(r"https?://[^\s<>'\")]+", visible))
    rid_name = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    for hyperlink in cell.findall(".//w:hyperlink", ns):
        target = rels.get(hyperlink.attrib.get(rid_name, ""))
        if target:
            urls.append(target)
    return list(dict.fromkeys(urls))


def row_label_from_headers(header_cells: list[str], cells: list[ET.Element], ns: dict[str, str], needles: tuple[str, ...]) -> str:
    for index, header in enumerate(header_cells):
        if index >= len(cells):
            continue
        normalised_header = normalise_name(header)
        if any(needle in normalised_header for needle in needles):
            value = cell_text(cells[index], ns)
            if value and not get_youtube_video_id(value):
                return value
    return ""


def speaker_from_column_header(header_cells: list[str], column_index: int) -> str:
    if column_index >= len(header_cells):
        return ""
    header = header_cells[column_index].strip()
    if normalise_name(header) in {"", "link", "url", "video", "videos", "youtube", "youtubelink"}:
        return ""
    return header


def read_input_folder_videos(input_videos_root: Path, sensor_files: list[SensorCsv]) -> list[DocxVideo]:
    """Fallback mapping from package/input_videos speaker folders."""

    sensor_speakers = {normalise_name(item.speaker): item.speaker for item in sensor_files}
    videos: list[DocxVideo] = []
    for folder in sorted(path for path in input_videos_root.iterdir() if path.is_dir()):
        speaker = closest_sensor_speaker(folder.name.replace("_", " "), sensor_speakers) or folder.name.replace("_", " ")
        ids = read_ids_from_put_videos_file(folder) or [path.stem for path in sorted(folder.glob("*.mp4"))]
        for index, video_id in enumerate(ids):
            if BARE_YOUTUBE_ID_RE.match(video_id):
                videos.append(DocxVideo(speaker=speaker, video_id=video_id, date_digits="", order_index=index, source=str(folder)))
    return dedupe_videos(videos)


def read_ids_from_put_videos_file(folder: Path) -> list[str]:
    path = folder / "PUT_VIDEOS_HERE.txt"
    if not path.exists():
        return []
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        value = line.strip()
        if BARE_YOUTUBE_ID_RE.match(value):
            ids.append(value)
    return ids


def closest_sensor_speaker(name: str, sensor_speakers: dict[str, str]) -> str:
    normalised = normalise_name(name)
    for key, speaker in sensor_speakers.items():
        if key and (key in normalised or normalised in key):
            return speaker
    return ""


def dedupe_videos(videos: Iterable[DocxVideo]) -> list[DocxVideo]:
    seen: set[tuple[str, str]] = set()
    unique: list[DocxVideo] = []
    for video in videos:
        key = (normalise_name(video.speaker), video.video_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(video)
    return unique


def load_latest_manifests(metadata_root: Path, include_status: set[str]) -> tuple[dict[str, ManifestRecord], list[str]]:
    """Load the newest usable manifest for each YouTube video ID."""

    records: dict[str, ManifestRecord] = {}
    mtimes: dict[str, int] = {}
    errors: list[str] = []
    for path in metadata_root.rglob("clean_speaker_beta_manifest.json"):
        try:
            payload = read_control_json(
                path,
                label="clean speaker manifest",
                max_bytes=MAX_CLEAN_SPEAKER_JSON_BYTES,
                max_items=MAX_CLEAN_SPEAKER_JSON_ITEMS,
            )
            if not isinstance(payload, dict):
                raise ValueError("clean speaker manifest must be a JSON object")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        status = str(payload.get("status", ""))
        if status not in include_status:
            continue
        input_payload = payload.get("input") or {}
        video_id = str(input_payload.get("video_id") or "")
        if not video_id:
            continue
        segments = read_selected_segments(payload, path.parent)
        if not segments:
            continue
        mtime = path.stat().st_mtime_ns
        if video_id in mtimes and mtime <= mtimes[video_id]:
            continue
        records[video_id] = ManifestRecord(
            path=path,
            video_id=video_id,
            speaker=str(input_payload.get("speaker") or ""),
            status=status,
            options=dict(payload.get("options") or {}),
            segments=segments,
            duration_seconds=float(input_payload.get("duration_seconds") or 0.0),
        )
        mtimes[video_id] = mtime
    return records, errors


def read_selected_segments(manifest: dict[str, object], output_dir: Path) -> list[dict[str, float]]:
    segment_plan = manifest.get("segment_plan") if isinstance(manifest.get("segment_plan"), dict) else {}
    selected = list(segment_plan.get("selected_segments") or []) if isinstance(segment_plan, dict) else []
    if not selected:
        selected_path = output_dir / "selected_segments.json"
        try:
            selected_payload = read_control_json(
                selected_path,
                label="clean speaker selected segments",
                max_bytes=MAX_CLEAN_SPEAKER_JSON_BYTES,
                max_items=MAX_CLEAN_SPEAKER_JSON_ITEMS,
            )
            if not isinstance(selected_payload, dict):
                raise ValueError("clean speaker selected segments must be a JSON object")
            selected = list(selected_payload.get("selected_segments") or [])
        except (OSError, UnicodeError, json.JSONDecodeError):
            selected = []

    parsed: list[dict[str, float]] = []
    for item in selected:
        if not isinstance(item, dict):
            continue
        source = item.get("interval") if isinstance(item.get("interval"), dict) else item
        try:
            start = float(source["start"])
            end = float(source["end"])
            confidence = float(source.get("confidence", 1.0))
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            parsed.append({"start": start, "end": end, "confidence": confidence})
    return sorted(parsed, key=lambda item: (item["start"], item["end"]))


def map_csvs_to_manifests(
    sensor_files: list[SensorCsv],
    docx_videos: list[DocxVideo],
    manifests: dict[str, ManifestRecord],
) -> tuple[list[CsvMapping], list[str]]:
    """Map each sensor CSV to a completed beta manifest."""

    videos_by_speaker: defaultdict[str, list[DocxVideo]] = defaultdict(list)
    for video in docx_videos:
        videos_by_speaker[normalise_name(video.speaker)].append(video)
    for items in videos_by_speaker.values():
        items.sort(key=lambda item: item.order_index)

    csvs_by_speaker: defaultdict[str, list[SensorCsv]] = defaultdict(list)
    for item in sensor_files:
        csvs_by_speaker[normalise_name(item.speaker)].append(item)
    for items in csvs_by_speaker.values():
        items.sort(key=lambda item: item.number)

    mappings: list[CsvMapping] = []
    warnings: list[str] = []
    for sensor in sensor_files:
        candidates = speaker_candidates(sensor.speaker, docx_videos)
        docx_video, method = choose_docx_video(sensor, candidates, csvs_by_speaker)
        if not docx_video:
            warnings.append(f"No DOCX/input mapping for {sensor.path.name}")
            continue
        manifest = manifests.get(docx_video.video_id)
        if not manifest:
            warnings.append(f"No completed beta manifest for {sensor.path.name} -> {docx_video.video_id}")
            continue
        mappings.append(CsvMapping(sensor_csv=sensor, manifest=manifest, mapping_method=method, docx_video=docx_video))
    return mappings, warnings


def speaker_candidates(speaker: str, videos: list[DocxVideo]) -> list[DocxVideo]:
    requested = normalise_name(speaker)
    return [
        video
        for video in videos
        if requested and (requested in normalise_name(video.speaker) or normalise_name(video.speaker) in requested)
    ]


def choose_docx_video(
    sensor: SensorCsv,
    candidates: list[DocxVideo],
    csvs_by_speaker: defaultdict[str, list[SensorCsv]],
) -> tuple[DocxVideo | None, str]:
    """Prefer date matches; fall back to same-speaker ordering."""

    if not candidates:
        return None, ""

    date_matches = [video for video in candidates if date_token_matches(sensor.date_token, video.date_digits)]
    if len(date_matches) == 1:
        return date_matches[0], "speaker_date"

    sensor_group = csvs_by_speaker[normalise_name(sensor.speaker)]
    speaker_index = sensor_group.index(sensor) if sensor in sensor_group else 0
    ordered = sorted(candidates, key=lambda item: item.order_index)
    if speaker_index < len(ordered):
        method = "speaker_order"
        if len(date_matches) > 1:
            method = "speaker_order_after_ambiguous_date"
        return ordered[speaker_index], method

    return None, ""


def trim_one_csv(mapping: CsvMapping, output_dir: Path, args: argparse.Namespace) -> dict[str, object]:
    """Stream one full-length CSV and write only selected-segment rows."""

    output_path = output_dir / mapping.sensor_csv.path.name
    segments = trim_stitch_edges(
        mapping.manifest.segments,
        edge_trim_seconds=args.stitch_edge_trim_seconds,
        minimum_segment_seconds=args.min_edge_trim_segment_seconds,
    )
    gap_seconds = float(mapping.manifest.options.get("gap_seconds", args.gap_seconds_fallback) or args.gap_seconds_fallback)
    timeline_segments = add_stitched_offsets(segments, gap_seconds)

    original_data_rows = 0
    kept_rows = 0
    first_kept_source_ms: float | None = None
    last_kept_source_ms: float | None = None
    last_rebased_ms: float | None = None

    with mapping.sensor_csv.path.open("r", newline="", encoding="utf-8-sig", errors="replace") as source:
        reader = csv.reader(source)
        with output_path.open("w", newline="", encoding="utf-8-sig") as target:
            writer = csv.writer(target)
            header = write_metadata_and_header(reader, writer)
            timestamp_index = header.index("Timestamp")
            row_index = header.index("Row") if "Row" in header else None

            segment_cursor = 0
            for row in reader:
                if not row:
                    continue
                timestamp_ms = parse_float(row[timestamp_index] if timestamp_index < len(row) else "")
                if timestamp_ms is None:
                    continue
                original_data_rows += 1
                segment_cursor, rebased_ms = rebased_timestamp_ms(timestamp_ms, timeline_segments, segment_cursor)
                if rebased_ms is None:
                    continue

                kept_rows += 1
                if row_index is not None and row_index < len(row):
                    row[row_index] = str(kept_rows)
                row[timestamp_index] = format_ms(rebased_ms)
                writer.writerow(row)

                first_kept_source_ms = timestamp_ms if first_kept_source_ms is None else first_kept_source_ms
                last_kept_source_ms = timestamp_ms
                last_rebased_ms = rebased_ms

    selected_duration_seconds = sum(segment["end"] - segment["start"] for segment in segments)
    stitched_timeline_seconds = selected_duration_seconds + max(0.0, gap_seconds) * max(0, len(segments) - 1)
    return {
        "source_csv": str(mapping.sensor_csv.path),
        "output_csv": str(output_path),
        "speaker": mapping.sensor_csv.speaker,
        "date_token": mapping.sensor_csv.date_token,
        "video_id": mapping.manifest.video_id,
        "status": mapping.manifest.status,
        "mapping_method": mapping.mapping_method,
        "docx_or_input_source": mapping.docx_video.source if mapping.docx_video else "",
        "manifest": str(mapping.manifest.path),
        "segment_count": len(segments),
        "gap_seconds": gap_seconds,
        "source_video_duration_seconds": mapping.manifest.duration_seconds,
        "selected_duration_seconds": round(selected_duration_seconds, 3),
        "stitched_timeline_seconds": round(stitched_timeline_seconds, 3),
        "original_data_rows_scanned": original_data_rows,
        "kept_rows": kept_rows,
        "first_kept_source_ms": first_kept_source_ms,
        "last_kept_source_ms": last_kept_source_ms,
        "last_rebased_ms": last_rebased_ms,
    }


def write_metadata_and_header(reader: csv.reader, writer: csv.writer) -> list[str]:
    """Copy metadata rows through the real data header and return that header."""

    for row in reader:
        writer.writerow(row)
        if len(row) >= 2 and row[0] == "Row" and row[1] == "Timestamp":
            return row
    raise RuntimeError("Could not find iMotions data header row.")


def trim_stitch_edges(segments: list[dict[str, float]], *, edge_trim_seconds: float, minimum_segment_seconds: float) -> list[dict[str, float]]:
    """Mirror runner.trim_segment_for_stitching for CSV row selection."""

    trimmed: list[dict[str, float]] = []
    for segment in segments:
        start = float(segment["start"])
        end = float(segment["end"])
        duration = end - start
        if duration > minimum_segment_seconds:
            trim = min(edge_trim_seconds, max(0.0, (duration - 1.0) / 2.0))
            start += trim
            end -= trim
        if end > start:
            trimmed.append({"start": start, "end": end, "confidence": float(segment.get("confidence", 1.0))})
    return trimmed


def add_stitched_offsets(segments: list[dict[str, float]], gap_seconds: float) -> list[dict[str, float]]:
    """Attach stitched-output offsets to source intervals."""

    offset_seconds = 0.0
    timeline: list[dict[str, float]] = []
    for index, segment in enumerate(sorted(segments, key=lambda item: (item["start"], item["end"]))):
        duration = segment["end"] - segment["start"]
        timeline.append({**segment, "offset_seconds": offset_seconds})
        offset_seconds += duration
        if index < len(segments) - 1:
            offset_seconds += max(0.0, gap_seconds)
    return timeline


def rebased_timestamp_ms(
    timestamp_ms: float,
    segments: list[dict[str, float]],
    segment_cursor: int,
) -> tuple[int, float | None]:
    """Return the stitched timestamp for a source timestamp, if selected."""

    while segment_cursor < len(segments):
        segment = segments[segment_cursor]
        start_ms = segment["start"] * 1000.0
        end_ms = segment["end"] * 1000.0
        if timestamp_ms < start_ms:
            return segment_cursor, None
        if timestamp_ms <= end_ms:
            rebased = (segment["offset_seconds"] * 1000.0) + (timestamp_ms - start_ms)
            return segment_cursor, rebased
        segment_cursor += 1
    return segment_cursor, None


def write_report_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "source_csv",
        "output_csv",
        "speaker",
        "date_token",
        "video_id",
        "status",
        "mapping_method",
        "segment_count",
        "gap_seconds",
        "selected_duration_seconds",
        "stitched_timeline_seconds",
        "original_data_rows_scanned",
        "kept_rows",
        "manifest",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def get_youtube_video_id(value: str) -> str:
    match = YOUTUBE_ID_RE.search(value)
    if match:
        return match.group(1)
    stripped = value.strip()
    if BARE_YOUTUBE_ID_RE.match(stripped):
        return stripped
    return ""


def extract_date_digits(value: str) -> str:
    if not value:
        return ""
    compact = COMPACT_DATE_RE.search(value)
    if compact:
        return "".join(compact.groups())
    iso = ISO_DATE_RE.search(value)
    if iso:
        year, month, day = iso.groups()
        return f"{int(year):04d}{int(month):02d}{int(day):02d}"
    eu = EU_DATE_RE.search(value)
    if eu:
        day, month, year = eu.groups()
        return f"{int(year):04d}{int(month):02d}{int(day):02d}"
    year_month = YEAR_MONTH_RE.search(value)
    if year_month:
        year, month = year_month.groups()
        return f"{int(year):04d}{int(month):02d}"
    year = YEAR_RE.search(value)
    return year.group(1) if year else ""


def date_token_matches(token: str, date_digits: str) -> bool:
    if not token or not date_digits:
        return False
    return date_digits.startswith(token)


def normalise_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


def parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_ms(value: float) -> str:
    if abs(value - round(value)) < 0.0001:
        return str(int(round(value)))
    return f"{value:.4f}".rstrip("0").rstrip(".")


if __name__ == "__main__":
    raise SystemExit(main())
