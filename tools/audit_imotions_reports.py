#!/usr/bin/env python3
"""Validate generated iMotions reports against the streamed payload audit."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery-root", type=Path, required=True)
    return parser.parse_args()


def safe_filename(text: str) -> str:
    """Match the post-processing engine's directory-name normalization."""

    cleaned = re.sub(r'[<>:"/\\|?*]', "", str(text))
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned.strip("._ ") or "output"


def status(path: Path, *, required: bool) -> str:
    if not required:
        return "not_applicable"
    if not path.is_file():
        return "missing"
    return "valid" if path.stat().st_size > 100 else "empty"


def write_csv(
    path: Path,
    rows: list[dict[str, object]],
    *,
    fieldnames: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = fieldnames or (list(rows[0]) if rows else [])
    if not columns:
        raise ValueError("CSV output requires field names when there are no rows")
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = parse_args().delivery_root.resolve()
    metadata_root = root / "04_metadata" / "reports"
    reports_root = root / "03_post_processing" / "imotions" / "reports"
    payload_path = metadata_root / "imotions_payload_audit.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    rows: list[dict[str, object]] = []
    for item in payload["files"]:
        speaker = safe_filename(str(item["speaker"]))
        video = safe_filename(str(item["canonical_name"]))
        relative = Path(speaker) / video / "histograms.csv"
        has_fea = item["status"] == "valid_affectiva_fea"
        emotion_path = reports_root / "emotion" / relative
        raw_path = reports_root / "raw" / relative
        rows.append(
            {
                "speaker": item["speaker"],
                "canonical_name": item["canonical_name"],
                "input_status": item["status"],
                "data_rows": item["data_rows"],
                "emotion_rows": item["emotion_rows"],
                "emotion_report_status": status(emotion_path, required=has_fea),
                "emotion_report_bytes": emotion_path.stat().st_size if emotion_path.is_file() else 0,
                "emotion_report": str(emotion_path),
                "raw_report_status": status(raw_path, required=True),
                "raw_report_bytes": raw_path.stat().st_size if raw_path.is_file() else 0,
                "raw_report": str(raw_path),
                "requires_affectiva_reexport": not has_fea,
            }
        )

    errors = [
        row
        for row in rows
        if row["emotion_report_status"] in {"missing", "empty"}
        or row["raw_report_status"] in {"missing", "empty"}
    ]
    missing_sources = [row for row in rows if row["requires_affectiva_reexport"]]
    summary = {
        "files": len(rows),
        "valid_affectiva_inputs": sum(not row["requires_affectiva_reexport"] for row in rows),
        "valid_emotion_reports": sum(row["emotion_report_status"] == "valid" for row in rows),
        "valid_raw_reports": sum(row["raw_report_status"] == "valid" for row in rows),
        "affectiva_reexports_required": len(missing_sources),
        "report_errors": len(errors),
    }

    report_fields = list(rows[0])
    write_csv(metadata_root / "imotions_report_audit.csv", rows, fieldnames=report_fields)
    write_csv(
        metadata_root / "imotions_affectiva_reexport_required.csv",
        missing_sources,
        fieldnames=report_fields,
    )
    (metadata_root / "imotions_report_audit.json").write_text(
        json.dumps({"summary": summary, "files": rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 1 if len(rows) != 60 or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
