import json
import os
import time
import csv
from types import SimpleNamespace

import pytest

from processing import io_utils
from processing.io_utils import (
    atomic_write_csv,
    assert_confined_input_file,
    assert_local_filesystem_path_syntax,
    assert_safe_output_path,
    exclusive_process_lock,
    make_staging_directory,
    publish_directory,
)


@pytest.mark.parametrize(
    "value",
    (
        r"\\server\share\clip.mp4",
        "//server/share/clip.mp4",
        r"\\?\UNC\server\share\clip.mp4",
        r"\\.\PhysicalDrive0",
        r"\\?\C:\research\clip.mp4",
    ),
)
def test_local_path_syntax_rejects_network_and_device_namespaces_before_io(value) -> None:
    with pytest.raises(ValueError, match="network|device|namespace"):
        assert_local_filesystem_path_syntax(value, description="test input")


def test_confined_input_rejects_file_symlink_that_escapes_selected_root(tmp_path) -> None:
    root = tmp_path / "selected"
    root.mkdir()
    outside = tmp_path / "private.mp4"
    outside.write_bytes(b"private")
    alias = root / "clip.mp4"
    try:
        alias.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="symbolic link|reparse|outside"):
        assert_confined_input_file(alias, root, description="test input")


def test_atomic_csv_neutralizes_dynamic_headers_and_values(tmp_path) -> None:
    output = tmp_path / "safe.csv"

    atomic_write_csv(
        output,
        [{"=label": "@attack", "signed": "-42"}],
        ("=label", "signed"),
    )

    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [["'=label", "signed"], ["'@attack", "-42"]]


def test_staging_directory_is_unique_readable_sibling(tmp_path) -> None:
    first = make_staging_directory(tmp_path, ".result-staging-")
    second = make_staging_directory(tmp_path, ".result-staging-")

    assert first.parent == tmp_path
    assert second.parent == tmp_path
    assert first != second
    (first / "proof.txt").write_text("readable", encoding="utf-8")
    promoted = tmp_path / "result"
    first.rename(promoted)
    assert (promoted / "proof.txt").read_text(encoding="utf-8") == "readable"


def test_staging_prefix_cannot_escape_parent(tmp_path) -> None:
    try:
        make_staging_directory(tmp_path, "../escape-")
    except ValueError as exc:
        assert "file-name component" in str(exc)
    else:
        raise AssertionError("unsafe prefix was accepted")


def test_safe_output_rejects_git_metadata_but_allows_external_custom_path(tmp_path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".git").mkdir()
    source = repository / "Videos"
    source.mkdir()

    with pytest.raises(ValueError, match="Git metadata"):
        assert_safe_output_path(
            repository / ".git" / "generated",
            repository_root=repository,
            protected_sources=(source,),
        )

    external = tmp_path / "separate-output" / "result"
    assert assert_safe_output_path(
        external,
        repository_root=repository,
        protected_sources=(source,),
    ) == external.resolve()


def test_safe_output_rejects_symlinked_ancestor_when_supported(tmp_path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="symbolic link, junction, or reparse"):
        assert_safe_output_path(linked_parent / "new-output")
    with pytest.raises(ValueError, match="symbolic link, junction, or reparse"):
        assert_safe_output_path(linked_parent / ".." / "normal-looking-output")


def test_windows_reparse_attribute_is_a_junction_compatibility_fallback(tmp_path) -> None:
    metadata = SimpleNamespace(st_file_attributes=0x0400)

    assert io_utils._is_windows_junction_or_reparse(tmp_path / "candidate", metadata)


def test_publish_directory_replaces_complete_target(tmp_path) -> None:
    target = tmp_path / "result"
    target.mkdir()
    (target / "value.txt").write_text("old", encoding="utf-8")
    staging = make_staging_directory(tmp_path, ".result-staging-")
    (staging / "value.txt").write_text("new", encoding="utf-8")

    publish_directory(staging, target)

    assert (target / "value.txt").read_text(encoding="utf-8") == "new"
    assert not staging.exists()
    assert not list(tmp_path.glob(".result.backup.*"))


def test_publish_directory_revalidates_target_before_rename(tmp_path, monkeypatch) -> None:
    target = tmp_path / "result"
    target.mkdir()
    (target / "value.txt").write_text("old", encoding="utf-8")
    staging = make_staging_directory(tmp_path, ".result-staging-")
    (staging / "value.txt").write_text("new", encoding="utf-8")
    real_validator = io_utils.assert_safe_output_path
    target_checks = 0

    def fail_second_target_check(path, **kwargs):
        nonlocal target_checks
        result = real_validator(path, **kwargs)
        if result == target.resolve():
            target_checks += 1
            if target_checks == 2:
                raise ValueError("simulated path alias race")
        return result

    monkeypatch.setattr(io_utils, "assert_safe_output_path", fail_second_target_check)

    with pytest.raises(ValueError, match="simulated path alias race"):
        publish_directory(staging, target)

    assert (target / "value.txt").read_text(encoding="utf-8") == "old"
    assert (staging / "value.txt").read_text(encoding="utf-8") == "new"


def test_publish_directory_restores_previous_target_on_failed_promotion(
    tmp_path, monkeypatch
) -> None:
    target = tmp_path / "result"
    target.mkdir()
    (target / "value.txt").write_text("old", encoding="utf-8")
    staging = make_staging_directory(tmp_path, ".result-staging-")
    (staging / "value.txt").write_text("new", encoding="utf-8")
    real_rename = io_utils._rename_directory_with_retry
    calls = 0

    def fail_promotion(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("simulated lock")
        return real_rename(source, destination)

    monkeypatch.setattr(io_utils, "_rename_directory_with_retry", fail_promotion)

    with pytest.raises(PermissionError, match="simulated"):
        publish_directory(staging, target)

    assert (target / "value.txt").read_text(encoding="utf-8") == "old"
    assert staging.is_dir()


def test_publish_directory_rejects_live_lock(tmp_path) -> None:
    target = tmp_path / "result"
    staging = make_staging_directory(tmp_path, ".result-staging-")
    lock = tmp_path / ".result.publish.lock"
    lock.write_text(json.dumps({"pid": io_utils.os.getpid()}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="Another process"):
        publish_directory(staging, target)


def test_publish_directory_requires_sibling_staging(tmp_path) -> None:
    staging = tmp_path / "elsewhere" / "staging"
    staging.mkdir(parents=True)
    with pytest.raises(ValueError, match="siblings"):
        publish_directory(staging, tmp_path / "result")


def test_publish_directory_recovers_backup_left_by_dead_process(
    tmp_path, monkeypatch
) -> None:
    target = tmp_path / "result"
    abandoned = tmp_path / ".result.backup.abandoned"
    abandoned.mkdir()
    (abandoned / "value.txt").write_text("last-good", encoding="utf-8")
    staging = make_staging_directory(tmp_path, ".result-staging-")
    (staging / "value.txt").write_text("candidate", encoding="utf-8")
    (tmp_path / ".result.publish.lock").write_text(
        json.dumps({"pid": 999_999_999}), encoding="utf-8"
    )
    real_rename = io_utils._rename_directory_with_retry
    calls = 0

    def fail_new_candidate(source, destination):
        nonlocal calls
        calls += 1
        # restore abandoned -> target, target -> new backup, then fail staging promotion
        if calls == 3:
            raise PermissionError("candidate could not be promoted")
        return real_rename(source, destination)

    monkeypatch.setattr(io_utils, "_rename_directory_with_retry", fail_new_candidate)

    with pytest.raises(PermissionError, match="candidate"):
        publish_directory(staging, target)

    assert (target / "value.txt").read_text(encoding="utf-8") == "last-good"


def test_publish_directory_cleans_backup_left_after_completed_crash(tmp_path) -> None:
    target = tmp_path / "result"
    target.mkdir()
    (target / "value.txt").write_text("current", encoding="utf-8")
    abandoned = tmp_path / ".result.backup.old-run"
    abandoned.mkdir()
    (abandoned / "value.txt").write_text("older", encoding="utf-8")
    staging = make_staging_directory(tmp_path, ".result-staging-")
    (staging / "value.txt").write_text("new", encoding="utf-8")

    publish_directory(staging, target)

    assert (target / "value.txt").read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob(".result.backup.*"))


def test_process_lock_is_released_after_context(tmp_path) -> None:
    lock = tmp_path / ".pipeline.run.lock"

    with exclusive_process_lock(lock, purpose="running a test"):
        owner = json.loads(lock.read_text(encoding="utf-8"))
        assert owner["pid"] == os.getpid()
        assert owner["lock_id"]

    assert not lock.exists()


def test_process_lock_rejects_recycled_pid_owner(tmp_path, monkeypatch) -> None:
    lock = tmp_path / ".pipeline.run.lock"
    lock.write_text(
        json.dumps(
            {
                "lock_id": "old",
                "pid": os.getpid(),
                "process_started_at_unix": 1.0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(io_utils, "_pid_matches_owner", lambda *_args: False)

    with exclusive_process_lock(lock, purpose="running a replacement"):
        owner = json.loads(lock.read_text(encoding="utf-8"))
        assert owner["lock_id"] != "old"


def test_recent_malformed_process_lock_is_not_removed(tmp_path) -> None:
    lock = tmp_path / ".pipeline.run.lock"
    lock.write_text("incomplete", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Another process"):
        with exclusive_process_lock(lock, purpose="running a test"):
            raise AssertionError("lock should not have been acquired")


def test_old_malformed_process_lock_is_recovered(tmp_path) -> None:
    lock = tmp_path / ".pipeline.run.lock"
    lock.write_text("incomplete", encoding="utf-8")
    old = time.time() - 25 * 60 * 60
    os.utime(lock, (old, old))

    with exclusive_process_lock(lock, purpose="running a replacement"):
        assert json.loads(lock.read_text(encoding="utf-8"))["lock_id"]
