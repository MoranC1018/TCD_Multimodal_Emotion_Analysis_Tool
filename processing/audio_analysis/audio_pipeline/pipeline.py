from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from procurement.external_tools import credential_free_media_environment
from processing.io_utils import assert_confined_input_file, assert_safe_output_path

from .audio_analysis_csv import (
    build_audio_analysis_metadata,
    build_audio_analysis_rows,
    write_audio_analysis_csv,
)
from .config import (
    resolve_ffmpeg_binary,
    resolve_ffprobe_binary,
    resolve_opensmile_binary,
    resolve_opensmile_config,
)
from .emotion_models import (
    EmotionModelBundle,
    EmotionModelResult,
    EmotionModels,
    load_debug_fallback_emotion_models,
)
from .media import export_window_wav, extract_mono_wav, probe_duration_seconds
from .opensmile_runner import run_opensmile_windows
from .windows import make_windows


ProgressCallback = Callable[[str], None]
MAX_AUDIO_INPUT_BYTES = 20 * 1024 * 1024 * 1024
MAX_AUDIO_DURATION_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class SingleVideoResult:
    """Files produced for one analysed MP4."""

    output_dir: Path
    audio_analysis_csv: Path
    opensmile_csv: Path
    manifest_path: Path
    window_count: int


def run_single_video(
    input_video: Path,
    output_dir: Path,
    *,
    window_seconds: float = 10.0,
    stride_seconds: float = 5.0,
    opensmile_feature_set: str = "egemaps",
    emotion_models: EmotionModels | None = None,
    skip_emotion_models: bool = False,
    device: str = "auto",
    keep_temp_audio: bool = False,
    debug: bool = False,
    debug_fallback_emotion_models: EmotionModels | None = None,
    source_context: dict[str, object] | None = None,
    progress: ProgressCallback | None = None,
) -> SingleVideoResult:
    """Run reproducible per-window audio feature/model extraction for one MP4."""

    input_video = assert_confined_input_file(
        input_video, Path(input_video).expanduser().parent, description="Audio input"
    )
    input_size_bytes = input_video.stat().st_size
    if input_size_bytes > MAX_AUDIO_INPUT_BYTES:
        raise ValueError(
            f"Audio input exceeds the {MAX_AUDIO_INPUT_BYTES} byte limit: {input_video}"
        )
    input_sha256 = _file_sha256(input_video)
    source_duration_seconds = probe_duration_seconds(input_video)
    if source_duration_seconds > MAX_AUDIO_DURATION_SECONDS:
        raise ValueError(
            f"Audio input exceeds the {MAX_AUDIO_DURATION_SECONDS} second duration limit."
        )
    output_dir = assert_safe_output_path(
        output_dir,
        protected_sources=(input_video,),
        description="Audio output",
    )
    emit_progress(progress, f"Input video: {input_video}")
    emit_progress(progress, f"Output folder: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    emit_progress(progress, "Preparing output files.")
    clean_single_video_outputs(output_dir)
    provenance = dict(source_context or {})
    if provenance:
        (output_dir / "source_context.json").write_text(
            json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    audio_analysis_csv = output_dir / "audio_analysis.csv"
    opensmile_csv = output_dir / "opensmile_features.csv"
    manifest_path = output_dir / "audio_analysis_manifest.json"

    if emotion_models is None:
        emit_progress(progress, "Loading emotion models.")
        emotion_models = EmotionModelBundle.load(skip=skip_emotion_models, device=device)
    if emotion_models.skipped:
        emit_progress(progress, "Emotion models skipped; writing OpenSMILE-only rows with blank model outputs.")
    else:
        emit_progress(progress, f"Emotion model device: {emotion_models.device}.")
        for error in getattr(emotion_models, "errors", []):
            emit_progress(progress, f"Model warning: {error}")

    with audio_workspace(output_dir, keep_temp_audio) as temp_path, owned_audio_source_snapshot(
        input_video,
        expected_sha256=input_sha256,
        expected_size_bytes=input_size_bytes,
    ) as analysis_input:
        snapshot_duration_seconds = probe_duration_seconds(analysis_input)
        if snapshot_duration_seconds > MAX_AUDIO_DURATION_SECONDS:
            raise ValueError(
                f"Audio input exceeds the {MAX_AUDIO_DURATION_SECONDS} second duration limit."
            )
        emit_progress(progress, "Extracting mono audio with ffmpeg.")
        audio_wav = extract_mono_wav(analysis_input, temp_path / "audio_16khz_mono.wav")
        emit_progress(progress, "Reading audio duration.")
        duration_seconds = probe_duration_seconds(audio_wav)
        windows = make_windows(duration_seconds, window_seconds, stride_seconds)
        emit_progress(
            progress,
            f"Running OpenSMILE {opensmile_feature_set} on {len(windows)} window(s).",
        )
        run_opensmile_windows(
            audio_wav,
            windows,
            opensmile_csv,
            feature_set=opensmile_feature_set,
        )
        emotion_results = run_emotion_models(
            audio_wav=audio_wav,
            windows=windows,
            temp_path=temp_path,
            emotion_models=emotion_models,
            progress=progress,
        )
        if debug and not skip_emotion_models:
            write_debug_fallback_outputs(
                input_video=input_video,
                output_dir=output_dir,
                audio_wav=audio_wav,
                opensmile_csv=opensmile_csv,
                windows=windows,
                temp_path=temp_path,
                fallback_models=debug_fallback_emotion_models,
                device=device,
                duration_seconds=duration_seconds,
                window_seconds=window_seconds,
                stride_seconds=stride_seconds,
                opensmile_feature_set=opensmile_feature_set,
                keep_temp_audio=keep_temp_audio,
                source_context=provenance,
                progress=progress,
            )
        elif debug:
            emit_progress(progress, "Debug fallback skipped because --skip-emotion-models is active.")

    emit_progress(progress, "Writing per-window model output table.")
    rows = build_audio_analysis_rows(
        input_video=input_video,
        windows=windows,
        emotion_results=emotion_results,
        emotion_models=emotion_models,
        opensmile_feature_set=opensmile_feature_set,
        window_seconds=window_seconds,
        stride_seconds=stride_seconds,
    )
    metadata = build_audio_analysis_metadata(
        input_video=input_video,
        emotion_models=emotion_models,
        opensmile_feature_set=opensmile_feature_set,
        window_seconds=window_seconds,
        stride_seconds=stride_seconds,
        source_context=provenance,
    )
    metadata["InputSHA256"] = input_sha256
    metadata["InputSizeBytes"] = str(input_size_bytes)
    if (
        input_video.stat().st_size != input_size_bytes
        or _file_sha256(input_video) != input_sha256
    ):
        clean_single_video_outputs(output_dir)
        raise ValueError(
            "Input video changed during audio analysis; no result manifest was published."
        )
    write_audio_analysis_csv(audio_analysis_csv, rows, metadata=metadata)
    emit_progress(progress, "Writing manifest.")
    write_single_manifest(
        manifest_path,
        input_video=input_video,
        audio_analysis_csv=audio_analysis_csv,
        opensmile_csv=opensmile_csv,
        emotion_models=emotion_models,
        duration_seconds=duration_seconds,
        window_seconds=window_seconds,
        stride_seconds=stride_seconds,
        window_count=len(windows),
        opensmile_feature_set=opensmile_feature_set,
        keep_temp_audio=keep_temp_audio,
        source_context=provenance,
        input_sha256=input_sha256,
        input_size_bytes=input_size_bytes,
    )
    emit_progress(progress, "Finished video.")

    return SingleVideoResult(
        output_dir=output_dir,
        audio_analysis_csv=audio_analysis_csv,
        opensmile_csv=opensmile_csv,
        manifest_path=manifest_path,
        window_count=len(windows),
    )


def emit_progress(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def run_emotion_models(
    *,
    audio_wav: Path,
    windows,
    temp_path: Path,
    emotion_models: EmotionModels,
    progress: ProgressCallback | None,
) -> list[EmotionModelResult]:
    if emotion_models.skipped:
        emit_progress(progress, "Emotion models skipped; leaving model-output columns blank.")
        return [EmotionModelResult.empty() for _window in windows]

    available_layers = []
    if getattr(emotion_models, "categorical_available", False):
        available_layers.append("categorical speech emotion")
    if getattr(emotion_models, "dimensional_available", False):
        available_layers.append("dimensional affect")

    if not available_layers:
        emit_progress(progress, "No emotion model layers are available; leaving model-output columns blank.")
        return [EmotionModelResult.empty() for _window in windows]

    layer_text = " and ".join(available_layers)
    emit_progress(progress, f"Running {layer_text} model layer(s) on {len(windows)} window(s).")
    results: list[EmotionModelResult] = []
    model_window_dir = temp_path / "model_windows"
    for window in windows:
        window_wav = export_window_wav(audio_wav, window, model_window_dir / f"window_{window.row:04d}.wav")
        results.append(emotion_models.predict_window(window_wav))
    return results


def write_debug_fallback_outputs(
    *,
    input_video: Path,
    output_dir: Path,
    audio_wav: Path,
    opensmile_csv: Path,
    windows,
    temp_path: Path,
    fallback_models: EmotionModels | None,
    device: str,
    duration_seconds: float,
    window_seconds: float,
    stride_seconds: float,
    opensmile_feature_set: str,
    keep_temp_audio: bool,
    source_context: dict[str, object],
    progress: ProgressCallback | None,
) -> None:
    """Write fallback-model outputs for debug comparison without changing main outputs."""

    emit_progress(progress, "Debug mode: loading categorical fallback model for separate comparison output.")
    fallback_models = fallback_models or load_debug_fallback_emotion_models(device=device)
    debug_dir = output_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    fallback_csv = debug_dir / "fallback_audio_analysis.csv"
    fallback_manifest = debug_dir / "fallback_audio_analysis_manifest.json"
    fallback_results = run_emotion_models(
        audio_wav=audio_wav,
        windows=windows,
        temp_path=temp_path / "debug_fallback",
        emotion_models=fallback_models,
        progress=progress,
    )
    rows = build_audio_analysis_rows(
        input_video=input_video,
        windows=windows,
        emotion_results=fallback_results,
        emotion_models=fallback_models,
        opensmile_feature_set=opensmile_feature_set,
        window_seconds=window_seconds,
        stride_seconds=stride_seconds,
    )
    metadata = build_audio_analysis_metadata(
        input_video=input_video,
        emotion_models=fallback_models,
        opensmile_feature_set=opensmile_feature_set,
        window_seconds=window_seconds,
        stride_seconds=stride_seconds,
        source_context=source_context,
    )
    metadata["Note"] = "Debug fallback categorical model output only. Not used in main audio_analysis.csv."
    write_audio_analysis_csv(fallback_csv, rows, metadata=metadata)
    write_single_manifest(
        fallback_manifest,
        input_video=input_video,
        audio_analysis_csv=fallback_csv,
        opensmile_csv=opensmile_csv,
        emotion_models=fallback_models,
        duration_seconds=duration_seconds,
        window_seconds=window_seconds,
        stride_seconds=stride_seconds,
        window_count=len(windows),
        opensmile_feature_set=opensmile_feature_set,
        keep_temp_audio=keep_temp_audio,
        source_context=source_context,
    )
    emit_progress(progress, f"Debug fallback output: {fallback_csv}")


@contextmanager
def audio_workspace(output_dir: Path, keep_temp_audio: bool) -> Iterator[Path]:
    if keep_temp_audio:
        debug_dir = output_dir / "_debug_audio"
        if debug_dir.exists():
            remove_generated_directory(debug_dir)
        debug_dir.mkdir(parents=True, exist_ok=True)
        yield debug_dir
    else:
        with tempfile.TemporaryDirectory(prefix="audio_analysis_") as temp_dir:
            yield Path(temp_dir)


@contextmanager
def owned_audio_source_snapshot(
    source: Path,
    *,
    expected_sha256: str,
    expected_size_bytes: int,
) -> Iterator[Path]:
    """Yield an owned copy that exactly matches the already-approved source bytes."""

    with tempfile.TemporaryDirectory(prefix="tcd-audio-source-") as temp_dir:
        snapshot = Path(temp_dir) / source.name
        before = source.stat()
        with source.open("rb") as source_handle, snapshot.open("xb") as snapshot_handle:
            shutil.copyfileobj(source_handle, snapshot_handle, length=1024 * 1024)
        after = source.stat()
        stable_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if (
            not stable_identity
            or snapshot.stat().st_size != expected_size_bytes
            or _file_sha256(snapshot) != expected_sha256
            or source.stat().st_size != expected_size_bytes
            or _file_sha256(source) != expected_sha256
        ):
            raise ValueError(
                "Input video changed while its immutable audio snapshot was created."
            )
        yield snapshot


def write_single_manifest(
    path: Path,
    *,
    input_video: Path,
    audio_analysis_csv: Path,
    opensmile_csv: Path,
    emotion_models: EmotionModels,
    duration_seconds: float,
    window_seconds: float,
    stride_seconds: float,
    window_count: int,
    opensmile_feature_set: str,
    keep_temp_audio: bool,
    source_context: dict[str, object] | None = None,
    input_sha256: str | None = None,
    input_size_bytes: int | None = None,
) -> Path:
    """Write per-video provenance in a compact machine-readable form."""

    provenance = source_context or {}
    user_metadata = provenance.get("user_metadata") if isinstance(provenance.get("user_metadata"), dict) else {}
    system_metadata = provenance.get("system_metadata") if isinstance(provenance.get("system_metadata"), dict) else {}
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pipeline": "Multimodal Emotion Analysis Tool audio research data extraction",
        "stage_role": "per-window machine-output extraction only; no final interpretation or statistics",
        "input_video": str(input_video),
        "input_sha256": input_sha256 or _file_sha256(input_video),
        "input_size_bytes": (
            int(input_size_bytes) if input_size_bytes is not None else input_video.stat().st_size
        ),
        "source_id": str(provenance.get("source_id") or ""),
        "source_speaker": str(provenance.get("speaker") or ""),
        "source_metadata": user_metadata,
        "user_language": str(user_metadata.get("Language") or ""),
        "youtube_language": str(system_metadata.get("youtube_language") or ""),
        "audio_analysis_csv": str(audio_analysis_csv),
        "opensmile_features_csv": str(opensmile_csv),
        "audio_analysis_contents": "per-window model outputs and probabilities",
        "opensmile_features_contents": "OpenSMILE numeric acoustic features for audit and later statistical analysis",
        "categorical_model_name": emotion_models.categorical_model_name,
        "categorical_model_version": emotion_models.categorical_model_version,
        "dimensional_model_name": emotion_models.dimensional_model_name,
        "dimensional_model_version": emotion_models.dimensional_model_version,
        "model_device": emotion_models.device,
        "emotion_models_skipped": emotion_models.skipped,
        "categorical_model_available": emotion_models.categorical_available,
        "dimensional_model_available": emotion_models.dimensional_available,
        "model_errors": emotion_models.errors or [],
        "duration_seconds": duration_seconds,
        "window_seconds": window_seconds,
        "stride_seconds": stride_seconds,
        "window_count": window_count,
        "note": "Audio waveform/acoustic analysis only. No transcription or text sentiment analysis.",
        "opensmile_feature_set": opensmile_feature_set,
        "ffmpeg_binary": tool_path(resolve_ffmpeg_binary),
        "ffmpeg_version": tool_version(resolve_ffmpeg_binary),
        "ffprobe_binary": tool_path(resolve_ffprobe_binary),
        "ffprobe_version": tool_version(resolve_ffprobe_binary),
        "opensmile_binary": tool_path(resolve_opensmile_binary),
        "opensmile_version": tool_version(resolve_opensmile_binary),
        "opensmile_config": tool_path(lambda: resolve_opensmile_config(feature_set=opensmile_feature_set)),
        "temporary_audio_kept": keep_temp_audio,
        "errors": [],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tool_path(resolver) -> str:
    try:
        return str(resolver())
    except Exception as exc:
        return f"unavailable: {exc}"


def tool_version(resolver) -> str:
    try:
        binary = resolver()
    except Exception as exc:
        return f"unavailable: {exc}"
    try:
        completed = subprocess.run(
            [str(binary), "-version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            env=credential_free_media_environment(),
        )
    except Exception as exc:
        return f"unavailable: {exc}"
    first_line = (completed.stdout or completed.stderr).splitlines()
    return first_line[0] if first_line else ""


def clean_single_video_outputs(output_dir: Path) -> None:
    """Clean files generated by one previous per-video audio run."""

    for filename in ("audio_analysis.csv", "opensmile_features.csv", "audio_analysis_manifest.json", "source_context.json"):
        path = output_dir / filename
        if path.exists():
            path.unlink()

    # Remove earlier experimental output folders if present.
    for dirname in ("technical", "supporting_models", "logs", "_debug_audio", "debug"):
        path = output_dir / dirname
        if path.exists():
            remove_generated_directory(path)


def remove_generated_directory(path: Path) -> None:
    """Remove generated directories even when Windows marks them read-only."""

    def make_writable(function, failed_path, _exc_info):
        os.chmod(failed_path, stat.S_IREAD | stat.S_IWRITE)
        function(failed_path)

    shutil.rmtree(path, onerror=make_writable)
