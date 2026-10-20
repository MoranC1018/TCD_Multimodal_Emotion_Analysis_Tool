from __future__ import annotations

import os
from pathlib import Path

import pytest

from processing import ffmpeg_runtime


@pytest.mark.parametrize("path_mode", ("empty", "non_ffmpeg"))
def test_machine_winget_ffmpeg_is_found_without_a_usable_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path_mode: str,
) -> None:
    local_app_data = tmp_path / "LocalAppData"
    program_files = tmp_path / "Program Files"
    ffmpeg_bin = (
        program_files
        / "WinGet"
        / "Packages"
        / "Gyan.FFmpeg.Shared_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / f"ffmpeg-{ffmpeg_runtime.SUPPORTED_FFMPEG_RELEASE}-full_build-shared"
        / "bin"
    )
    ffmpeg_bin.mkdir(parents=True)
    for filename in ffmpeg_runtime.REQUIRED_FFMPEG8_FILES:
        (ffmpeg_bin / filename).write_bytes(b"test")

    path_value = ""
    if path_mode == "non_ffmpeg":
        non_ffmpeg = tmp_path / "ordinary-path-entry"
        non_ffmpeg.mkdir()
        path_value = str(non_ffmpeg)

    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.setenv("PATH", path_value)
    monkeypatch.setattr(ffmpeg_runtime, "_running_on_windows", lambda: True)
    monkeypatch.setattr(ffmpeg_runtime, "_add_dll_directory", lambda _path: object())
    monkeypatch.setattr(ffmpeg_runtime, "_CONFIGURED_PATH", None)
    monkeypatch.setattr(ffmpeg_runtime, "_DLL_HANDLES", [])

    resolved = ffmpeg_runtime.configure_ffmpeg_shared_libraries()

    assert resolved == ffmpeg_bin.resolve()
    assert os.environ["PATH"].split(os.pathsep)[0] == str(ffmpeg_bin.resolve())
