"""Cross-modality discovery of the supported shared FFmpeg runtime on Windows."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path


SUPPORTED_FFMPEG_RELEASE = "8.1.2"
SUPPORTED_FFMPEG_MAJOR = 8

# FFmpeg 8 maps to libavcodec/libavformat 62. TorchCodec links all seven
# libraries below; checking only avcodec can select an incomplete "essentials"
# installation that imports ffprobe but cannot load the decoder.
REQUIRED_FFMPEG8_FILES = (
    "avcodec-62.dll",
    "avdevice-62.dll",
    "avfilter-11.dll",
    "avformat-62.dll",
    "avutil-60.dll",
    "swresample-6.dll",
    "swscale-9.dll",
    "ffmpeg.exe",
    "ffprobe.exe",
)

_DLL_HANDLES: list[object] = []
_CONFIGURED_PATH: Path | None = None


def configure_ffmpeg_shared_libraries() -> Path | None:
    """Expose a complete FFmpeg 8 full-shared build to this process.

    The exact WinGet 8.1.2 installation is considered before every PATH entry.
    Compatible alternatives are accepted only when all FFmpeg-8 DLL majors and
    both command-line tools are present.
    """

    global _CONFIGURED_PATH
    if not _running_on_windows():
        return None
    if _CONFIGURED_PATH is not None and _is_supported_ffmpeg8_directory(_CONFIGURED_PATH):
        return _CONFIGURED_PATH
    _CONFIGURED_PATH = None

    for directory in _candidate_directories():
        try:
            if not _is_supported_ffmpeg8_directory(directory):
                continue
            resolved = directory.resolve()
            _DLL_HANDLES.append(_add_dll_directory(resolved))
            current_path = os.environ.get("PATH", "")
            path_parts = [part for part in current_path.split(os.pathsep) if part]
            if str(resolved).casefold() not in {part.casefold() for part in path_parts}:
                os.environ["PATH"] = (
                    f"{resolved}{os.pathsep}{current_path}" if current_path else str(resolved)
                )
            _CONFIGURED_PATH = resolved
            return resolved
        except OSError:
            continue
    return None


def _candidate_directories() -> Iterable[Path]:
    """Yield exact WinGet, other WinGet, then PATH candidates without duplicates."""

    exact: list[Path] = []
    other_winget: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        try:
            package_roots = sorted(packages.glob("Gyan.FFmpeg.Shared_*"), key=str)
        except OSError:
            package_roots = []
        expected_directory = f"ffmpeg-{SUPPORTED_FFMPEG_RELEASE}-full_build-shared"
        for package_root in package_roots:
            exact_candidate = package_root / expected_directory / "bin"
            exact.append(exact_candidate)
            try:
                other_winget.extend(
                    path for path in package_root.glob("*/bin")
                    if path != exact_candidate
                )
            except OSError:
                continue

    path_candidates = [
        Path(part) for part in os.environ.get("PATH", "").split(os.pathsep) if part
    ]
    seen: set[str] = set()
    for candidate in (*exact, *other_winget, *path_candidates):
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        yield candidate


def _is_supported_ffmpeg8_directory(directory: Path) -> bool:
    try:
        if not directory.is_dir():
            return False
        names = {path.name.casefold() for path in directory.iterdir() if path.is_file()}
    except OSError:
        return False
    return all(name.casefold() in names for name in REQUIRED_FFMPEG8_FILES)


def _running_on_windows() -> bool:
    return os.name == "nt"


def _add_dll_directory(directory: Path) -> object:
    return os.add_dll_directory(str(directory))
