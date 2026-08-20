#!/usr/bin/env python3
"""Audit shortened iMotions exports by their actual data payload.

The validator streams each CSV so that large facial-analysis exports are never
loaded into memory as a whole.  A file is only classified as facial data when
at least one row contains a numeric Affectiva value; metadata or file size alone
is not considered sufficient evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections.abc import Iterable
from pathlib import Path


EMOTION_COLUMNS = (
    "Anger",
    "Contempt",
    "Disgust",
    "Fear",
    "Joy",
    "Sadness",
    "Surprise",
    "Engagement",
    "Valence",
    "Neutral",
)
ACTION_UNIT_COLUMNS = (
    "Attention",
    "Brow Furrow",
    "Brow Raise",
    "Cheek Raise",
    "Chin Raise",
    "Dimpler",
    "Eye Closure",
    "Eye Widen",
    "Inner Brow Raise",
    "Jaw Drop",
    "Lip Corner Depressor",
    "Lip Press",
    "Lip Pucker",
    "Lip Stretch",
    "Lip Suck",
    "Lid Tighten",
    "Mouth Open",
    "Nose Wrinkle",
    "Smile",
    "Smirk",
    "Upper Lip Raise",
    "Blink",
    "BlinkRate",
    "Speaking",
)
HEAD_POSE_COLUMNS = ("Pitch", "Yaw", "Roll", "Interocular Distance")
LANDMARK_COLUMNS = tuple(
    name
    for feature in range(1, 7)
    for name in (f"feature-x_{feature}", f"feature-y_{feature}")
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery-root", type=Path, required=True)
    return parser.parse_args()


def is_numeric(value: str) -> bool:
    try:
        return bool(value.strip()) and math.isfinite(float(value))
    except ValueError:
        return False


def populated(row: list[str], indices: Iterable[int]) -> bool:
    return any(index < len(row) and is_numeric(row[index]) for index in indices)


def audit_file(path: Path, input_root: Path) -> dict[str, object]:
    metadata_has_affectiva = False
    header: list[str] | None = None
    total_rows = 0
    emotion_rows = 0
    action_unit_rows = 0
    head_pose_rows = 0
    landmark_rows = 0
    slide_event_rows = 0

    with path.open("r", newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if row and row[0] == "#Sensor info" and any("Affectiva AFFDEX" in cell for cell in row):
                metadata_has_affectiva = True
            if row and row[0] == "#DATA":
                header = next(reader, None)
                break

        if not header:
            return {
                "speaker": path.parent.name,
                "canonical_name": path.stem,
                "path": str(path),
                "bytes": path.stat().st_size,
                "status": "invalid_missing_data_header",
                "metadata_has_affectiva": metadata_has_affectiva,
                "data_rows": 0,
                "slide_event_rows": 0,
                "emotion_rows": 0,
                "action_unit_rows": 0,
                "head_pose_rows": 0,
                "landmark_rows": 0,
            }

        column_indices = {name: index for index, name in enumerate(header)}
        emotion_indices = [column_indices[name] for name in EMOTION_COLUMNS if name in column_indices]
        action_indices = [column_indices[name] for name in ACTION_UNIT_COLUMNS if name in column_indices]
        head_indices = [column_indices[name] for name in HEAD_POSE_COLUMNS if name in column_indices]
        landmark_indices = [column_indices[name] for name in LANDMARK_COLUMNS if name in column_indices]
        event_index = column_indices.get("SlideEvent")

        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            total_rows += 1
            emotion_rows += populated(row, emotion_indices)
            action_unit_rows += populated(row, action_indices)
            head_pose_rows += populated(row, head_indices)
            landmark_rows += populated(row, landmark_indices)
            if event_index is not None and event_index < len(row) and row[event_index].strip():
                slide_event_rows += 1

    has_real_fea = emotion_rows > 0
    if has_real_fea:
        status = "valid_affectiva_fea"
    elif total_rows > 0 and slide_event_rows > 0:
        status = "source_timing_only"
    else:
        status = "invalid_no_measurements"

    relative = path.relative_to(input_root)
    return {
        "speaker": relative.parts[0] if len(relative.parts) > 1 else path.parent.name,
        "canonical_name": path.stem,
        "path": str(path),
        "bytes": path.stat().st_size,
        "status": status,
        "metadata_has_affectiva": metadata_has_affectiva,
        "data_rows": total_rows,
        "slide_event_rows": slide_event_rows,
        "emotion_rows": emotion_rows,
        "action_unit_rows": action_unit_rows,
        "head_pose_rows": head_pose_rows,
        "landmark_rows": landmark_rows,
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def repair_manifest_paths(root: Path) -> int:
    manifest = root / "04_metadata" / "manifests" / "canonical_delivery_manifest.csv"
    if not manifest.is_file():
        return 0

    with manifest.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    repaired = 0
    for row in rows:
        old_path = row.get("imotions_short_csv", "")
        if not old_path:
            continue
        candidate = Path(old_path.replace("\\reports\\", "\\input_short_csv\\"))
        if candidate != Path(old_path) and candidate.is_file():
            row["imotions_short_csv"] = str(candidate)
            repaired += 1

    if repaired:
        with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return repaired


def main() -> int:
    root = parse_args().delivery_root.resolve()
    input_root = root / "03_post_processing" / "imotions" / "input_short_csv"
    report_root = root / "04_metadata" / "reports"
    paths = sorted(input_root.rglob("*.csv"), key=lambda path: str(path).casefold())
    if not paths:
        raise SystemExit(f"No iMotions CSV files found under {input_root}")

    rows: list[dict[str, object]] = []
    for position, path in enumerate(paths, start=1):
        result = audit_file(path, input_root)
        rows.append(result)
        print(
            f"[{position:02d}/{len(paths):02d}] {result['status']}: "
            f"{result['speaker']} / {result['canonical_name']} "
            f"({result['data_rows']} rows)",
            flush=True,
        )

    repaired_paths = repair_manifest_paths(root)
    counts = {
        "files": len(rows),
        "valid_affectiva_fea": sum(row["status"] == "valid_affectiva_fea" for row in rows),
        "source_timing_only": sum(row["status"] == "source_timing_only" for row in rows),
        "invalid": sum(str(row["status"]).startswith("invalid_") for row in rows),
        "manifest_paths_repaired": repaired_paths,
    }
    payload = {"summary": counts, "files": rows}
    write_csv(report_root / "imotions_payload_audit.csv", rows)
    (report_root / "imotions_payload_audit.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(counts, indent=2), flush=True)
    return 1 if counts["files"] != 60 or counts["invalid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
