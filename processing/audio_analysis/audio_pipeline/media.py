from __future__ import annotations

import subprocess
import wave
from decimal import Decimal, ROUND_HALF_UP
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
    """Copy canonical PCM samples directly; use FFmpeg for other audio formats.

    ``extract_mono_wav`` already decodes/resamples to mono 16 kHz PCM16. Seeking in
    that file avoids another decoder process for every overlapping model window.
    Keep FFmpeg's six-decimal timestamp and nearest-sample rounding contract.
    """

    if output_wav.exists() and source_wav.samefile(output_wav):
        raise ValueError("Audio window source and output must not be the same file.")
    if _export_canonical_pcm_window(source_wav, window, output_wav):
        return output_wav

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


def _export_canonical_pcm_window(source_wav: Path, window: AudioWindow, output_wav: Path) -> bool:
    try:
        source = wave.open(str(source_wav), "rb")
    except (OSError, EOFError, wave.Error):
        # Preserve FFmpeg's existing conversion/error path for non-PCM inputs.
        return False
    with source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, 16000, "NONE"):
            return False
        start = Decimal(f"{window.start:.6f}")
        duration = Decimal(f"{window.duration:.6f}")
        if not start.is_finite() or not duration.is_finite() or window.start < 0 or window.duration <= 0:
            raise ValueError("Audio window start must be finite/nonnegative and duration finite/positive.")
        start_frame = int((start * 16000).to_integral_value(rounding=ROUND_HALF_UP))
        frame_count = int((duration * 16000).to_integral_value(rounding=ROUND_HALF_UP))
        if frame_count == 0:
            # FFmpeg treats a duration rounded below one sample specially.
            # Preserve that existing behavior instead of emitting an empty WAV.
            return False
        source.setpos(min(start_frame, source.getnframes()))
        samples = source.readframes(frame_count)
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_wav), "wb") as target:
            target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            target.writeframes(samples)
    return True


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
