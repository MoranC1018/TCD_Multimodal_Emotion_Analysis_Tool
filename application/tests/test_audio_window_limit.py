from pathlib import Path

import pytest

from application.backend import AudioRunRequest, build_audio_command


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_audio_emotion_window_limit_is_rejected_before_launch(mode):
    request = AudioRunRequest(
        mode=mode, source_path=Path("input.mp4"), output_root=Path("output"),
        window_seconds=20, include_emotions=True,
    )
    with pytest.raises(ValueError, match="15"):
        build_audio_command(request, repo_root=Path("repo"))


def test_long_opensmile_only_window_remains_available():
    request = AudioRunRequest(
        mode="single", source_path=Path("input.mp4"), output_root=Path("output"),
        window_seconds=20, include_emotions=False,
    )
    command = build_audio_command(request, repo_root=Path("repo"))
    assert "--skip-emotion-models" in command
    assert float(command[command.index("--window-seconds") + 1]) == 20
