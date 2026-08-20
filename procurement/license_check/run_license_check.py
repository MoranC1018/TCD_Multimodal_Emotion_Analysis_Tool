#!/usr/bin/env python3
"""
run_pipeline.py

Package launcher for the YouTube licence-audit workflow.
Run with: python -m procurement.license_check.run_license_check
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

PIPELINE_VERSION = "2026.05.18-team-setup-v2-minimal-doc-columns"
PLACEHOLDER_KEY_VALUES = {"", "PASTE_KEY_HERE", "PASTE_YOUR_KEY_HERE", "YOUR_KEY_HERE"}


def root_dir() -> Path:
    return Path(__file__).resolve().parent


def read_config(path: Path) -> dict[str, str]:
    config: dict[str, str] = {}
    if not path.exists():
        return config
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip().strip('"').strip("'")
    return config


def as_bool(value: str, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_command(
    cmd: list[str],
    log_path: Path,
    allow_exit_codes: set[int] | None = None,
    env: dict[str, str] | None = None,
) -> int:
    allow_exit_codes = allow_exit_codes or {0}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print("\nRunning:")
    print(" ".join(f'"{part}"' if " " in part else part for part in redact_command_for_console(cmd)))
    print(f"Log: {log_path}")

    child_env = credential_free_environment() if env is None else dict(env)
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=child_env)
    log_path.write_text(proc.stdout or "", encoding="utf-8")

    # Echo the useful output to the screen so users can see progress.
    if proc.stdout:
        print(proc.stdout)

    if proc.returncode not in allow_exit_codes:
        print(f"ERROR: command failed with exit code {proc.returncode}.")
        print(f"Open this log file and send it to the technical maintainer: {log_path}")
    return proc.returncode


def redact_command_for_console(cmd: list[str]) -> list[str]:
    """Return a display-only command with secrets removed."""
    redacted = list(cmd)
    for index, part in enumerate(redacted[:-1]):
        if part == "--api-key":
            redacted[index + 1] = "<redacted>"
    return redacted


def credential_free_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in ("YOUTUBE_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        env.pop(name, None)
    return env


def create_missing_folders(base: Path, input_dir: Path, output_dir: Path, log_dir: Path, archive_dir: Path) -> None:
    for folder in [input_dir, output_dir, log_dir, archive_dir]:
        folder.mkdir(parents=True, exist_ok=True)
    placeholder = input_dir / "PUT_WORD_DOCX_FILES_HERE.txt"
    if not placeholder.exists():
        placeholder.write_text(
            "Put the Word .docx files you want to licence-check in this folder.\n"
            "Then run: python -m procurement.license_check.run_license_check\n",
            encoding="utf-8",
        )


def preflight(base: Path, config: dict[str, str], input_dir: Path) -> tuple[bool, str]:
    _ = base, config
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if api_key in PLACEHOLDER_KEY_VALUES or len(api_key) < 10:
        return False, (
            "No YouTube API key is set.\n\n"
            "Set YOUTUBE_API_KEY in the process environment or use the launcher's protected credential setting.\n"
        )

    docs = [p for p in input_dir.glob("*.docx") if not p.name.startswith("~$")]
    if not docs:
        return False, (
            f"No .docx files were found in the input folder:\n{input_dir}\n\n"
            "Put your DOCX file in the input folder, close it in its editor, then run again.\n"
        )

    return True, ""


def copy_example_config_if_needed(base: Path) -> None:
    config = base / "config.env"
    example = base / "config.env.example"
    if not config.exists() and example.exists():
        shutil.copyfile(example, config)


def main() -> int:
    base = root_dir()
    copy_example_config_if_needed(base)

    config_path = base / "config.env"
    config = read_config(config_path)

    input_dir = base / config.get("INPUT_FOLDER", "input")
    output_dir = base / config.get("OUTPUT_FOLDER", "output")
    log_dir = base / config.get("LOG_FOLDER", "logs")
    archive_dir = base / config.get("ARCHIVE_FOLDER", "archive")
    create_missing_folders(base, input_dir, output_dir, log_dir, archive_dir)

    print("=" * 64)
    print("YouTube Licence Check Pipeline")
    print("=" * 64)
    print(f"Pipeline version: {PIPELINE_VERSION}")
    print(f"Main folder:      {base}")
    print(f"Input folder:     {input_dir}")
    print(f"Output folder:    {output_dir}")
    print(f"Logs folder:      {log_dir}")

    ok, message = preflight(base, config, input_dir)
    if not ok:
        print("\n" + message)
        write_text(log_dir / "LAST_ERROR.txt", message)
        return 2

    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    terms_json = base / config.get("TERMS_JSON", "license_terms_dictionary.json")
    if not terms_json.exists():
        terms_json = None

    scan_tags = as_bool(config.get("SCAN_TAGS", "false"), default=False)
    run_verifier = as_bool(config.get("RUN_BLIND_VERIFICATION_AFTER_AUDIT", "true"), default=True)
    insert_headers = as_bool(config.get("INSERT_HEADER_FOR_HEADERLESS_TABLES", "true"), default=True)
    only_headered = as_bool(config.get("ONLY_HEADERED_TABLES", "false"), default=False)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    docs = [p for p in input_dir.glob("*.docx") if not p.name.startswith("~$")]

    all_success = True
    finished_lines: list[str] = []

    for docx in docs:
        print("\n" + "-" * 64)
        print(f"Processing: {docx.name}")
        safe_stem = docx.stem.replace(" ", "_")
        out_docx = output_dir / f"{docx.stem}_license_audit_{timestamp}.docx"
        debug_csv = log_dir / f"{safe_stem}_audit_debug_{timestamp}.csv"
        audit_summary = output_dir / f"{docx.stem}_license_audit_summary_{timestamp}.txt"
        audit_log_docx = output_dir / f"{docx.stem}_license_audit_log_{timestamp}.docx"
        audit_log = log_dir / f"{safe_stem}_audit_console_{timestamp}.log"

        cmd = [
            sys.executable,
            str(base / "audit_docx.py"),
            str(docx),
            "--output",
            str(out_docx),
            "--debug-csv",
            str(debug_csv),
            "--summary-txt",
            str(audit_summary),
            "--log-docx",
            str(audit_log_docx),
        ]
        if terms_json:
            cmd.extend(["--terms-json", str(terms_json)])
        if scan_tags:
            cmd.append("--scan-tags")
        if not insert_headers:
            cmd.append("--no-insert-headerless-headers")
        if only_headered:
            cmd.append("--only-headered-tables")

        audit_env = credential_free_environment()
        audit_env["YOUTUBE_API_KEY"] = api_key
        code = run_command(cmd, audit_log, allow_exit_codes={0}, env=audit_env)
        if code != 0:
            all_success = False
            finished_lines.append(f"FAILED audit: {docx.name} -> see {audit_log}")
            continue

        finished_lines.append(f"Audit output: {out_docx}")
        finished_lines.append(f"Audit log document: {audit_log_docx}")
        finished_lines.append(f"Audit summary: {audit_summary}")
        finished_lines.append(f"Audit debug CSV: {debug_csv}")

        if run_verifier:
            verifier_csv = log_dir / f"{safe_stem}_blind_verification_{timestamp}.csv"
            verifier_summary = output_dir / f"{docx.stem}_blind_verification_summary_{timestamp}.txt"
            verifier_log = log_dir / f"{safe_stem}_blind_verification_console_{timestamp}.log"
            verifier_cmd = [
                sys.executable,
                str(base / "verify_audit.py"),
                str(out_docx),
                "--api-key",
                api_key,
                "--out-csv",
                str(verifier_csv),
                "--summary",
                str(verifier_summary),
            ]
            vcode = run_command(verifier_cmd, verifier_log, allow_exit_codes={0, 1})
            if vcode not in {0, 1}:
                all_success = False
                finished_lines.append(f"FAILED verifier: {docx.name} -> see {verifier_log}")
            else:
                finished_lines.append(f"Verifier summary: {verifier_summary}")
                finished_lines.append(f"Verifier CSV: {verifier_csv}")
                if vcode == 1:
                    finished_lines.append("Verifier found manual-review items. This is not necessarily a failure; open the verifier summary.")

    final_report = output_dir / f"PIPELINE_FINISHED_{timestamp}.txt"
    write_text(
        final_report,
        "YouTube Licence Check Pipeline Finished\n"
        "=======================================\n\n"
        + "\n".join(finished_lines)
        + "\n\n"
        + ("Overall status: SUCCESS\n" if all_success else "Overall status: SOME STEPS FAILED\n"),
    )

    print("\n" + "=" * 64)
    print("Finished")
    print("=" * 64)
    print(f"Final report: {final_report}")
    print("Open the output folder to collect the checked DOCX file and summaries.")
    return 0 if all_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
