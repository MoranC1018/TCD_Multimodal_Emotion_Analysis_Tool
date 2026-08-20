from __future__ import annotations

from pathlib import Path

from procurement.procurement_beta.readiness import build_readiness_report, default_module_exists


def test_build_readiness_report_marks_required_tools_and_optional_models() -> None:
    report = build_readiness_report(
        command_exists=lambda name: name == "ffmpeg",
        module_exists=lambda name: name in {"cv2", "mediapipe"},
        token_provider=lambda: "token",
        opencv_zoo_models_ready=lambda: True,
    )

    by_id = {item["id"]: item for item in report["items"]}

    assert by_id["ffmpeg"]["ready"] is True
    assert by_id["yt-dlp"]["ready"] is False
    assert by_id["opencv"]["ready"] is True
    assert by_id["opencv-zoo-models"]["ready"] is True
    assert by_id["mediapipe"]["ready"] is True
    assert by_id["pyannote"]["ready"] is False
    assert by_id["torch"]["ready"] is False
    assert by_id["huggingface-token"]["ready"] is True
    assert report["canRun"] is False
    assert report["modelBackedFace"] is True
    assert report["modelBackedVoice"] is False
    assert report["canProduceCleanSegments"] is False
    assert report["voiceBackends"] == {"pyannoteWithToken": False, "speechbrainEcapa": False}


def test_model_backed_face_requires_opencv_zoo_models() -> None:
    report = build_readiness_report(
        command_exists=lambda _name: True,
        module_exists=lambda name: name == "cv2",
        token_provider=lambda: "",
        opencv_zoo_models_ready=lambda: False,
    )

    assert report["modelBackedFace"] is False
    assert report["canProduceCleanSegments"] is False


def test_clean_segment_readiness_requires_face_and_voice_models() -> None:
    report = build_readiness_report(
        command_exists=lambda _name: True,
        module_exists=lambda name: name in {"cv2", "pyannote.audio"},
        token_provider=lambda: "token",
        opencv_zoo_models_ready=lambda: True,
    )

    assert report["canRun"] is True
    assert report["modelBackedFace"] is True
    assert report["modelBackedVoice"] is True
    assert report["canProduceCleanSegments"] is True


def test_speechbrain_ecapa_can_satisfy_voice_readiness_without_hf_token() -> None:
    report = build_readiness_report(
        command_exists=lambda _name: True,
        module_exists=lambda name: name in {"cv2", "speechbrain", "torch"},
        token_provider=lambda: "",
        opencv_zoo_models_ready=lambda: True,
    )

    assert report["modelBackedFace"] is True
    assert report["modelBackedVoice"] is True
    assert report["canProduceCleanSegments"] is True
    assert report["voiceBackends"] == {"pyannoteWithToken": False, "speechbrainEcapa": True}


def test_default_module_exists_returns_false_for_missing_dotted_package() -> None:
    assert default_module_exists("definitely_missing_procurement_beta_package.audio") is False


def test_readiness_reports_the_exact_trusted_media_tool_paths() -> None:
    selected = {
        "ffmpeg": Path(r"C:\trusted\ffmpeg.exe"),
        "ffprobe": Path(r"C:\trusted\ffprobe.exe"),
    }
    report = build_readiness_report(
        tool_resolver=lambda name: selected[name],
        yt_dlp_available=lambda: True,
        module_exists=lambda _name: False,
        token_provider=lambda: "",
        opencv_zoo_models_ready=lambda: False,
    )
    by_id = {item["id"]: item for item in report["items"]}

    assert by_id["ffmpeg"]["selectedPath"] == str(selected["ffmpeg"])
    assert by_id["ffprobe"]["selectedPath"] == str(selected["ffprobe"])
    assert by_id["yt-dlp"]["selectedPath"].endswith(r"python.exe -E -P -m yt_dlp")
