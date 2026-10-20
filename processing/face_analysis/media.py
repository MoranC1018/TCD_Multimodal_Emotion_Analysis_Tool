"""Video discovery, probing, identity, and hashing helpers."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Iterable, TextIO

from procurement.external_tools import (
    credential_free_media_environment,
    resolve_media_binary,
)


VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
FFPROBE_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class VideoMetadata:
    path: str
    sha256: str
    size_bytes: int
    duration_seconds: float
    fps: float
    frame_count: int | None
    width: int
    height: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def discover_videos(source: Path, *, recursive: bool = True) -> list[Path]:
    source = source.expanduser().resolve()
    if source.is_file():
        if source.suffix.lower() not in VIDEO_SUFFIXES:
            raise ValueError(f"Unsupported video extension: {source.suffix}")
        return [source]
    if not source.is_dir():
        raise FileNotFoundError(f"Face input does not exist: {source}")
    iterator: Iterable[Path] = source.rglob("*") if recursive else source.glob("*")
    videos = sorted(path.resolve() for path in iterator if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES)
    if not videos:
        raise ValueError(f"No supported videos found under {source}")
    return videos


def file_sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video(path: Path, *, ffprobe: str | Path | None = None) -> VideoMetadata:
    """Read video-only timing and verify every frame against the frame/FPS clock."""

    executable = resolve_media_binary(
        "ffprobe",
        explicit_path=Path(ffprobe) if ffprobe is not None else None,
        excluded_roots=(path.parent,),
    )
    completed = _run_ffprobe(executable, path, [
        "-show_entries", "stream=width,height,avg_frame_rate,time_base,duration,nb_frames",
        "-of", "json",
    ])
    payload = json.loads(completed.stdout)
    streams = payload.get("streams") or []
    if not streams:
        raise RuntimeError(f"No video stream found in {path}")
    stream = streams[0]
    fps = _positive_ratio(stream.get("avg_frame_rate"))
    if fps is None:
        raise RuntimeError(f"Video has invalid frame rate: {path}")
    duration = _positive_float(stream.get("duration"))
    frame_count = _positive_frame_count(stream.get("nb_frames"))
    # A complete header's average FPS does not establish a uniform cadence.
    # Validate all video timestamps before accepting the frame/FPS sampling
    # contract, including MP4 files with both duration and frame count present.
    counted, scanned_duration = _scan_video_timing(
        executable, path, fps, _positive_ratio(stream.get("time_base"))
    )
    if frame_count is not None and frame_count != counted:
        raise RuntimeError(
            f"Video frame count differs between stream metadata ({frame_count}) "
            f"and decoded frames ({counted}): {path}"
        )
    frame_count = counted
    if duration is None:
        # A longer audio/container tail is never evidence for video duration.
        duration = scanned_duration
    return VideoMetadata(
        path=str(path),
        sha256=file_sha256(path),
        size_bytes=path.stat().st_size,
        duration_seconds=duration,
        fps=fps,
        frame_count=frame_count,
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
    )


def _run_ffprobe(
    executable: Path,
    path: Path,
    arguments: list[str],
    *,
    stdout: TextIO | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        str(executable), "-v", "error", "-select_streams", "v:0", *arguments, str(path)
    ]
    try:
        completed = subprocess.run(
            command,
            stdout=stdout if stdout is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            shell=False,
            timeout=FFPROBE_TIMEOUT_SECONDS,
            env=credential_free_media_environment(),
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe is required and must be available on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"ffprobe timed out after {FFPROBE_TIMEOUT_SECONDS}s while inspecting video {path}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown ffprobe error").strip()
        raise RuntimeError(f"Could not inspect video {path}: {detail}") from exc
    # FFprobe can report decoding errors while still exiting successfully.
    # A partial decoded count must not turn corrupt frames into absent video.
    if completed.stderr and completed.stderr.strip():
        raise RuntimeError(f"Could not inspect video {path}: {completed.stderr.strip()}")
    return completed


def _scan_video_timing(
    executable: Path, path: Path, fps: float, time_base: float | None
) -> tuple[int, float]:
    frame_count = 0
    first_timestamp = None
    last_timestamp = None
    last_duration = None
    # Account for timestamp quantization (e.g. Matroska milliseconds), while
    # never accepting a missing frame's worth of timestamp drift.
    tolerance = min(0.25 / fps, max(time_base or 0.0, 1e-6) + 1e-6)
    # Compact rows go to disk, not an unbounded captured frame-JSON payload.
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as frames:
        _run_ffprobe(executable, path, [
            "-show_frames", "-show_entries",
            "frame=best_effort_timestamp_time,duration_time,pkt_duration_time:frame_side_data=",
            "-of", "compact=p=1:nk=0",
        ], stdout=frames)
        frames.seek(0)
        for line in frames:
            if not line.startswith("frame|"):
                continue
            fields = dict(
                field.split("=", 1)
                for field in line.strip().split("|")[1:]
                if "=" in field
            )
            timestamp = _finite_float(fields.get("best_effort_timestamp_time"))
            if timestamp is None:
                raise RuntimeError(f"Video frame timestamp is unavailable: {path}")
            if first_timestamp is None:
                first_timestamp = timestamp
            if abs(timestamp - first_timestamp - frame_count / fps) > tolerance:
                raise RuntimeError(
                    "Video has nonuniform frame timestamps; Face uses frame/fps timestamps. "
                    f"Convert to constant-frame-rate video before processing: {path}"
                )
            last_timestamp = timestamp
            last_duration = (
                _positive_float(fields.get("duration_time"))
                or _positive_float(fields.get("pkt_duration_time"))
            )
            frame_count += 1
    if frame_count == 0:
        raise RuntimeError(f"Could not establish a positive video frame count: {path}")
    if last_duration is None:
        raise RuntimeError(f"Final video frame duration is unavailable: {path}")
    return frame_count, last_timestamp + last_duration - first_timestamp


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _positive_float(value: object) -> float | None:
    number = _finite_float(value)
    return number if number is not None and number > 0 else None


def _positive_ratio(value: object) -> float | None:
    try:
        return _positive_float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return None


def _positive_frame_count(value: object) -> int | None:
    try:
        count = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return count if count > 0 else None


def stable_media_id(path: Path, sha256: str) -> str:
    safe_stem = "".join(character if character.isalnum() or character in "-_" else "_" for character in path.stem)
    return f"{safe_stem}__{sha256[:12]}"
