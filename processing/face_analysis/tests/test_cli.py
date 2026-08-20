from __future__ import annotations

import json
from pathlib import Path

from processing.face_analysis import __main__ as cli
from processing.face_analysis.health import ModelPreparation, Readiness
from processing.face_analysis.pipeline import FaceProcessingResult


READY = Readiness(
    ready=True,
    ffprobe=True,
    pyfeat=True,
    torch=True,
    device="cpu",
    detail="ready",
    pyarrow=True,
    torchcodec=True,
    ffmpeg_major=8,
    detector=True,
    model_weights={"status": "ready"},
)


def test_cli_prints_failed_video_stage_and_reason(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "check_readiness", lambda _device: READY)
    manifest = tmp_path / "run_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "videos": [
                    {
                        "input_relative": "UK/Speaker/video.mp4",
                        "status": "failed",
                        "error_stage": "transform",
                        "error_type": "RuntimeError",
                        "error_message": "FaceScore is missing",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = FaceProcessingResult(
        input_path=tmp_path / "video.mp4",
        output_root=tmp_path,
        processed=0,
        skipped=0,
        failed=1,
        run_manifest=manifest,
        run_index=tmp_path / "run_index.csv",
        run_id="test-run",
    )
    monkeypatch.setattr(cli, "process_face_input", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(cli.sys, "argv", ["face-analysis", str(tmp_path / "video.mp4")])

    assert cli.main() == 1
    captured = capsys.readouterr()
    assert "UK/Speaker/video.mp4" in captured.err
    assert "[transform]" in captured.err
    assert "RuntimeError: FaceScore is missing" in captured.err


def test_prepare_models_cli_prints_structured_success_and_returns_zero(
    monkeypatch, capsys
) -> None:
    preparation = ModelPreparation(
        ready=True,
        device="cpu",
        detail="all checkpoint files verified",
        model_weights={"status": "ready", "components": {}},
    )
    monkeypatch.setattr(cli, "prepare_detector_models", lambda device: preparation)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        ["face-analysis", "--prepare-models", "--device", "cpu"],
    )

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "prepare-models"
    assert payload["status"] == "ready"
    assert payload["ready"] is True
    assert payload["device"] == "cpu"


def test_prepare_models_cli_returns_nonzero_for_structured_failure(
    monkeypatch, capsys
) -> None:
    preparation = ModelPreparation(
        ready=False,
        device="cpu",
        detail="download failed",
        model_weights={"status": "incomplete"},
    )
    monkeypatch.setattr(cli, "prepare_detector_models", lambda _device: preparation)
    monkeypatch.setattr(cli.sys, "argv", ["face-analysis", "--prepare-models"])

    assert cli.main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["ready"] is False
    assert payload["detail"] == "download failed"


def test_check_cli_forwards_the_requested_device(monkeypatch, capsys) -> None:
    seen: list[str] = []
    readiness = Readiness(
        ready=True,
        ffprobe=True,
        pyfeat=True,
        torch=True,
        device="cpu",
        detail="ready",
        pyarrow=True,
        torchcodec=True,
        ffmpeg_major=8,
        detector=True,
        model_weights={"status": "ready"},
    )
    monkeypatch.setattr(
        cli,
        "check_readiness",
        lambda device: seen.append(device) or readiness,
    )
    monkeypatch.setattr(cli.sys, "argv", ["face-analysis", "--check", "--device", "cpu"])

    assert cli.main() == 0
    assert seen == ["cpu"]
    assert json.loads(capsys.readouterr().out)["device"] == "cpu"


def test_face_cli_returns_130_without_traceback_on_keyboard_interrupt(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli, "check_readiness", lambda _device: READY)
    monkeypatch.setattr(
        cli,
        "process_face_input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(cli.sys, "argv", ["face-analysis", str(tmp_path / "video.mp4")])

    assert cli.main() == 130
    captured = capsys.readouterr()
    assert "cancelled" in captured.err
    assert "Traceback" not in captured.err


def test_face_cli_prints_concise_startup_error_unless_debug(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli, "check_readiness", lambda _device: READY)
    monkeypatch.setattr(
        cli,
        "process_face_input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("unsafe output")),
    )
    monkeypatch.setattr(cli.sys, "argv", ["face-analysis", str(tmp_path / "video.mp4")])

    assert cli.main() == 1
    captured = capsys.readouterr()
    assert "ValueError: unsafe output" in captured.err
    assert "Traceback" not in captured.err
