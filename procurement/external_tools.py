"""Trusted executable selection for first-party media subprocesses."""

from __future__ import annotations

import importlib.util
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MEDIA_CHILD_SECRET_NAMES = frozenset(
    {
        "YOUTUBE_API_KEY",
        "HF_TOKEN",
        "HUGGINGFACE_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
    }
)


def credential_free_media_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return a child environment without API or model-registry credentials."""

    environment = dict(os.environ if base is None else base)
    protected = {name.casefold() for name in MEDIA_CHILD_SECRET_NAMES}
    for name in tuple(environment):
        if name.casefold() in protected:
            environment.pop(name, None)
    return environment


def _resolved_roots(values: Iterable[Path | str]) -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in values:
        try:
            resolved = Path(value).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _candidate_names(name: str) -> tuple[str, ...]:
    requested = Path(name).name
    if Path(requested).suffix:
        return (requested,)
    if os.name != "nt":
        return (requested,)
    extensions = [item for item in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(os.pathsep) if item]
    return tuple(dict.fromkeys((requested, *(f"{requested}{extension.lower()}" for extension in extensions))))


@lru_cache(maxsize=64)
def _resolve_from_path(name: str, excluded: tuple[str, ...], search_path: str) -> Path:
    excluded_roots = tuple(Path(value) for value in excluded)
    for raw_entry in search_path.split(os.pathsep):
        if not raw_entry.strip():
            continue
        entry = Path(raw_entry.strip().strip('"')).expanduser()
        try:
            directory = entry.resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if any(_is_within(directory, root) for root in excluded_roots):
            continue
        for candidate_name in _candidate_names(name):
            candidate = (directory / candidate_name).resolve()
            if any(_is_within(candidate, root) for root in excluded_roots):
                continue
            if candidate.exists() and candidate.is_file():
                return candidate
    raise FileNotFoundError(f"{name} was not found in a trusted absolute PATH directory.")


def resolve_media_binary(
    name: str,
    *,
    explicit_path: Path | None = None,
    excluded_roots: Iterable[Path | str] = (),
    search_path: str | None = None,
) -> Path:
    """Resolve ffmpeg/ffprobe outside current, repository, input, and output trees."""

    if name.casefold() not in {"ffmpeg", "ffprobe"}:
        raise ValueError(f"Unsupported media executable: {name}")
    excluded = _resolved_roots((Path.cwd(), REPOSITORY_ROOT, *excluded_roots))
    if explicit_path is not None:
        candidate = explicit_path.expanduser().resolve()
        if any(_is_within(candidate, root) for root in excluded):
            raise ValueError(f"{name} must be installed outside repository, input, and output directories: {candidate}")
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError(f"{name} was not found: {candidate}")
        return candidate
    path_value = os.environ.get("PATH", "") if search_path is None else str(search_path)
    return _resolve_from_path(name, tuple(str(root) for root in excluded), path_value)


def resolve_nvidia_smi(
    *,
    excluded_roots: Iterable[Path | str] = (),
    search_path: str | None = None,
) -> Path:
    """Resolve NVIDIA telemetry outside current, repository, and user-data trees."""

    excluded = _resolved_roots((Path.cwd(), REPOSITORY_ROOT, *excluded_roots))
    if os.name == "nt":
        install_roots = [
            os.environ.get("ProgramW6432"),
            os.environ.get("ProgramFiles"),
            os.environ.get("SystemRoot"),
        ]
        relative_candidates = (
            Path("NVIDIA Corporation") / "NVSMI" / "nvidia-smi.exe",
            Path("System32") / "nvidia-smi.exe",
        )
        for raw_root in install_roots:
            if not raw_root:
                continue
            for relative in relative_candidates:
                candidate = (Path(raw_root) / relative).expanduser().resolve()
                if candidate.exists() and candidate.is_file() and not any(
                    _is_within(candidate, root) for root in excluded
                ):
                    return candidate
        raise FileNotFoundError("nvidia-smi was not found in a trusted Windows system or NVIDIA installation directory.")
    path_value = os.environ.get("PATH", "") if search_path is None else str(search_path)
    return _resolve_from_path(
        "nvidia-smi",
        tuple(str(root) for root in excluded),
        path_value,
    )


def yt_dlp_is_available() -> bool:
    """Return whether the selected Python interpreter can run yt-dlp as a module."""

    return importlib.util.find_spec("yt_dlp") is not None


def build_yt_dlp_command(
    arguments: Iterable[str],
    *,
    ffmpeg_binary: Path,
    python_executable: Path | None = None,
) -> list[str]:
    """Invoke yt-dlp through this interpreter and bind its media-tool lookup."""

    interpreter = (python_executable or Path(sys.executable)).expanduser().resolve()
    ffmpeg = ffmpeg_binary.expanduser().resolve()
    return [
        str(interpreter),
        "-E",
        "-P",
        "-m",
        "yt_dlp",
        "--ffmpeg-location",
        str(ffmpeg),
        *[str(value) for value in arguments],
    ]
