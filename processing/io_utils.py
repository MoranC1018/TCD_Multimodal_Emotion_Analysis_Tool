"""Small, shared persistence helpers for processing pipelines."""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from spreadsheet_safety import SpreadsheetSafeWriter


_WINDOWS_RESERVED_COMPONENTS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)


@dataclass(frozen=True)
class _LockHandle:
    descriptor: int
    lock_id: str


def lexical_absolute_path(path: Path | str) -> Path:
    """Return an absolute, normalised path without following filesystem links.

    ``Path.resolve()`` is deliberately not used here.  Output paths must be
    inspected for symbolic links and Windows reparse points *before* those
    aliases disappear during resolution.
    """

    candidate = Path(path).expanduser()
    return Path(os.path.abspath(os.fspath(candidate)))


def assert_local_filesystem_path_syntax(
    path: Path | str, *, description: str = "input"
) -> Path:
    """Reject remote, device, ADS, and drive-relative syntax before any I/O."""

    raw = os.fspath(path).strip()
    if not raw:
        raise ValueError(f"{description.capitalize()} path is blank")
    windows = raw.replace("/", "\\")
    if windows.startswith("\\\\"):
        raise ValueError(
            f"Refusing network, device, or namespace path for {description}: {raw}"
        )
    if re.match(r"^[A-Za-z]:[^\\/]", raw):
        raise ValueError(f"Refusing drive-relative path for {description}: {raw}")
    colon_tail = raw[2:] if re.match(r"^[A-Za-z]:", raw) else raw
    if ":" in colon_tail:
        raise ValueError(f"Refusing alternate-data-stream path for {description}: {raw}")
    for component in re.split(r"[\\/]", windows):
        normalized = component.rstrip(" .").split(".", 1)[0].casefold()
        if normalized in _WINDOWS_RESERVED_COMPONENTS:
            raise ValueError(f"Refusing Windows device name for {description}: {raw}")
    return Path(raw).expanduser()


def assert_confined_input_file(
    path: Path | str,
    root: Path | str,
    *,
    description: str = "input",
    max_bytes: int | None = None,
) -> Path:
    """Return a regular local file proven to remain under a selected root."""

    requested = assert_local_filesystem_path_syntax(path, description=description)
    selected_root = assert_local_filesystem_path_syntax(root, description=f"{description} root")
    lexical_root = assert_no_output_path_aliases(
        selected_root, description=f"{description} root"
    )
    lexical_file = assert_no_output_path_aliases(requested, description=description)
    try:
        resolved_root = lexical_root.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise FileNotFoundError(
            f"{description.capitalize()} root does not exist: {lexical_root}"
        ) from exc
    try:
        resolved_file = lexical_file.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise FileNotFoundError(
            f"{description.capitalize()} does not exist: {lexical_file}"
        ) from exc
    try:
        resolved_file.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing {description} outside the selected root: {resolved_file}"
        ) from exc
    if not resolved_file.is_file():
        raise FileNotFoundError(f"{description.capitalize()} is not a regular file: {resolved_file}")
    if max_bytes is not None and resolved_file.stat().st_size > max_bytes:
        raise ValueError(
            f"{description.capitalize()} exceeds the {max_bytes} byte limit: {resolved_file}"
        )
    assert_no_output_path_aliases(requested, description=description)
    return resolved_file


def assert_input_file_budget(
    paths: Sequence[Path],
    *,
    max_files: int = 10_000,
    max_total_bytes: int = 1024 * 1024 * 1024,
    description: str = "input",
) -> tuple[Path, ...]:
    """Reject an excessive discovered file set before parsers allocate it."""

    if len(paths) > max_files:
        raise ValueError(f"{description.capitalize()} exceeds the {max_files} file limit")
    total = 0
    for path in paths:
        total += path.stat().st_size
        if total > max_total_bytes:
            raise ValueError(
                f"{description.capitalize()} exceeds the {max_total_bytes} cumulative byte limit"
            )
    return tuple(paths)


def assert_no_output_path_aliases(
    path: Path | str, *, description: str = "output"
) -> Path:
    """Reject an existing symlink, junction, or other Windows reparse component.

    Every existing component is checked, not just the final path.  This also
    catches an absent ``link/new-output`` target whose parent ``link`` redirects
    publication somewhere else.  ``Path.is_junction`` is used on Python 3.12+
    and ``st_file_attributes`` provides the compatible fallback.
    """

    requested = Path(path).expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    # Inspect the caller's unnormalised components first.  In particular,
    # ``link/../output`` must inspect (and reject) ``link`` before lexical
    # normalisation removes it; filesystem traversal would otherwise follow
    # the link before applying ``..`` on platforms such as POSIX.
    current = Path(requested.anchor)
    parts = requested.parts[1:] if requested.anchor else requested.parts
    for part in parts:
        if part == "..":
            current = current.parent
            continue
        current /= part
        try:
            metadata = current.lstat()
        except (FileNotFoundError, NotADirectoryError):
            # Keep walking: a later ``..`` may return to an existing branch.
            continue
        except OSError as exc:
            raise OSError(
                f"Cannot safely inspect {description} path component {current}: {exc}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or _is_windows_junction_or_reparse(
            current, metadata
        ):
            raise ValueError(
                f"Refusing to use {description} through a symbolic link, junction, "
                f"or reparse point: {current}"
            )
    return lexical_absolute_path(requested)


def assert_safe_output_path(
    target: Path | str,
    *,
    repository_root: Path | str | None = None,
    protected_sources: Sequence[Path | str] = (),
    description: str = "output",
) -> Path:
    """Validate and resolve one configurable directory-publication target.

    Legitimate paths outside this repository remain supported.  The protected
    boundaries are only filesystem roots, this repository/root ancestors,
    Git metadata, repository roots, and source trees that overlap the output
    in either direction.
    """

    lexical = assert_no_output_path_aliases(target, description=description)
    resolved = lexical.resolve(strict=False)
    if resolved == Path(resolved.anchor) or resolved.parent == resolved:
        raise ValueError(f"Refusing to use a filesystem root as {description}: {resolved}")

    # A .git component is never a valid generated-output location, including
    # the metadata tree of a different worktree.  Also retain the prior guard
    # against replacing an entire repository root.
    contains_git_metadata = any(part.casefold() == ".git" for part in resolved.parts)
    if contains_git_metadata or _entry_exists_without_following(resolved / ".git"):
        raise ValueError(
            f"Refusing to use Git metadata or a repository root as {description}: {resolved}"
        )

    if repository_root is not None:
        repository = Path(repository_root).expanduser().resolve(strict=False)
        if resolved == repository or resolved in repository.parents:
            raise ValueError(
                f"Refusing to use the repository or one of its ancestors as {description}: "
                f"{resolved}"
            )
        git_root = repository / ".git"
        if resolved == git_root or git_root in resolved.parents:
            raise ValueError(
                f"Refusing to use repository Git metadata as {description}: {resolved}"
            )

    for source_value in protected_sources:
        source = Path(source_value).expanduser().resolve(strict=False)
        if resolved == source or resolved in source.parents or source in resolved.parents:
            raise ValueError(
                f"{description.capitalize()} and source must not overlap: "
                f"output={resolved}, source={source}"
            )

    # Narrow the validation-to-use window.  This cannot make path operations
    # perfectly race-free on every supported platform, but catches aliases
    # introduced while sources and repository boundaries were being checked.
    assert_no_output_path_aliases(lexical, description=description)
    return resolved


def _is_windows_junction_or_reparse(path: Path, metadata: os.stat_result) -> bool:
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            if is_junction():
                return True
        except OSError:
            # The lstat attributes below are the compatibility/failure
            # fallback and do not follow the reparse target.
            pass
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400))
    return bool(attributes & reparse_flag)


def _entry_exists_without_following(path: Path) -> bool:
    try:
        path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


def make_staging_directory(parent: Path, prefix: str) -> Path:
    """Create a unique sibling directory with the parent's normal permissions.

    ``tempfile.mkdtemp`` deliberately creates directories with private
    permissions.  Renaming one of those directories into an output tree also
    promotes that private ACL on Windows, which can make a successful result
    unreadable to the user who launched the pipeline.  A regular ``mkdir``
    inherits the output parent's ACL and is therefore the right primitive for
    directories that may later become public pipeline artifacts.
    """

    if not prefix or Path(prefix).name != prefix:
        raise ValueError("Staging prefix must be a non-empty file-name component")
    parent = assert_no_output_path_aliases(parent, description="staging parent")
    if any(part.casefold() == ".git" for part in parent.parts):
        raise ValueError(
            f"Refusing to create a staging directory inside Git metadata: {parent}"
        )
    parent.mkdir(parents=True, exist_ok=True)
    assert_no_output_path_aliases(parent, description="staging parent")
    for _ in range(100):
        candidate = parent / f"{prefix}{uuid.uuid4().hex}"
        try:
            candidate.mkdir(mode=0o755)
        except FileExistsError:
            continue
        return candidate
    raise FileExistsError(f"Could not allocate a unique staging directory in {parent}")


def publish_directory(staging: Path, target: Path) -> None:
    """Promote a complete sibling directory while preserving the last result.

    A small exclusive lock prevents two runs from swapping the same target at
    once.  The previous target is moved to a run-unique backup and restored if
    promotion fails.  Backups from an interrupted process are never deleted
    merely because another path happens to exist.
    """

    staging = assert_safe_output_path(staging, description="staging directory")
    target = assert_safe_output_path(target, description="publication output")
    if not staging.is_dir():
        raise NotADirectoryError(f"Staging directory does not exist: {staging}")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Recheck after parent creation and immediately before taking the lock.
    staging = assert_safe_output_path(staging, description="staging directory")
    target = assert_safe_output_path(target, description="publication output")
    if staging.parent.resolve() != target.parent.resolve():
        raise ValueError("Staging and target directories must be siblings")
    if staging.resolve() == target.resolve():
        raise ValueError("Staging and target directories must be different")
    if target.exists() and not target.is_dir():
        raise NotADirectoryError(f"Directory publication target is not a directory: {target}")

    lock_path = target.parent / f".{target.name}.publish.lock"
    lock_handle = _acquire_process_lock(lock_path, f"publishing {target}")
    backup = target.parent / f".{target.name}.backup.{uuid.uuid4().hex}"
    moved_existing = False
    try:
        _assert_safe_backup_candidates(target)
        staging = assert_safe_output_path(staging, description="staging directory")
        target = assert_safe_output_path(target, description="publication output")
        _restore_interrupted_backup_if_needed(target)
        if target.exists():
            target = assert_safe_output_path(target, description="publication output")
            _rename_directory_with_retry(target, backup)
            moved_existing = True
        try:
            staging = assert_safe_output_path(staging, description="staging directory")
            target = assert_safe_output_path(target, description="publication output")
            _rename_directory_with_retry(staging, target)
        except Exception as promotion_error:
            if moved_existing and backup.exists() and not target.exists():
                try:
                    backup = assert_safe_output_path(
                        backup, description="publication recovery backup"
                    )
                    target = assert_safe_output_path(
                        target, description="publication output"
                    )
                    _rename_directory_with_retry(backup, target)
                except Exception as restore_error:
                    raise RuntimeError(
                        f"Could not publish {target} and could not restore its previous output: "
                        f"{restore_error}"
                    ) from promotion_error
            raise
        if moved_existing and backup.exists():
            try:
                assert_no_output_path_aliases(
                    backup, description="publication recovery backup"
                )
                if _path_itself_is_alias(backup):
                    raise ValueError(f"Recovery backup became a linked path: {backup}")
                shutil.rmtree(backup)
            except (OSError, ValueError) as exc:
                warnings.warn(
                    f"Published {target}, but old backup cleanup failed: {backup}: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
        _cleanup_superseded_backups(target)
    finally:
        _release_process_lock(lock_path, lock_handle)


def publish_directory_pair(
    pairs: Sequence[tuple[Path, Path]], *, journal_path: Path
) -> None:
    """Publish two directory snapshots as one recoverable logical transaction.

    Filesystems do not provide one atomic rename spanning two directory names.
    This helper therefore journals every rename, holds both normal publication
    locks, and rolls both targets back on any ordinary exception or
    ``KeyboardInterrupt``.  A hard process crash can expose an intermediate
    state until :func:`recover_directory_pair` is called; the journal makes
    each recorded process-crash cut point recoverable.  This does not claim
    power-loss durability for directory metadata on every filesystem.
    """

    entries = _normalise_directory_pair(pairs)
    journal = _normalise_pair_journal_path(journal_path, entries)
    lock_handles = _acquire_pair_publish_locks(entries)
    try:
        _recover_directory_pair_locked(
            journal, [target for _staging, target in entries]
        )
        if journal.exists():
            raise RuntimeError(
                "The previous committed directory-pair journal could not be cleaned; "
                f"refusing to overwrite it: {journal}"
            )
        transaction_id = uuid.uuid4().hex
        state: dict[str, Any] = {
            "schema_version": "1.0",
            "kind": "directory-pair-publication",
            "transaction_id": transaction_id,
            "status": "backing-up",
            "updated_at_unix": time.time(),
            "pairs": [],
        }
        for staging, target in entries:
            backup = target.parent / f".{target.name}.pair-backup.{transaction_id}"
            state["pairs"].append(
                {
                    "staging": str(staging),
                    "target": str(target),
                    "backup": str(backup),
                    "had_target": target.exists(),
                    "backup_created": False,
                    "published": False,
                }
            )
        _write_pair_journal(journal, state)

        try:
            for item in state["pairs"]:
                target = Path(item["target"])
                backup = Path(item["backup"])
                _assert_safe_pair_path(target, description="pair publication target")
                _assert_safe_pair_path(backup, description="pair publication backup")
                if target.exists():
                    _rename_directory_with_retry(target, backup)
                    item["backup_created"] = True
                    _write_pair_journal(journal, state)

            state["status"] = "publishing"
            _write_pair_journal(journal, state)
            for item in state["pairs"]:
                staging = Path(item["staging"])
                target = Path(item["target"])
                _assert_safe_pair_path(staging, description="pair staging directory")
                _assert_safe_pair_path(target, description="pair publication target")
                _rename_directory_with_retry(staging, target)
                item["published"] = True
                _write_pair_journal(journal, state)

            state["status"] = "committed"
            _write_pair_journal(journal, state)
        except BaseException as publication_error:
            rollback_errors = _rollback_directory_pair_entries(state["pairs"])
            if not rollback_errors:
                journal.unlink(missing_ok=True)
            if rollback_errors:
                raise RuntimeError(
                    "Directory-pair publication failed and automatic rollback was incomplete; "
                    f"recovery journal retained at {journal}. "
                    + "; ".join(rollback_errors)
                ) from publication_error
            raise

        for item in state["pairs"]:
            backup = Path(item["backup"])
            if not backup.exists():
                continue
            try:
                _assert_safe_pair_path(backup, description="pair publication backup")
                if _path_itself_is_alias(backup):
                    raise ValueError(f"Pair backup became a linked path: {backup}")
                shutil.rmtree(backup)
            except (OSError, ValueError) as exc:
                warnings.warn(
                    f"Published directory pair, but backup cleanup failed: {backup}: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
        try:
            journal.unlink(missing_ok=True)
        except OSError as exc:
            # Both targets are already committed.  Leaving a committed journal
            # is safe: the next writer will verify the pair and finish cleanup.
            warnings.warn(
                f"Published directory pair, but transaction-journal cleanup failed: "
                f"{journal}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
    finally:
        _release_pair_publish_locks(lock_handles)


def recover_directory_pair(
    targets: Sequence[Path],
    *,
    journal_path: Path,
    path_validator: Callable[[Path, Path, str], None] | None = None,
) -> bool:
    """Recover a journaled pair transaction; return whether one was present.

    ``path_validator`` is a domain ownership check called with the path, its
    target, and ``staging``/``target``/``backup`` role for every existing
    directory before the first recovery mutation.
    """

    normalised_targets = _normalise_pair_targets(targets)
    journal = _normalise_pair_journal_path(
        journal_path,
        [(target.parent / f".{target.name}.recovery-placeholder", target) for target in normalised_targets],
    )
    if not journal.is_file():
        return False
    lock_handles = _acquire_pair_target_locks(normalised_targets)
    try:
        return _recover_directory_pair_locked(
            journal, normalised_targets, path_validator=path_validator
        )
    finally:
        _release_pair_publish_locks(lock_handles)


def _normalise_directory_pair(
    pairs: Sequence[tuple[Path, Path]], *, require_staging: bool = True
) -> list[tuple[Path, Path]]:
    if len(pairs) != 2:
        raise ValueError("Directory-pair publication requires exactly two staging/target pairs")
    entries: list[tuple[Path, Path]] = []
    for raw_staging, raw_target in pairs:
        staging = assert_safe_output_path(raw_staging, description="pair staging directory")
        target = assert_safe_output_path(raw_target, description="pair publication target")
        if require_staging and not staging.is_dir():
            raise NotADirectoryError(f"Pair staging directory does not exist: {staging}")
        if staging.parent != target.parent:
            raise ValueError("Each pair staging directory and target must be siblings")
        if staging == target:
            raise ValueError("Pair staging directory and target must differ")
        expected_staging_prefix = f".{target.name}_staging_"
        suffix = staging.name.removeprefix(expected_staging_prefix)
        if (
            not staging.name.startswith(expected_staging_prefix)
            or re.fullmatch(r"[0-9a-f]{32}", suffix) is None
        ):
            raise ValueError(
                "Pair staging directory must use the owned sibling naming convention: "
                f"{staging}"
            )
        if target.exists() and not target.is_dir():
            raise NotADirectoryError(f"Pair publication target is not a directory: {target}")
        entries.append((staging, target))
    all_paths = [path for entry in entries for path in entry]
    folded = [str(path).casefold() for path in all_paths]
    if len(set(folded)) != len(folded):
        raise ValueError("Directory-pair staging and target paths must be distinct")
    left_target, right_target = entries[0][1], entries[1][1]
    if left_target in right_target.parents or right_target in left_target.parents:
        raise ValueError("Directory-pair targets must not overlap")
    _assert_pair_publish_sidecars_do_not_overlap(entries)
    return entries


def _normalise_pair_journal_path(
    journal_path: Path, entries: Sequence[tuple[Path, Path]]
) -> Path:
    journal = assert_safe_output_path(
        journal_path, description="directory-pair recovery journal"
    )
    if journal.exists() and not journal.is_file():
        raise ValueError(f"Directory-pair recovery journal is not a file: {journal}")
    for staging, target in entries:
        if _paths_overlap(journal, staging) or _paths_overlap(journal, target):
            raise ValueError("Directory-pair recovery journal must be outside staged/visible roots")
    lock_paths = [
        target.parent / f".{target.name}.publish.lock"
        for _staging, target in entries
    ]
    if any(_paths_overlap(journal, lock_path) for lock_path in lock_paths):
        raise ValueError("Directory-pair journal must not overlap a publication lock")
    journal.parent.mkdir(parents=True, exist_ok=True)
    return journal


def _assert_pair_publish_sidecars_do_not_overlap(
    entries: Sequence[tuple[Path, Path]],
) -> None:
    data_paths = [path for entry in entries for path in entry]
    lock_paths = [
        target.parent / f".{target.name}.publish.lock"
        for _staging, target in entries
    ]
    if len({str(path).casefold() for path in lock_paths}) != len(lock_paths):
        raise ValueError("Directory-pair targets resolve to the same publication lock")
    for lock_path in lock_paths:
        if any(_paths_overlap(lock_path, path) for path in data_paths):
            raise ValueError(
                "Directory-pair output/staging path overlaps a publication-lock sidecar: "
                f"{lock_path}"
            )


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _acquire_pair_publish_locks(
    entries: Sequence[tuple[Path, Path]],
) -> list[tuple[Path, _LockHandle]]:
    return _acquire_pair_target_locks([target for _staging, target in entries])


def _acquire_pair_target_locks(
    targets: Sequence[Path],
) -> list[tuple[Path, _LockHandle]]:
    handles: list[tuple[Path, _LockHandle]] = []
    ordered_targets = sorted(targets, key=lambda path: str(path).casefold())
    try:
        for target in ordered_targets:
            lock_path = target.parent / f".{target.name}.publish.lock"
            handles.append(
                (
                    lock_path,
                    _acquire_process_lock(lock_path, f"publishing directory pair containing {target}"),
                )
            )
    except BaseException:
        _release_pair_publish_locks(handles)
        raise
    return handles


def _release_pair_publish_locks(handles: Sequence[tuple[Path, _LockHandle]]) -> None:
    for lock_path, handle in reversed(handles):
        _release_process_lock(lock_path, handle)


def _write_pair_journal(path: Path, state: Mapping[str, Any]) -> None:
    mutable = dict(state)
    mutable["updated_at_unix"] = time.time()
    atomic_write_json(path, mutable)


def _recover_directory_pair_locked(
    journal: Path,
    expected_targets: Sequence[Path],
    *,
    path_validator: Callable[[Path, Path, str], None] | None = None,
) -> bool:
    if not journal.is_file():
        return False
    try:
        state = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read directory-pair recovery journal {journal}: {exc}") from exc
    if not isinstance(state, dict):
        raise RuntimeError(f"Directory-pair recovery journal is malformed: {journal}")
    transaction_id = state.get("transaction_id")
    status = state.get("status")
    pairs = state.get("pairs")
    if (
        state.get("schema_version") != "1.0"
        or state.get("kind") != "directory-pair-publication"
        or not isinstance(transaction_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", transaction_id) is None
        or status not in {"backing-up", "publishing", "committed"}
        or isinstance(state.get("updated_at_unix"), bool)
        or not isinstance(state.get("updated_at_unix"), (int, float))
        or not isinstance(pairs, list)
        or len(pairs) != 2
    ):
        raise RuntimeError(f"Directory-pair recovery journal is malformed: {journal}")
    expected_target_strings = [str(target) for target in expected_targets]
    actual_targets = [
        item.get("target") if isinstance(item, dict) else None for item in pairs
    ]
    if actual_targets != expected_target_strings:
        raise RuntimeError(
            f"Directory-pair recovery journal targets do not match this request: {journal}"
        )
    validated_items: list[dict[str, object]] = []
    all_recorded_paths: list[Path] = []
    for expected_target, raw_item in zip(expected_targets, pairs):
        if not isinstance(raw_item, dict) or any(
            not isinstance(raw_item.get(name), str)
            for name in ("staging", "target", "backup")
        ) or any(
            type(raw_item.get(name)) is not bool
            for name in ("had_target", "backup_created", "published")
        ):
            raise RuntimeError(f"Directory-pair recovery journal is malformed: {journal}")
        staging = Path(raw_item["staging"])
        target = Path(raw_item["target"])
        backup = Path(raw_item["backup"])
        if not all(path.is_absolute() for path in (staging, target, backup)):
            raise RuntimeError(f"Directory-pair recovery paths must be absolute: {journal}")
        expected_staging_prefix = f".{target.name}_staging_"
        staging_suffix = staging.name.removeprefix(expected_staging_prefix)
        if (
            target != expected_target
            or staging.parent != target.parent
            or staging == target
            or not staging.name.startswith(expected_staging_prefix)
            or re.fullmatch(r"[0-9a-f]{32}", staging_suffix) is None
        ):
            raise RuntimeError(f"Directory-pair recovery paths do not match: {journal}")
        expected_backup = target.parent / f".{target.name}.pair-backup.{transaction_id}"
        if backup != expected_backup:
            raise RuntimeError(f"Directory-pair recovery backup path is unsafe: {backup}")
        had_target = raw_item["had_target"]
        backup_created = raw_item["backup_created"]
        published = raw_item["published"]
        if (
            (not had_target and backup_created)
            or (status == "backing-up" and published)
            or (status == "publishing" and backup_created != had_target)
            or (
                status == "committed"
                and (not published or backup_created != had_target)
            )
        ):
            raise RuntimeError(
                f"Directory-pair recovery journal flags are inconsistent: {journal}"
            )
        _assert_safe_pair_path(target, description="pair recovery target")
        _assert_safe_pair_path(staging, description="pair recovery staging")
        _assert_safe_pair_path(backup, description="pair recovery backup")
        item = dict(raw_item)
        item.update({"staging": staging, "target": target, "backup": backup})
        validated_items.append(item)
        all_recorded_paths.extend((staging, target, backup))

    if len({str(path).casefold() for path in all_recorded_paths}) != len(
        all_recorded_paths
    ):
        raise RuntimeError(f"Directory-pair recovery paths are not distinct: {journal}")
    for index, left in enumerate(all_recorded_paths):
        if _paths_overlap(journal, left):
            raise RuntimeError(
                f"Directory-pair journal overlaps a recorded data path: {journal}"
            )
        for right in all_recorded_paths[index + 1 :]:
            if _paths_overlap(left, right):
                raise RuntimeError(
                    f"Directory-pair recovery paths overlap: {left} and {right}"
                )

    # Classify and validate every path before the first rename/rmtree.  A
    # malformed/externally modified state must leave all evidence untouched.
    states = [
        _classify_pair_recovery_item(item, committed=status == "committed")
        for item in validated_items
    ]
    if path_validator is not None:
        for item in validated_items:
            target = item["target"]
            assert isinstance(target, Path)
            for role in ("staging", "target", "backup"):
                candidate = item[role]
                assert isinstance(candidate, Path)
                if candidate.is_dir():
                    path_validator(candidate, target, role)

    if status == "committed":
        # A committed pair is already the new consistent generation.  Old
        # backups are cleanup-only and must never turn a success into rollback.
        for item in validated_items:
            backup = item["backup"]
            assert isinstance(backup, Path)
            if not backup.is_dir():
                continue
            try:
                shutil.rmtree(backup)
            except OSError as exc:
                warnings.warn(
                    f"Recovered committed directory pair, but backup cleanup failed: "
                    f"{backup}: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
        try:
            journal.unlink(missing_ok=True)
        except OSError as exc:
            warnings.warn(
                f"Recovered committed directory pair, but journal cleanup failed: "
                f"{journal}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
        return True

    rollback_errors = _rollback_directory_pair_entries(validated_items, states=states)
    if rollback_errors:
        raise RuntimeError(
            f"Directory-pair crash recovery is incomplete; journal retained at {journal}: "
            + "; ".join(rollback_errors)
        )
    journal.unlink(missing_ok=True)
    return True


def _normalise_pair_targets(targets: Sequence[Path]) -> list[Path]:
    if len(targets) != 2:
        raise ValueError("Directory-pair recovery requires exactly two targets")
    result = [
        assert_safe_output_path(target, description="pair recovery target")
        for target in targets
    ]
    if len({str(path).casefold() for path in result}) != 2:
        raise ValueError("Directory-pair recovery targets must be distinct")
    if result[0] in result[1].parents or result[1] in result[0].parents:
        raise ValueError("Directory-pair recovery targets must not overlap")
    placeholder_entries = [
        (target.parent / f".{target.name}_staging_{'0' * 32}", target)
        for target in result
    ]
    _assert_pair_publish_sidecars_do_not_overlap(placeholder_entries)
    return result


def _classify_pair_recovery_item(
    item: Mapping[str, object], *, committed: bool
) -> str:
    staging = Path(item["staging"])
    target = Path(item["target"])
    backup = Path(item["backup"])
    for path in (staging, target, backup):
        if path.exists() and not path.is_dir():
            raise RuntimeError(
                f"Directory-pair recovery found a non-directory path: {path}"
            )
    present = (staging.is_dir(), target.is_dir(), backup.is_dir())
    had_target = bool(item["had_target"])
    if committed:
        expected = (False, True, had_target)
        # Backup deletion after commit is also a legitimate cut point.
        if present not in {expected, (False, True, False)}:
            raise RuntimeError(
                "Committed directory-pair recovery state is ambiguous for "
                f"{target}: staging/target/backup={present}"
            )
        return "committed"
    if had_target:
        states = {
            (True, True, False): "untouched",
            (True, False, True): "backed-up",
            (False, True, True): "published",
        }
    else:
        states = {
            (True, False, False): "untouched",
            (False, True, False): "published",
        }
    try:
        return states[present]
    except KeyError as exc:
        raise RuntimeError(
            "Directory-pair recovery state is ambiguous for "
            f"{target}: staging/target/backup={present}"
        ) from exc


def _rollback_directory_pair_entries(
    items: Sequence[Mapping[str, Any]], *, states: Sequence[str] | None = None
) -> list[str]:
    errors: list[str] = []
    recovery_states = list(states) if states is not None else [
        _classify_pair_recovery_item(item, committed=False) for item in items
    ]
    for item, recovery_state in reversed(list(zip(items, recovery_states))):
        staging = Path(item["staging"])
        target = Path(item["target"])
        backup = Path(item["backup"])
        had_target = bool(item.get("had_target"))
        try:
            _assert_safe_pair_path(staging, description="pair rollback staging")
            _assert_safe_pair_path(target, description="pair rollback target")
            _assert_safe_pair_path(backup, description="pair rollback backup")
            if recovery_state == "published":
                _rename_directory_with_retry(target, staging)
            if recovery_state in {"published", "backed-up"} and had_target:
                if target.exists():
                    raise RuntimeError(
                        f"cannot restore {backup}; unexpected target still exists at {target}"
                    )
                _rename_directory_with_retry(backup, target)
        except BaseException as exc:
            errors.append(f"{target}: {type(exc).__name__}: {exc}")
    return errors


def _assert_safe_pair_path(path: Path, *, description: str) -> None:
    assert_safe_output_path(path, description=description)
    if _path_itself_is_alias(path):
        raise ValueError(f"Refusing {description} through a linked path: {path}")


@contextmanager
def exclusive_process_lock(lock_path: Path, *, purpose: str) -> Iterator[None]:
    """Hold a crash-recoverable, process-owned lock for a complete pipeline run.

    The lock records both PID and process creation time so a recycled PID does
    not make an abandoned lock look live forever.  A unique token also prevents
    a finishing process from deleting a replacement lock created after someone
    manually removed its original lock file.
    """

    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = _acquire_process_lock(lock_path, purpose)
    try:
        yield
    finally:
        _release_process_lock(lock_path, handle)


def _acquire_process_lock(lock_path: Path, purpose: str) -> _LockHandle:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    lock_id = uuid.uuid4().hex
    try:
        descriptor = os.open(lock_path, flags, 0o644)
    except FileExistsError:
        owner = _read_lock_owner(lock_path)
        if _lock_is_abandoned(lock_path, owner):
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
            descriptor = os.open(lock_path, flags, 0o644)
        else:
            pid = owner.get("pid") if isinstance(owner, dict) else None
            detail = f" (PID {pid})" if isinstance(pid, int) else ""
            raise RuntimeError(
                f"Another process is {purpose}{detail}. "
                f"If no such process exists, inspect and remove {lock_path}."
            )
    try:
        payload = json.dumps(
            {
                "lock_id": lock_id,
                "pid": os.getpid(),
                "process_started_at_unix": _process_started_at(os.getpid()),
                "purpose": purpose,
                "created_at_unix": time.time(),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        os.write(descriptor, payload)
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except OSError:
            pass
        raise
    return _LockHandle(descriptor, lock_id)


def _release_process_lock(lock_path: Path, handle: _LockHandle) -> None:
    try:
        os.close(handle.descriptor)
    finally:
        try:
            owner = _read_lock_owner(lock_path)
            if isinstance(owner, dict) and owner.get("lock_id") == handle.lock_id:
                lock_path.unlink()
            elif lock_path.exists():
                warnings.warn(
                    f"Completed process no longer owns lock {lock_path}; leaving it untouched",
                    RuntimeWarning,
                    stacklevel=2,
                )
        except FileNotFoundError:
            pass
        except OSError as exc:
            warnings.warn(
                f"Could not remove completed process lock {lock_path}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )


def _lock_is_abandoned(lock_path: Path, owner: object) -> bool:
    if isinstance(owner, dict):
        pid = owner.get("pid")
        if isinstance(pid, int):
            return not _pid_matches_owner(pid, owner.get("process_started_at_unix"))
    try:
        # A malformed partial lock should not block the tool forever, but give
        # a possibly-live writer a generous recovery window.
        return time.time() - lock_path.stat().st_mtime > 24 * 60 * 60
    except OSError:
        return False


def _restore_interrupted_backup_if_needed(target: Path) -> None:
    if target.exists():
        return
    backups = sorted(
        (
            path
            for path in target.parent.glob(f".{target.name}.backup.*")
            if not _path_itself_is_alias(path) and path.is_dir()
        ),
        key=lambda path: path.lstat().st_mtime_ns,
        reverse=True,
    )
    if backups:
        assert_safe_output_path(backups[0], description="publication recovery backup")
        assert_safe_output_path(target, description="publication output")
        _rename_directory_with_retry(backups[0], target)


def _cleanup_superseded_backups(target: Path) -> None:
    """Remove old backups only after a new complete target is in place."""

    if _path_itself_is_alias(target) or not target.is_dir():
        return
    for backup in target.parent.glob(f".{target.name}.backup.*"):
        if _path_itself_is_alias(backup) or not backup.is_dir():
            continue
        try:
            assert_no_output_path_aliases(
                backup, description="publication recovery backup"
            )
            shutil.rmtree(backup)
        except OSError as exc:
            warnings.warn(
                f"Published {target}, but superseded backup cleanup failed: {backup}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )


def _assert_safe_backup_candidates(target: Path) -> None:
    """Never restore or recursively clean a linked recovery candidate."""

    for backup in target.parent.glob(f".{target.name}.backup.*"):
        if _path_itself_is_alias(backup):
            raise ValueError(
                f"Refusing publication while an unsafe linked backup exists: {backup}"
            )


def _path_itself_is_alias(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or _is_windows_junction_or_reparse(path, metadata)


def _read_lock_owner(lock_path: Path) -> object:
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _pid_matches_owner(pid: int, expected_started_at: object) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil

        if not psutil.pid_exists(pid):
            return False
        if not isinstance(expected_started_at, (int, float)):
            return True
        try:
            actual = psutil.Process(pid).create_time()
        except (psutil.Error, OSError):
            return True
        return abs(actual - float(expected_started_at)) < 1.0
    except ImportError:
        if os.name == "nt":
            # Without a reliable Windows process check, keep the lock rather
            # than risk interrupting a live publisher.
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def _process_started_at(pid: int) -> float | None:
    try:
        import psutil

        return psutil.Process(pid).create_time()
    except (ImportError, OSError):
        return None
    except Exception as exc:  # psutil exception classes are optional at import time
        if exc.__class__.__module__.startswith("psutil"):
            return None
        raise


def _rename_directory_with_retry(source: Path, target: Path) -> None:
    last_error: OSError | None = None
    for attempt in range(6):
        try:
            source.rename(target)
            return
        except OSError as exc:
            last_error = exc
            if attempt == 5 or not _is_retryable_rename_error(exc):
                raise
            time.sleep(0.1 * (attempt + 1))
    if last_error is not None:  # pragma: no cover - loop always returns/raises
        raise last_error


def _is_retryable_rename_error(error: OSError) -> bool:
    return isinstance(error, PermissionError) or getattr(error, "winerror", None) in {5, 32, 33}


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Durably replace a JSON file without exposing a partially written file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fieldnames: Sequence[str],
) -> None:
    """Replace a UTF-8 CSV only after its complete contents are durable."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = SpreadsheetSafeWriter(
                csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
