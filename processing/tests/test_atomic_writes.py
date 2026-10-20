"""Atomic publication survives brief Windows locks without losing old output."""

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import threading

import pytest

from processing import io_utils


@contextmanager
def _deny_delete_sharing(path: Path):
    """Hold a real Windows reader that allows reads/writes but blocks rename."""

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    handle = create_file(str(path), 0x80000000, 0x00000003, None, 3, 0, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())

    def release():
        nonlocal handle
        if handle is not None:
            if not close_handle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            handle = None

    try:
        yield release
    finally:
        release()


@pytest.fixture(params=("json", "csv"))
def atomic_writer(request):
    if request.param == "json":
        return (
            lambda path: io_utils.atomic_write_json(path, {"version": "new"}),
            b'{\n  "version": "new"\n}\n',
        )
    return (
        lambda path: io_utils.atomic_write_csv(path, [{"version": "new"}], ("version",)),
        b"version\r\nnew\r\n",
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing-mode regression")
def test_atomic_write_retries_until_windows_reader_releases_destination(
    tmp_path, monkeypatch, atomic_writer,
) -> None:
    write, expected = atomic_writer
    destination = tmp_path / "report"
    previous = b"previous complete output\n"
    destination.write_bytes(previous)
    real_replace = io_utils.os.replace
    blocked_errors = []
    release_requested = threading.Event()

    def observed_replace(source, target):
        assert destination.read_bytes() == previous
        assert Path(source).read_bytes() == expected
        try:
            return real_replace(source, target)
        except OSError as error:
            blocked_errors.append(error)
            release_requested.set()
            raise

    monkeypatch.setattr(io_utils.os, "replace", observed_replace)
    thread_errors = []
    with _deny_delete_sharing(destination) as release:
        def unlock_after_failed_replace():
            try:
                if not release_requested.wait(timeout=10):
                    raise RuntimeError("No replacement attempt reached the Windows lock")
                release()
            except BaseException as error:
                thread_errors.append(error)

        unlocker = threading.Thread(target=unlock_after_failed_replace)
        unlocker.start()
        try:
            write(destination)
        finally:
            release_requested.set()
            unlocker.join(timeout=10)

    assert not unlocker.is_alive()
    assert not thread_errors
    assert blocked_errors and blocked_errors[0].winerror in {5, 32, 33}
    assert destination.read_bytes() == expected
    assert list(tmp_path.glob(".report.*.tmp")) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing-mode regression")
def test_atomic_write_bounds_windows_lock_retries_and_preserves_old_output(
    tmp_path, monkeypatch, atomic_writer,
) -> None:
    write, _expected = atomic_writer
    destination = tmp_path / "report"
    previous = b"previous complete output\n"
    destination.write_bytes(previous)
    real_replace = io_utils.os.replace
    attempts = []

    def observed_replace(source, target):
        attempts.append((source, target))
        return real_replace(source, target)

    monkeypatch.setattr(io_utils.os, "replace", observed_replace)
    monkeypatch.setattr(io_utils.time, "sleep", lambda _delay: None)
    with _deny_delete_sharing(destination):
        with pytest.raises(PermissionError) as failure:
            write(destination)

    assert failure.value.winerror in {5, 32, 33}
    assert len(attempts) == 6
    assert destination.read_bytes() == previous
    assert list(tmp_path.glob(".report.*.tmp")) == []


def test_atomic_write_propagates_nonretryable_error_without_touching_old_output(
    tmp_path, monkeypatch, atomic_writer,
) -> None:
    write, _expected = atomic_writer
    destination = tmp_path / "report"
    previous = b"previous complete output\n"
    destination.write_bytes(previous)
    failure = OSError(errno.ENOSPC, "No space left on device")
    attempts = []

    def fail_replace(source, target):
        attempts.append((source, target))
        raise failure

    monkeypatch.setattr(io_utils.os, "replace", fail_replace)
    with pytest.raises(OSError) as raised:
        write(destination)

    assert raised.value is failure
    assert len(attempts) == 1
    assert destination.read_bytes() == previous
    assert list(tmp_path.glob(".report.*.tmp")) == []
