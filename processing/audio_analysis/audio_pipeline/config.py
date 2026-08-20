from __future__ import annotations

import os
import shutil
from pathlib import Path

from procurement.external_tools import resolve_media_binary


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OPENSMILE_DIR = "opensmile-3.0-win-x64"

# Set this to True inside the deployed Multimodal Emotion Analysis Tool checkout when audio
# extraction should also publish its per-video CSVs into analysis/audio_outputs.
Full_Stack_Deployment = False


def resolve_opensmile_binary(project_root: Path | None = None, explicit_path: Path | None = None) -> Path:
    """Return the SMILExtract executable path, preferring the bundled Windows build."""

    if explicit_path is not None:
        path = explicit_path.expanduser().resolve()
        if path.exists():
            return path
        raise FileNotFoundError(f"OpenSMILE binary was not found: {path}")

    env_binary = os.environ.get("OPENSMILE_BINARY")
    if env_binary:
        path = Path(env_binary).expanduser().resolve()
        if path.exists():
            return path
        raise FileNotFoundError(f"OPENSMILE_BINARY points to a missing file: {path}")

    env_home = os.environ.get("OPENSMILE_HOME")
    if env_home:
        path = Path(env_home).expanduser().resolve() / "bin" / "SMILExtract.exe"
        if path.exists():
            return path
        raise FileNotFoundError(f"OPENSMILE_HOME does not contain bin/SMILExtract.exe: {path}")

    root = (project_root or PROJECT_ROOT).resolve()
    bundled = root / DEFAULT_OPENSMILE_DIR / "bin" / "SMILExtract.exe"
    if bundled.exists():
        return bundled

    resolved = shutil.which("SMILExtract") or shutil.which("SMILExtract.exe")
    if resolved:
        return Path(resolved).resolve()

    raise FileNotFoundError(
        "OpenSMILE was not found. Keep opensmile-3.0-win-x64 in the Audio_Analysis root "
        "or pass --opensmile-binary."
    )


def resolve_opensmile_config(
    project_root: Path | None = None,
    feature_set: str = "egemaps",
    explicit_path: Path | None = None,
) -> Path:
    """Resolve the OpenSMILE config used for explainable acoustic features."""

    if explicit_path is not None:
        path = explicit_path.expanduser().resolve()
        if path.exists():
            return path
        raise FileNotFoundError(f"OpenSMILE config was not found: {path}")

    root = (project_root or PROJECT_ROOT).resolve()
    env_home = os.environ.get("OPENSMILE_HOME")
    config_root = (Path(env_home).expanduser().resolve() / "config") if env_home else (root / DEFAULT_OPENSMILE_DIR / "config")
    feature_key = feature_set.lower()
    candidates = {
        "egemaps": config_root / "egemaps" / "v01b" / "eGeMAPSv01b.conf",
        "compare": config_root / "compare16" / "ComParE_2016.conf",
        "compare16": config_root / "compare16" / "ComParE_2016.conf",
    }

    if feature_key not in candidates:
        raise ValueError("feature_set must be one of: egemaps, compare, compare16")

    path = candidates[feature_key]
    if path.exists():
        return path
    raise FileNotFoundError(f"OpenSMILE config was not found: {path}")


def resolve_ffmpeg_binary(
    explicit_path: Path | None = None,
    *,
    excluded_roots: tuple[Path, ...] = (),
    search_path: str | None = None,
) -> Path:
    """Return the ffmpeg executable path."""

    return resolve_media_binary(
        "ffmpeg",
        explicit_path=explicit_path,
        excluded_roots=excluded_roots,
        search_path=search_path,
    )


def resolve_ffprobe_binary(
    explicit_path: Path | None = None,
    *,
    excluded_roots: tuple[Path, ...] = (),
    search_path: str | None = None,
) -> Path:
    """Return the ffprobe executable path."""

    return resolve_media_binary(
        "ffprobe",
        explicit_path=explicit_path,
        excluded_roots=excluded_roots,
        search_path=search_path,
    )
