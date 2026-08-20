"""Transaction boundary for the canonical RockSteady all/core output pair."""

from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from processing.io_utils import (
    assert_safe_output_path,
    exclusive_process_lock,
    publish_directory_pair,
    recover_directory_pair,
)

from .contracts import TEXT_SCHEMA_VERSION
from .filesystem import (
    OWNER_FILE,
    OWNER_NAME,
    assert_replaceable_stage_target,
    assert_safe_output_target,
    validate_owned_stage_path,
    validate_stage_directory,
)


PAIR_LOCK_SUFFIX = ".rocksteady-core.lock"
PAIR_JOURNAL_SUFFIX = ".rocksteady-core.transaction.json"


def rocksteady_pair_lock_path(all_root: Path) -> Path:
    root = assert_safe_output_target(all_root)
    return root.parent / f".{root.name}{PAIR_LOCK_SUFFIX}"


def rocksteady_pair_journal_path(all_root: Path) -> Path:
    root = assert_safe_output_target(all_root)
    return root.parent / f".{root.name}{PAIR_JOURNAL_SUFFIX}"


@dataclass
class RockSteadyCoreTransaction:
    """Capability yielded only while the canonical pair lock is held."""

    all_root: Path
    core_root: Path | None
    journal_path: Path
    _published: bool = False

    def publish(self, all_staging: Path, core_staging: Path) -> None:
        if self.core_root is None:
            raise RuntimeError("A core target is required for paired publication")
        if self._published:
            raise RuntimeError("This RockSteady pair transaction was already published")
        if self.journal_path.exists():
            raise RuntimeError(
                "A previous committed RockSteady pair journal could not be cleaned; "
                f"refusing to replace it: {self.journal_path}"
            )
        all_stage, all_target = validate_stage_directory(
            all_staging, self.all_root, "rocksteady"
        )
        core_stage, core_target = validate_stage_directory(
            core_staging, self.core_root, "derived-view"
        )
        publish_directory_pair(
            ((all_stage, all_target), (core_stage, core_target)),
            journal_path=self.journal_path,
        )
        self._published = True


@contextmanager
def rocksteady_pair_transaction(
    all_root: Path,
    core_root: Path | None = None,
    *,
    purpose: str,
) -> Iterator[RockSteadyCoreTransaction]:
    """Lock all writers and recover any prior interrupted pair publication.

    The standalone RockSteady adapter passes only ``all_root``.  It can safely
    serialize with paired pipeline writers, but deliberately refuses to write
    when a pending pair journal needs both configured targets for recovery.
    """

    all_target = assert_safe_output_target(all_root)
    core_target: Path | None = None
    if core_root is not None:
        core_target = assert_safe_output_target(core_root)
        if (
            all_target == core_target
            or all_target in core_target.parents
            or core_target in all_target.parents
        ):
            raise ValueError(
                "RockSteady all/core output directories must be distinct and non-overlapping"
            )
    journal = rocksteady_pair_journal_path(all_target)
    lock = rocksteady_pair_lock_path(all_target)
    _assert_transaction_sidecars_do_not_overlap(
        all_target, core_target, lock, journal
    )
    with exclusive_process_lock(lock, purpose=purpose):
        if core_target is None:
            if journal.exists():
                raise RuntimeError(
                    "A RockSteady all/core publication needs recovery before the standalone "
                    f"adapter can write {all_target}. Run the configured Text pipeline; "
                    f"recovery journal: {journal}"
                )
        else:
            recover_directory_pair(
                (all_target, core_target),
                journal_path=journal,
                path_validator=lambda candidate, target, role: _validate_recovery_path(
                    candidate, target, role, all_target
                ),
            )
        # Once this lock is held no compatible writer can own one of these
        # hidden roots.  Clean abandoned candidates even when a process died
        # before it reached the journaled publication step.
        _cleanup_recovered_staging(all_target, "rocksteady")
        if core_target is not None:
            _cleanup_recovered_staging(core_target, "derived-view")
        yield RockSteadyCoreTransaction(all_target, core_target, journal)


def _assert_transaction_sidecars_do_not_overlap(
    all_target: Path,
    core_target: Path | None,
    pair_lock: Path,
    journal: Path,
) -> None:
    if core_target is None:
        return
    targets = (all_target, core_target)
    sidecars = (
        pair_lock,
        journal,
        all_target.parent / f".{all_target.name}.publish.lock",
        core_target.parent / f".{core_target.name}.publish.lock",
        all_target.parent / f".{all_target.name}.rocksteady.lock",
        core_target.parent / f".{core_target.name}.derived-view.lock",
    )
    for target in targets:
        for sidecar in sidecars:
            if (
                target == sidecar
                or target in sidecar.parents
                or sidecar in target.parents
            ):
                raise ValueError(
                    "RockSteady all/core output overlaps an internal transaction sidecar: "
                    f"output={target}, sidecar={sidecar}"
                )


def _validate_recovery_path(
    candidate: Path, target: Path, role: str, all_target: Path
) -> None:
    stage = "rocksteady" if target == all_target else "derived-view"
    if role == "staging":
        validate_owned_stage_path(candidate, stage)
    else:
        # The previous target may be a fresh empty directory on the first run;
        # otherwise the exact Text stage marker is required.
        assert_replaceable_stage_target(candidate, stage)


def _cleanup_recovered_staging(target: Path, stage: str) -> None:
    """Remove only owned hidden staging roots left by a recovered transaction."""

    expected = {
        "schema_version": TEXT_SCHEMA_VERSION,
        "owner": OWNER_NAME,
        "stage": stage,
    }
    for candidate in target.parent.glob(f".{target.name}_staging_*"):
        if not candidate.is_dir() or candidate.is_symlink():
            continue
        try:
            payload = json.loads((candidate / OWNER_FILE).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if payload != expected:
            continue
        safe_candidate = assert_safe_output_path(
            candidate, description="recovered Text staging directory"
        )
        shutil.rmtree(safe_candidate)
