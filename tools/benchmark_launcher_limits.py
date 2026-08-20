"""Reproducible, non-destructive launcher scale benchmarks.

The benchmark creates synthetic folder trees and DOCX tables in a temporary
directory. It measures launcher parsing only: no videos are downloaded, no
models are loaded, and no media is retained after the command exits.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from docx import Document

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application import backend
from application.launcher import MAX_JSON_BODY_BYTES, validate_segment_manifest


@dataclass(frozen=True)
class Measurement:
    operation: str
    item_count: int
    elapsed_seconds: float
    peak_python_mb: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scales",
        default="100,1000,5000",
        help="Comma-separated item counts. Default: 100,1000,5000.",
    )
    parser.add_argument("--output-json", type=Path, help="Optional path for machine-readable results.")
    return parser.parse_args()


def parse_scales(value: str) -> list[int]:
    scales = sorted({int(item.strip()) for item in value.split(",") if item.strip()})
    if not scales or any(item < 1 for item in scales):
        raise ValueError("Scales must contain positive integers.")
    return scales


def measure(operation: str, item_count: int, callback: Callable[[], object]) -> Measurement:
    tracemalloc.start()
    started = time.perf_counter()
    callback()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return Measurement(
        operation=operation,
        item_count=item_count,
        elapsed_seconds=round(elapsed, 4),
        peak_python_mb=round(peak / (1024 ** 2), 3),
    )


def create_folder_fixture(root: Path, count: int) -> Path:
    source = root / f"folder_{count}"
    for index in range(count):
        speaker = source / f"Speaker_{index % 20:02d}"
        speaker.mkdir(parents=True, exist_ok=True)
        (speaker / f"Video_{index:05d}.mp4").touch()
    return source


def create_docx_fixture(root: Path, count: int) -> Path:
    path = root / f"videos_{count}.docx"
    document = Document()
    table = document.add_table(rows=count + 1, cols=4)
    for column, heading in enumerate(("Link", "Speaker", "Length", "Date Uploaded")):
        table.rows[0].cells[column].text = heading
    for index in range(count):
        row = table.rows[index + 1]
        row.cells[0].text = f"https://www.youtube.com/watch?v={video_id_for_index(index)}"
        row.cells[1].text = f"Speaker {index % 20:02d}"
        row.cells[2].text = "00:30:00"
        row.cells[3].text = "2026-07-01"
    document.save(path)
    return path


def video_id_for_index(index: int) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    value = index
    characters = []
    for _ in range(11):
        characters.append(alphabet[value % len(alphabet)])
        value //= len(alphabet)
    return "".join(characters)


def benchmark_folder(root: Path, count: int) -> Measurement:
    source = create_folder_fixture(root, count)
    return measure(
        "folder_scan",
        count,
        lambda: backend.scan_input_source(
            source,
            duration_reader=lambda _path: 1800.0,
            enrich_youtube=False,
        ),
    )


def benchmark_docx(root: Path, count: int) -> Measurement:
    source = create_docx_fixture(root, count)
    return measure(
        "docx_scan",
        count,
        lambda: backend.scan_input_source(source, enrich_youtube=False),
    )


def typical_focus_segment(index: int) -> dict[str, object]:
    start = index * 10.0
    return {
        "video_id": "abcdefghijk",
        "video_title": "Representative research video",
        "speaker": "Representative Speaker",
        "source_path": "https://www.youtube.com/watch?v=abcdefghijk",
        "source_kind": "youtube",
        "youtube_url": "https://www.youtube.com/watch?v=abcdefghijk",
        "segment_index": index + 1,
        "start_seconds": start,
        "end_seconds": start + 8.0,
        "length_seconds": 8.0,
    }


def focus_manifest_size(segment_count: int) -> int:
    payload = {
        "mode": "manual",
        "sourcePath": "https://www.youtube.com/watch?v=abcdefghijk",
        "segmentManifest": {
            "schema_version": 1,
            "gap_seconds": 0.5,
            "selected_segments": [typical_focus_segment(index) for index in range(segment_count)],
        },
    }
    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def maximum_typical_focus_segments() -> dict[str, int]:
    low, high = 0, 1
    while focus_manifest_size(high) <= MAX_JSON_BODY_BYTES:
        low, high = high, high * 2
    while low + 1 < high:
        midpoint = (low + high) // 2
        if focus_manifest_size(midpoint) <= MAX_JSON_BODY_BYTES:
            low = midpoint
        else:
            high = midpoint
    # Validate a bounded subset through the same overlap/time normalization
    # code used by the API. The 2 MB calculation itself is exact JSON sizing.
    validate_segment_manifest(
        {
            "gap_seconds": 0.5,
            "selected_segments": [typical_focus_segment(index) for index in range(min(low, 1000))],
        }
    )
    return {
        "request_limit_bytes": MAX_JSON_BODY_BYTES,
        "typical_segments_within_limit": low,
        "next_payload_bytes": focus_manifest_size(low + 1),
    }


def main() -> int:
    args = parse_args()
    scales = parse_scales(args.scales)
    measurements: list[Measurement] = []
    with tempfile.TemporaryDirectory(prefix="meap-launcher-benchmark-") as temp_dir:
        root = Path(temp_dir)
        for scale in scales:
            measurements.append(benchmark_folder(root, scale))
            measurements.append(benchmark_docx(root, scale))

    report = {
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpu_count": os.cpu_count(),
        },
        "measurements": [asdict(item) for item in measurements],
        "focus_manifest_capacity": maximum_typical_focus_segments(),
    }
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output_json:
        args.output_json.expanduser().resolve().write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
