from __future__ import annotations

import importlib.util
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from procurement.procurement_beta.detectors import OPENCV_ZOO_MODELS, local_model_cache_dir, model_file_ready
from procurement.external_tools import resolve_media_binary, yt_dlp_is_available as yt_dlp_module_available
from application import backend


def build_readiness_report(
    *,
    command_exists: Callable[[str], bool] | None = None,
    tool_resolver: Callable[[str], Path] | None = None,
    yt_dlp_available: Callable[[], bool] | None = None,
    module_exists: Callable[[str], bool] | None = None,
    token_provider: Callable[[], str] | None = None,
    opencv_zoo_models_ready: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Return local dependency readiness for clean speaker beta runs."""

    module_exists = module_exists or default_module_exists
    token_provider = token_provider or backend.load_huggingface_token
    opencv_zoo_models_ready = opencv_zoo_models_ready or default_opencv_zoo_models_ready
    selected_paths: dict[str, str] = {}
    tool_ready: dict[str, bool] = {}
    if tool_resolver is not None or command_exists is None:
        resolver = tool_resolver or (lambda name: resolve_media_binary(name))
        for name in ("ffmpeg", "ffprobe"):
            try:
                selected = resolver(name)
            except (FileNotFoundError, ValueError):
                tool_ready[name] = False
            else:
                tool_ready[name] = True
                selected_paths[name] = str(selected)
    else:
        for name in ("ffmpeg", "ffprobe"):
            tool_ready[name] = bool(command_exists(name))
            if tool_ready[name]:
                selected_paths[name] = name

    ytdlp_ready = bool((yt_dlp_available or yt_dlp_module_available)()) if command_exists is None or yt_dlp_available is not None else bool(command_exists("yt-dlp"))
    if ytdlp_ready:
        selected_paths["yt-dlp"] = f"{Path(sys.executable).resolve()} -E -P -m yt_dlp"

    items = [
        readiness_item("ffmpeg", "ffmpeg", tool_ready["ffmpeg"], True, "Required for cutting, stitching, and audio extraction.", selected_paths.get("ffmpeg", "")),
        readiness_item("ffprobe", "ffprobe", tool_ready["ffprobe"], True, "Required for trusted media inspection.", selected_paths.get("ffprobe", "")),
        readiness_item("yt-dlp", "yt-dlp", ytdlp_ready, True, "Required for YouTube inputs from DOCX rows.", selected_paths.get("yt-dlp", "")),
        readiness_item("opencv", "OpenCV", module_exists("cv2"), False, "Optional model-backed face detection support."),
        readiness_item("opencv-zoo-models", "OpenCV Zoo YuNet/SFace models", opencv_zoo_models_ready(), False, "Needed for identity-backed face selection without bundling model weights."),
        readiness_item("mediapipe", "MediaPipe", module_exists("mediapipe"), False, "Optional landmark/head-pose quality support."),
        readiness_item("pyannote", "pyannote.audio", module_exists("pyannote.audio"), False, "Optional speaker diarization support."),
        readiness_item("speechbrain", "SpeechBrain", module_exists("speechbrain"), False, "Optional ECAPA speaker embedding support."),
        readiness_item("torch", "PyTorch", module_exists("torch"), False, "Needed for SpeechBrain ECAPA inference."),
        readiness_item("huggingface-token", "Hugging Face token", bool(token_provider()), False, "Needed for some free gated diarization models."),
    ]
    by_id = {str(item["id"]): item for item in items}
    can_run = bool(by_id["ffmpeg"]["ready"] and by_id["ffprobe"]["ready"] and by_id["yt-dlp"]["ready"])
    model_backed_face = bool(by_id["opencv"]["ready"] and by_id["opencv-zoo-models"]["ready"])
    pyannote_voice = bool(by_id["pyannote"]["ready"] and by_id["huggingface-token"]["ready"])
    speechbrain_voice = bool(by_id["speechbrain"]["ready"] and by_id["torch"]["ready"])
    model_backed_voice = bool(pyannote_voice or speechbrain_voice)
    return {
        "items": items,
        "canRun": can_run,
        "modelBackedFace": model_backed_face,
        "modelBackedVoice": model_backed_voice,
        "canProduceCleanSegments": bool(can_run and model_backed_face and model_backed_voice),
        "hasSpeechBrain": bool(by_id["speechbrain"]["ready"]),
        "voiceBackends": {
            "pyannoteWithToken": pyannote_voice,
            "speechbrainEcapa": speechbrain_voice,
        },
    }


def readiness_item(
    item_id: str,
    label: str,
    ready: bool,
    required: bool,
    detail: str,
    selected_path: str = "",
) -> dict[str, object]:
    item = {
        "id": item_id,
        "label": label,
        "ready": bool(ready),
        "required": bool(required),
        "detail": detail,
    }
    if selected_path:
        item["selectedPath"] = selected_path
    return item


def default_command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def default_module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def default_opencv_zoo_models_ready() -> bool:
    """Return true only when the local cache contains real ONNX model files."""

    cache_dir = local_model_cache_dir() / "opencv_zoo"
    for metadata in OPENCV_ZOO_MODELS.values():
        if not model_file_ready(cache_dir / str(metadata["filename"]), str(metadata["sha256"])):
            return False
    return True
