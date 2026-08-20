"""Video discovery, probing, identity, and hashing helpers."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from procurement.external_tools import (
    credential_free_media_environment,
    resolve_media_binary,
)


VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


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
    executable = resolve_media_binary(
        "ffprobe",
        explicit_path=Path(ffprobe) if ffprobe is not None else None,
        excluded_roots=(path.parent,),
    )
    command = [
        str(executable),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,nb_frames:format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            shell=False,
            env=credential_free_media_environment(),
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe is required and must be available on PATH") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown ffprobe error").strip()
        raise RuntimeError(f"Could not inspect video {path}: {detail}") from exc

    payload = json.loads(completed.stdout)
    streams = payload.get("streams") or []
    if not streams:
        raise RuntimeError(f"No video stream found in {path}")
    stream = streams[0]
    numerator, denominator = str(stream.get("avg_frame_rate") or "0/1").split("/", 1)
    fps = float(numerator) / float(denominator) if float(denominator) else 0.0
    duration = float((payload.get("format") or {}).get("duration") or 0.0)
    if fps <= 0 or duration <= 0:
        raise RuntimeError(f"Video has invalid duration or frame rate: {path}")
    raw_count = stream.get("nb_frames")
    frame_count = int(raw_count) if raw_count not in {None, "", "N/A"} else None
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


def stable_media_id(path: Path, sha256: str) -> str:
    safe_stem = "".join(character if character.isalnum() or character in "-_" else "_" for character in path.stem)
    return f"{safe_stem}__{sha256[:12]}"
