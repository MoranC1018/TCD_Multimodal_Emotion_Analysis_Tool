from __future__ import annotations

import subprocess
from pathlib import Path

from procurement.external_tools import credential_free_media_environment

from .config import resolve_ffmpeg_binary, resolve_ffprobe_binary
from .windows import AudioWindow

FFMPEG_TIMEOUT_SECONDS = 6 * 60 * 60
FFPROBE_TIMEOUT_SECONDS = 60


def extract_mono_wav(input_video: Path, output_wav: Path, sample_rate: int = 16000) -> Path:
    """Extract a mono WAV file suitable for the selected emotion models."""

    output_wav.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(resolve_ffmpeg_binary(excluded_roots=(input_video.parent, output_wav.parent))),
        "-y",
        "-i",
        str(input_video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        str(output_wav),
    ]
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=FFMPEG_TIMEOUT_SECONDS,
        env=credential_free_media_environment(),
    )
    return output_wav


def export_window_wav(source_wav: Path, window: AudioWindow, output_wav: Path) -> Path:
    """Export one model window from the full WAV without decoding in Python."""

    output_wav.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(resolve_ffmpeg_binary(excluded_roots=(source_wav.parent, output_wav.parent))),
        "-y",
        "-ss",
        f"{window.start:.6f}",
        "-t",
        f"{window.duration:.6f}",
        "-i",
        str(source_wav),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output_wav),
    ]
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=FFMPEG_TIMEOUT_SECONDS,
        env=credential_free_media_environment(),
    )
    return output_wav


def probe_duration_seconds(media_path: Path) -> float:
    """Read media duration using ffprobe."""

    command = [
        str(resolve_ffprobe_binary(excluded_roots=(media_path.parent,))),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=FFPROBE_TIMEOUT_SECONDS,
        env=credential_free_media_environment(),
    )
    return float(result.stdout.strip())
