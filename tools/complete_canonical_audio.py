#!/usr/bin/env python3
"""Complete and validate canonical audio emotion/OpenSMILE outputs sequentially."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-manifest", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--force", action="store_true", help="Re-run outputs which already pass validation.")
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


def validate_output(output_dir: Path) -> tuple[bool, str]:
    manifest_path = output_dir / "audio_analysis_manifest.json"
    audio_csv = output_dir / "audio_analysis.csv"
    opensmile_csv = output_dir / "opensmile_features.csv"
    if not manifest_path.is_file() or not audio_csv.is_file() or not opensmile_csv.is_file():
        return False, "one or more required output files are missing"

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"invalid manifest: {exc}"

    if payload.get("emotion_models_skipped") is not False:
        return False, "emotion models were skipped"
    if payload.get("categorical_model_available") is not True:
        return False, "categorical emotion model unavailable"
    if payload.get("dimensional_model_available") is not True:
        return False, "dimensional emotion model unavailable"
    if int(payload.get("window_count") or 0) < 1:
        return False, "no analysis windows were written"
    return True, "complete"


def run_audio(row: dict[str, str], repo_root: Path, python: str) -> None:
    clean_video = Path(row["clean_video"])
    output_dir = Path(row["audio_output"])
    if not clean_video.is_file():
        raise FileNotFoundError(f"Clean video is missing: {clean_video}")
    output_dir.mkdir(parents=True, exist_ok=True)

    command = [
        python,
        "run_audio_analysis.py",
        "single",
        str(clean_video),
        "--output",
        str(output_dir),
        "--opensmile-feature-set",
        "egemaps",
        "--device",
        "cpu",
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "OMP_NUM_THREADS": "2",
            "MKL_NUM_THREADS": "2",
            "OPENBLAS_NUM_THREADS": "2",
            "NUMEXPR_NUM_THREADS": "2",
        }
    )
    subprocess.run(
        command,
        cwd=repo_root / "processing" / "audio_analysis",
        env=environment,
        check=True,
    )


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.canonical_manifest).resolve()
    repo_root = Path(args.repo_root).resolve()
    rows, fieldnames = read_manifest(manifest_path)
    failures: list[str] = []

    for index, row in enumerate(rows, start=1):
        output_dir = Path(row["audio_output"])
        valid, reason = validate_output(output_dir)
        if valid and not args.force:
            print(f"[{index:02d}/{len(rows)}] Existing complete: {row['canonical_name']}", flush=True)
            row["audio_output_found"] = "True"
            continue

        print(f"[{index:02d}/{len(rows)}] Analysing: {row['speaker']} - {row['canonical_name']} ({reason})", flush=True)
        try:
            run_audio(row, repo_root, args.python)
            valid, reason = validate_output(output_dir)
            if not valid:
                raise RuntimeError(reason)
            row["audio_output_found"] = "True"
        except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
            failures.append(f"{row['canonical_name']}: {exc}")
            row["audio_output_found"] = "False"
        finally:
            # Persist progress after every item so a machine interruption can
            # resume from the next validated output without repeating work.
            write_manifest(manifest_path, rows, fieldnames)

    if failures:
        print(f"Audio completion finished with {len(failures)} failure(s):", flush=True)
        for failure in failures:
            print(f"  - {failure}", flush=True)
        return 1

    print(f"Complete: all {len(rows)} canonical audio outputs include emotion models and OpenSMILE.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
