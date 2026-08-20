from __future__ import annotations

import csv
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from spreadsheet_safety import SpreadsheetSafeWriter

from procurement.external_tools import credential_free_media_environment

from .config import resolve_opensmile_binary, resolve_opensmile_config
from .windows import AudioWindow

OPENSMILE_WINDOW_TIMEOUT_SECONDS = 10 * 60


def run_opensmile_windows(
    source_wav: Path,
    windows: Sequence[AudioWindow],
    output_csv: Path,
    *,
    feature_set: str = "egemaps",
    opensmile_binary: Path | None = None,
    opensmile_config: Path | None = None,
) -> Path:
    """Run OpenSMILE functionals for each analysis window."""

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    binary = resolve_opensmile_binary(explicit_path=opensmile_binary)
    config = resolve_opensmile_config(feature_set=feature_set, explicit_path=opensmile_config)

    if output_csv.exists():
        output_csv.unlink()

    with tempfile.TemporaryDirectory(prefix="opensmile_features_") as temp_dir:
        temp_csv = Path(temp_dir) / "features.csv"
        for window in windows:
            append = temp_csv.exists()
            command = [
                str(binary),
                "-C",
                str(config),
                "-I",
                str(source_wav),
                "-start",
                f"{window.start:.6f}",
                "-end",
                f"{window.end:.6f}",
                "-instname",
                f"row_{window.row:04d}",
                "-csvoutput",
                str(temp_csv),
                "-appendcsv",
                "1" if append else "0",
                "-timestampcsv",
                "1",
                "-headercsv",
                "1" if not append else "0",
                "-nologfile",
                "1",
            ]
            run_opensmile_command(command, window)

        add_window_metadata(temp_csv, windows)
        shutil.copyfile(temp_csv, output_csv)
    return output_csv


def run_opensmile_command(command: Sequence[str], window: AudioWindow) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=OPENSMILE_WINDOW_TIMEOUT_SECONDS,
            env=credential_free_media_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"OpenSMILE timed out on window {window.row} after "
            f"{OPENSMILE_WINDOW_TIMEOUT_SECONDS} seconds."
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = compact_process_output(exc)
        message = f"OpenSMILE failed on window {window.row} with exit code {exc.returncode}."
        if details:
            message = f"{message} {details}"
        raise RuntimeError(message) from exc


def compact_process_output(exc: subprocess.CalledProcessError) -> str:
    output = "\n".join(part.strip() for part in (exc.stderr, exc.stdout) if part and part.strip())
    if not output:
        return ""
    output = " ".join(output.split())
    if len(output) > 500:
        output = f"{output[:500]}..."
    return f"OpenSMILE output: {output}"


def add_window_metadata(output_csv: Path, windows: Sequence[AudioWindow]) -> None:
    """Add row/window timing columns to the OpenSMILE CSV for easier review."""

    if not output_csv.exists() or not windows:
        return

    delimiter = detect_delimiter(output_csv)
    with output_csv.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=delimiter))
    if not rows:
        return

    header = ["Row", "WindowStart", "WindowEnd", *rows[0]]
    data_rows = []
    for index, row in enumerate(rows[1:]):
        if index >= len(windows):
            break
        window = windows[index]
        data_rows.append([window.row, format_window_number(window.start), format_window_number(window.end), *row])

    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = SpreadsheetSafeWriter(csv.writer(handle))
        writer.writerow(header)
        writer.writerows(data_rows)


def detect_delimiter(path: Path) -> str:
    """Detect the delimiter OpenSMILE used, defaulting to semicolon."""

    first_line = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    if first_line.count(";") >= first_line.count(","):
        return ";"
    return ","


def format_window_number(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")
