"""Ownership and path-safety rules for native Face output trees."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from processing.io_utils import assert_safe_output_path, atomic_write_json


FACE_OWNER_FILE = ".face_pipeline_owner.json"
FACE_OWNER = "multimodal-emotion-analysis-face"
FACE_OWNER_SCHEMA_VERSION = "1.0"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

_ROOT_SCOPE = "output-root"
_VIDEO_SCOPE = "video-output"
_LEGACY_RUN_SCHEMAS = {"1.0", "1.1"}
_LEGACY_VIDEO_SCHEMAS = {"1.0", "2.0"}
_ROOT_FILES = {"run_manifest.json", "run_index.csv", ".gitkeep", FACE_OWNER_FILE}
_VIDEO_FILES = {
    "video_manifest.json",
    "face_core.csv",
    "face_features.parquet",
    FACE_OWNER_FILE,
}
_PER_VIDEO_CONTRACT = {
    "core": "face_core.csv",
    "full": "face_features.parquet",
    "manifest": "video_manifest.json",
}


def validate_face_output_root(source: Path, output_root: Path) -> Path:
    """Validate one Face output root without creating or changing it."""

    source = Path(source).expanduser().resolve()
    target = _assert_safe_target(Path(output_root), source)
    if target.exists() and not target.is_dir():
        raise NotADirectoryError(f"Face output root is not a directory: {target}")
    if not target.exists():
        return target

    marker = target / FACE_OWNER_FILE
    if marker.exists():
        _require_owner_marker(marker, _ROOT_SCOPE)
        return target

    entries = list(target.iterdir())
    if not entries or all(entry.name == ".gitkeep" for entry in entries):
        return target
    if _legacy_face_video_directories(target) is None:
        raise ValueError(
            "Refusing to take over a non-empty directory that is not a recognised "
            f"Face output root: {target}"
        )
    return target


def prepare_face_output_root(source: Path, output_root: Path) -> Path:
    """Validate, claim, or safely upgrade one Face output root.

    Existing non-empty directories are accepted only when they carry our
    ownership marker or match the previous Face run/video manifest layout.
    This lets verified pre-marker outputs upgrade without allowing an
    arbitrary directory to be taken over.
    """

    source = Path(source).expanduser().resolve()
    target = validate_face_output_root(source, output_root)
    if not target.exists():
        target.mkdir(parents=True)
        target = _assert_safe_target(target, source)
        _write_owner_marker(target, _ROOT_SCOPE)
        return target

    marker = target / FACE_OWNER_FILE
    if marker.exists():
        _require_owner_marker(marker, _ROOT_SCOPE)
        return target

    entries = list(target.iterdir())
    if not entries or all(entry.name == ".gitkeep" for entry in entries):
        _write_owner_marker(target, _ROOT_SCOPE)
        return target

    legacy_video_dirs = _legacy_face_video_directories(target)
    if legacy_video_dirs is None:
        raise ValueError(
            "Refusing to take over a non-empty directory that is not a recognised "
            f"Face output root: {target}"
        )
    for video_dir in legacy_video_dirs:
        _write_owner_marker(video_dir, _VIDEO_SCOPE)
    _write_owner_marker(target, _ROOT_SCOPE)
    return target


def write_face_video_owner_marker(output_dir: Path) -> None:
    """Mark a complete staged per-video directory before publication."""

    _write_owner_marker(Path(output_dir), _VIDEO_SCOPE)


def _assert_safe_target(target: Path, source: Path) -> Path:
    return assert_safe_output_path(
        target,
        repository_root=REPOSITORY_ROOT,
        protected_sources=(source,),
        description="Face output",
    )


def _write_owner_marker(directory: Path, scope: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        directory / FACE_OWNER_FILE,
        {
            "schema_version": FACE_OWNER_SCHEMA_VERSION,
            "owner": FACE_OWNER,
            "scope": scope,
        },
    )


def _require_owner_marker(path: Path, expected_scope: str) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Face ownership marker is unreadable: {path}") from exc
    expected = {
        "schema_version": FACE_OWNER_SCHEMA_VERSION,
        "owner": FACE_OWNER,
        "scope": expected_scope,
    }
    if payload != expected:
        raise ValueError(f"Face ownership marker is invalid or has the wrong scope: {path}")


def _legacy_face_video_directories(root: Path) -> set[Path] | None:
    """Recognise only the exact pre-marker Face layout used by this project."""

    run_manifest = root / "run_manifest.json"
    try:
        payload = json.loads(run_manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if payload.get("schema_version") not in _LEGACY_RUN_SCHEMAS:
        return None
    if not isinstance(payload.get("videos"), list) or not isinstance(payload.get("summary"), Mapping):
        return None
    outputs = payload.get("outputs")
    if not isinstance(outputs, Mapping) or outputs.get("per_video") != _PER_VIDEO_CONTRACT:
        return None

    declared_root = payload.get("output_root")
    if declared_root:
        try:
            if Path(str(declared_root)).expanduser().resolve() != root.resolve():
                return None
        except (OSError, ValueError):
            return None

    video_dirs: set[Path] = set()
    for raw in payload["videos"]:
        if not isinstance(raw, Mapping):
            return None
        relative_value = raw.get("output_relative")
        if not relative_value:
            continue
        relative = Path(str(relative_value))
        if relative.is_absolute() or ".." in relative.parts:
            return None
        candidate = root / relative
        if candidate.is_dir():
            video_dirs.add(candidate)

    # A shared root can retain valid outputs from earlier subsets that are not
    # named by the latest run manifest. Recognise those by their own manifest.
    for manifest_path in root.rglob("video_manifest.json"):
        if _looks_like_face_video_manifest(manifest_path):
            video_dirs.add(manifest_path.parent)

    allowed_directories = {root}
    for video_dir in video_dirs:
        current = video_dir
        while current != root:
            allowed_directories.add(current)
            current = current.parent
        if current != root:
            return None

    for path in root.rglob("*"):
        if path.is_dir():
            if path not in allowed_directories:
                return None
            continue
        if path.parent == root:
            if path.name not in _ROOT_FILES:
                return None
        elif path.parent not in video_dirs or path.name not in _VIDEO_FILES:
            return None
    return video_dirs


def _looks_like_face_video_manifest(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, Mapping)
        and payload.get("schema_version") in _LEGACY_VIDEO_SCHEMAS
        and payload.get("status") == "completed"
        and isinstance(payload.get("input"), Mapping)
        and isinstance(payload.get("media_id"), str)
    )
