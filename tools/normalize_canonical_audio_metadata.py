#!/usr/bin/env python3
"""Normalize all canonical audio metadata to delivery speaker/video names."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-manifest", type=Path, required=True)
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def normalize_audio_csv(path: Path, row: dict[str, str]) -> None:
    """Update structured #INFO rows without touching analysis values."""

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        records = list(csv.reader(handle))
    replacements = {
        "#SourceFile": row["clean_video"],
        "#SpeakerName": row["speaker"],
        "#VideoTitle": row["canonical_name"],
        "#YoutubeID": row["video_id"],
    }
    seen: set[str] = set()
    for record in records:
        if record and record[0] in replacements:
            while len(record) < 2:
                record.append("")
            record[1] = replacements[record[0]]
            seen.add(record[0])

    # Current exports contain all four keys. Insert a missing key before #DATA
    # only for backwards-compatible older files.
    data_index = next((index for index, record in enumerate(records) if record and record[0] == "#DATA"), len(records))
    for key, value in replacements.items():
        if key not in seen:
            records.insert(data_index, [key, value])
            data_index += 1

    temporary = path.with_suffix(path.suffix + ".normalizing")
    with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle).writerows(records)
    temporary.replace(path)


def normalize_json_manifest(path: Path, row: dict[str, str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    output_dir = Path(row["audio_output"])
    payload["input_video"] = row["clean_video"]
    payload["audio_analysis_csv"] = str(output_dir / "audio_analysis.csv")
    payload["opensmile_features_csv"] = str(output_dir / "opensmile_features.csv")
    payload["canonical_speaker"] = row["speaker"]
    payload["canonical_video_name"] = row["canonical_name"]
    payload["youtube_id"] = row["video_id"]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    rows = read_rows(args_path := parse_args().canonical_manifest.resolve())
    failures: list[str] = []
    for index, row in enumerate(rows, start=1):
        output_dir = Path(row["audio_output"])
        audio_csv = output_dir / "audio_analysis.csv"
        opensmile_csv = output_dir / "opensmile_features.csv"
        sidecar = output_dir / "audio_analysis_manifest.json"
        if not audio_csv.is_file() or not opensmile_csv.is_file() or not sidecar.is_file():
            failures.append(f"Missing required audio files: {row['canonical_name']}")
            continue
        normalize_audio_csv(audio_csv, row)
        normalize_json_manifest(sidecar, row)
        print(f"[{index:02d}/{len(rows)}] Normalized {row['canonical_name']}", flush=True)

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", flush=True)
        return 1
    print(f"Complete: normalized all {len(rows)} audio outputs from {args_path}.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
