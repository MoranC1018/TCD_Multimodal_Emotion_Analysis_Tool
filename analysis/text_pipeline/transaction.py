"""Failure-safe directory publication for text-postprocessing results."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from processing.io_utils import make_staging_directory, publish_directory


def replace_output_dir(staging_dir: Path, output_dir: Path) -> None:
    """Publish ``staging_dir`` while preserving the previous complete output.

    The formal output path is only ever created by a directory rename.  If a
    direct rename is blocked on Windows, staging is copied into a second hidden
    candidate and that *complete* candidate is renamed into place.  A partial
    copy can therefore never appear at ``output_dir``.  Every invocation uses a
    unique backup so concurrent or interrupted runs cannot delete another
    run's recovery copy.
    """

    staging_dir = Path(staging_dir)
    output_dir = Path(output_dir)
    if not staging_dir.is_dir():
        raise NotADirectoryError(f"Completed staging directory does not exist: {staging_dir}")
    if output_dir.exists() and not output_dir.is_dir():
        raise NotADirectoryError(f"Output path is not a directory: {output_dir}")

    direct_error_text: str | None = None
    try:
        publish_directory(staging_dir, output_dir)
        return
    except OSError as direct_error:
        # A Windows process may hold a handle inside the freshly generated
        # source tree even though reading every file remains possible.  Copy to
        # another inherited-ACL sibling, validate it completely, and ask the
        # shared publisher to perform the same locked/rollback-safe swap.
        if not staging_dir.is_dir():
            raise
        direct_error_text = str(direct_error)

    promotion_candidate = make_staging_directory(
        output_dir.parent, f".{output_dir.name}_promotion_"
    )
    try:
        shutil.copytree(staging_dir, promotion_candidate, dirs_exist_ok=True)
        _validate_tree_copy(staging_dir, promotion_candidate)
        try:
            publish_directory(promotion_candidate, output_dir)
        except Exception as fallback_error:
            raise RuntimeError(
                f"Direct publication of {staging_dir} failed ({direct_error_text}); "
                f"validated-copy publication also failed: {fallback_error}"
            ) from fallback_error
    finally:
        _remove_tree_best_effort(promotion_candidate)
    _remove_tree_best_effort(staging_dir)


def _validate_tree_copy(source: Path, target: Path) -> None:
    """Check that a fallback copy has the same files and sizes as staging."""

    source_files = _tree_file_inventory(source)
    target_files = _tree_file_inventory(target)
    if source_files != target_files:
        missing = sorted(str(path) for path in source_files.keys() - target_files.keys())
        extra = sorted(str(path) for path in target_files.keys() - source_files.keys())
        changed = sorted(
            str(path)
            for path in source_files.keys() & target_files.keys()
            if source_files[path] != target_files[path]
        )
        raise OSError(
            "Fallback output copy did not match staging: "
            f"missing={missing[:5]}, extra={extra[:5]}, content_changed={changed[:5]}"
        )


def _tree_file_inventory(root: Path) -> dict[Path, tuple[int, str]]:
    inventory: dict[Path, tuple[int, str]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        inventory[path.relative_to(root)] = (path.stat().st_size, digest.hexdigest())
    return inventory


def _remove_tree_best_effort(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError:
        pass
