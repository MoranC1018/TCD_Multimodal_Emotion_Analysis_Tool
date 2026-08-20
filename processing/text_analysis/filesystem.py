"""Safe directory publication primitives shared by Text processing stages."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from processing.io_utils import (
    assert_safe_output_path,
    atomic_write_json,
    make_staging_directory,
    publish_directory,
)

from .contracts import TEXT_SCHEMA_VERSION


OWNER_FILE = ".text_pipeline_owner.json"
OWNER_NAME = "multimodal-emotion-analysis-text"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def assert_safe_output_target(target: Path, *protected_sources: Path) -> Path:
    """Reject roots and targets that could replace a source or repository tree."""

    return assert_safe_output_path(
        target,
        repository_root=REPOSITORY_ROOT,
        protected_sources=protected_sources,
        description="Text output",
    )


def create_stage_directory(target: Path, stage: str) -> Path:
    """Create a sibling staging directory with an ownership marker."""

    target = assert_safe_output_target(target)
    assert_replaceable_stage_target(target, stage)
    staging = make_staging_directory(target.parent, f".{target.name}_staging_")
    atomic_write_json(
        staging / OWNER_FILE,
        {"schema_version": TEXT_SCHEMA_VERSION, "owner": OWNER_NAME, "stage": stage},
    )
    return staging


def replace_stage_directory(staging: Path, target: Path, stage: str) -> None:
    """Atomically publish a complete stage tree and recover the previous tree on failure."""

    staging, target = validate_stage_directory(staging, target, stage)
    publish_directory(staging, target)


def validate_stage_directory(
    staging: Path, target: Path, stage: str
) -> tuple[Path, Path]:
    """Validate one owned staging tree without publishing it."""

    # Revalidate the configurable destination immediately before inspecting
    # ownership and publication.  The shared publisher performs another check
    # immediately before each rename.
    target = assert_safe_output_target(target)
    staging = assert_safe_output_path(staging, description="Text staging directory")
    if staging.parent != target.parent:
        raise ValueError("Staging and target directories must be siblings")
    validate_owned_stage_path(staging, stage)

    assert_replaceable_stage_target(target, stage)
    return staging, target


def validate_owned_stage_path(path: Path, stage: str) -> Path:
    """Require an existing directory with this Text stage's exact owner marker."""

    path = assert_safe_output_path(path, description="Text owned stage directory")
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"Text stage path is not a safe directory: {path}")
    marker = path / OWNER_FILE
    try:
        marker_payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Directory has no valid Text ownership marker: {path}") from exc
    if (
        marker_payload.get("schema_version") != TEXT_SCHEMA_VERSION
        or marker_payload.get("owner") != OWNER_NAME
        or marker_payload.get("stage") != stage
    ):
        raise ValueError(f"Directory ownership does not match stage {stage!r}: {path}")
    return path


def discard_stage_directory(staging: Path, target: Path, stage: str) -> None:
    """Delete only a validated, owned staging tree for one exact target.

    This is intentionally stricter than ``shutil.rmtree(..., ignore_errors=True)``:
    configurable paths are never removed unless they are a sibling staging
    directory carrying this Text stage's exact ownership marker.
    """

    staging, _target = validate_stage_directory(staging, target, stage)
    shutil.rmtree(staging)


def assert_replaceable_stage_target(target: Path, stage: str) -> None:
    """Refuse to replace a non-empty directory not owned by this exact stage.

    Output paths are configurable.  A staging marker proves what we generated,
    but it does not prove that the user's existing target is ours to delete.
    The target marker is therefore a required capability for every subsequent
    whole-directory publication.  A fresh/empty directory (including a lone
    repository ``.gitkeep``) is safe for its first publication.
    """

    if not target.exists():
        return
    if target.is_symlink():
        raise ValueError(f"Refusing to replace a symlinked Text output directory: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"Text output path is not a directory: {target}")
    entries = list(target.iterdir())
    if not entries or all(entry.name == ".gitkeep" and entry.is_file() for entry in entries):
        return

    marker = target / OWNER_FILE
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Refusing to replace a non-empty Text output directory without a valid "
            f"ownership marker for stage {stage!r}: {target}"
        ) from exc
    expected = {
        "schema_version": TEXT_SCHEMA_VERSION,
        "owner": OWNER_NAME,
        "stage": stage,
    }
    if payload != expected:
        raise ValueError(
            f"Text output ownership does not match stage {stage!r}: {marker}"
        )
