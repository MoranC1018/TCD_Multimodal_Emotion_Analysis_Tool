from __future__ import annotations

import array
import hashlib
import inspect
import json
import os
import random
import re
import contextlib
import subprocess
import sys
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlretrieve

from procurement.procurement_beta.identity import assign_identity_clusters
from procurement.procurement_beta.intervals import Interval, intersect_intervals, merge_nearby_intervals
from procurement.procurement_beta.pipeline import ProcurementBetaOptions
from procurement.procurement_beta.resources import configure_torch_runtime_threads, pause_if_resource_pressure
from procurement.procurement_beta.runner import DetectionResult
from procurement.procurement_beta.speaker_profile import cosine_similarity
from application import backend
from procurement.external_tools import credential_free_media_environment, resolve_media_binary
from procurement.procurement_beta.model_integrity import (
    OPENCV_ZOO_MODELS,
    PYANNOTE_MODEL,
    PYANNOTE_MODEL_REVISION,
    SPEECHBRAIN_ECAPA_MODEL,
    SPEECHBRAIN_ECAPA_REVISION,
)
from procurement.input_limits import (
    MAX_FACE_REFERENCE_JSON_BYTES,
    MAX_FACE_REFERENCE_JSON_ITEMS,
    read_control_json,
)


IDENTITY_BASELINE_BATCH_SIZE = 10
IDENTITY_BASELINE_DOMINANCE = 0.60
RELAXED_IDENTITY_CLUSTER_DOMINANCE = 0.25
MIN_RELAXED_IDENTITY_CLUSTER_CANDIDATES = 12
MAX_IDENTITY_BASELINE_CLUSTER_CANDIDATES = 600
OPENCV_ZOO_IDENTITY_ON_THRESHOLD = 0.65
OPENCV_ZOO_IDENTITY_OFF_THRESHOLD = 0.60
INSIGHTFACE_IDENTITY_ON_THRESHOLD = 0.42
INSIGHTFACE_IDENTITY_OFF_THRESHOLD = 0.38
INSIGHTFACE_MIN_FACE_PX = 80
INSIGHTFACE_MIN_VISIBILITY_FACE_PX = 32
INSIGHTFACE_MIN_VISIBILITY_FACE_AREA = 0.0005
INSIGHTFACE_MIN_SAMPLE_STEP_SECONDS = 4.0
INSIGHTFACE_MIN_VALIDATION_STEP_SECONDS = 2.0
INSIGHTFACE_PROGRESS_SAMPLE_INTERVAL = 100
INSIGHTFACE_REFERENCE_WINDOW_SECONDS = 240.0
INSIGHTFACE_REFERENCE_SAMPLE_STEP_SECONDS = 2.0
INSIGHTFACE_MIN_EXPECTED_IDENTITY_SECONDS = 60.0
FINAL_STITCHED_VALIDATION_FPS = 1.0
FINAL_STITCHED_IDENTITY_THRESHOLD = 0.64
REFERENCE_EMBEDDING_FILENAME = "reference_embedding.json"
MIN_CLEAR_FACE_AREA = 0.004
MIN_CLEAR_FACE_EDGE_PX = 56
MIN_CLEAR_FACE_CENTER_SCORE = 0.22
MIN_CLEAR_FACE_BLUR_SCORE = 6.0
MAX_CONTEXT_FACE_COUNT = 3
MIN_OUTPUT_FACE_AREA = MIN_CLEAR_FACE_AREA
MIN_OUTPUT_FACE_EDGE_PX = 56
YUNET_DETECTOR_MAX_WIDTH = 640
HEURISTIC_AUDIO_ACTIVITY_CONFIDENCE = 0.40
STRICT_FACE_INTERVAL_GAP_SECONDS = 0.05
FIRST_PASS_FACE_INTERVAL_GAP_SECONDS = 1.5
MAX_CONSECUTIVE_DECODE_FAILURES = 30
SPEECHBRAIN_WINDOW_SECONDS = 5.0
SPEECHBRAIN_MIN_WINDOW_SECONDS = 2.5
SPEECHBRAIN_CLUSTER_SIMILARITY = 0.45
SPEECHBRAIN_DOMINANCE_RATIO = 0.40
SPEECHBRAIN_REFERENCE_SIMILARITY = 0.45
SPEECHBRAIN_REFERENCE_MAX_WINDOWS = 24
ACTIVE_THROTTLE_FRAME_INTERVAL = 250
ACTIVE_THROTTLE_AUDIO_WINDOW_INTERVAL = 25
OPENCV_ZOO_MODEL_LOCK = threading.Lock()
SPEECHBRAIN_MODEL_LOCK = threading.Lock()
SPEECHBRAIN_INFERENCE_LOCK = threading.Lock()


@dataclass(frozen=True)
class FrameCandidate:
    """A frame worth saving as an identity still."""

    timestamp: float
    confidence: float
    area: float
    blur_score: float
    frame: Any
    embedding: list[float] | None = None
    cluster_id: int | None = None
    face_count: int = 0
    dark_ratio: float = 0.0
    crop: Any | None = None
    center_score: float = 0.0
    face_width_px: int = 0
    face_height_px: int = 0


@dataclass(frozen=True)
class HaarFrameResult:
    """The face and context signals extracted from one sampled frame."""

    candidate: FrameCandidate | None
    face_count: int
    dark_ratio: float


@dataclass(frozen=True)
class FaceSample:
    """Detector output for one sampled video timestamp."""

    timestamp: float
    candidate: FrameCandidate | None
    face_count: int
    dark_ratio: float
    audience_like: bool
    stage_context: bool


class FaceVisibilityAnalyzer:
    """Detect when a face is visible and save representative identity stills."""

    def analyze(self, video_path: Path, output_dir: Path, options: ProcurementBetaOptions) -> DetectionResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        duration = backend.read_duration_seconds(video_path) or 0.0
        cv2 = optional_import("cv2")
        if cv2 is None:
            return DetectionResult(
                intervals=[],
                method="unavailable_face_model",
                artifacts=[],
                warnings=["Install opencv-python and the OpenCV Zoo YuNet/SFace models for identity-backed face visibility detection."],
            )
        opencv_zoo_result = analyze_with_opencv_zoo(cv2, video_path, output_dir, duration, options)
        if opencv_zoo_result is not None:
            return opencv_zoo_result
        return DetectionResult(
            intervals=[],
            method="unavailable_face_model",
            artifacts=[],
            warnings=["Verified OpenCV Zoo YuNet/SFace models were unavailable; face analysis stopped."],
        )

    def validate_segments(
        self,
        video_path: Path,
        output_dir: Path,
        candidate_intervals: list[Interval],
        options: ProcurementBetaOptions,
    ) -> DetectionResult:
        """Second-pass check over candidate clips before they are stitched."""

        if not candidate_intervals:
            return DetectionResult([], "face_segment_validation_skipped", [], ["No candidate face intervals needed validation."])

        duration = backend.read_duration_seconds(video_path) or 0.0
        cv2 = optional_import("cv2")
        if cv2 is None:
            return DetectionResult(
                candidate_intervals,
                "face_segment_validation_unavailable",
                [],
                ["OpenCV was unavailable; candidate face intervals were left unvalidated."],
            )

        result = validate_opencv_zoo_segments(cv2, video_path, output_dir, candidate_intervals, duration, options)
        if result is not None:
            return result
        return DetectionResult(
            candidate_intervals,
            "face_segment_validation_unavailable",
            [],
            ["OpenCV Zoo validation was unavailable; candidate face intervals were left unvalidated."],
        )


    def validate_stitched_output(
        self,
        video_path: Path,
        output_dir: Path,
        options: ProcurementBetaOptions,
    ) -> dict[str, Any]:
        """Sanity-check the final stitched video before reporting success."""

        duration = backend.read_duration_seconds(video_path) or 0.0
        cv2 = optional_import("cv2")
        if cv2 is None:
            return write_stitched_output_validation(
                output_dir,
                {
                    "available": False,
                    "failure_count": 1,
                    "failures": [{"reason": "OpenCV was unavailable for final stitched-output validation."}],
                },
            )

        result = validate_opencv_zoo_stitched_output(cv2, video_path, output_dir, duration, options)
        if result is not None:
            return result
        return write_stitched_output_validation(
            output_dir,
            {
                "available": False,
                "failure_count": 1,
                "failures": [{"reason": "OpenCV Zoo final stitched-output validation was unavailable."}],
            },
        )
class MainVoiceAnalyzer:
    """Find intervals where the dominant speaker is talking."""

    def __init__(self, reference_audio: Path | None = None) -> None:
        self.reference_audio = reference_audio.expanduser().resolve() if reference_audio else None

    def analyze(self, video_path: Path, output_dir: Path, options: ProcurementBetaOptions) -> DetectionResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        duration = backend.read_duration_seconds(video_path) or 0.0
        audio_path = output_dir / "main_voice_audio.wav"

        speechbrain_result = analyze_with_speechbrain_ecapa(
            video_path,
            audio_path,
            duration,
            options,
            reference_audio=self.reference_audio,
        )
        if speechbrain_result is not None:
            return speechbrain_result

        token = huggingface_token()
        if not token:
            return heuristic_voice_activity_result(
                video_path,
                audio_path,
                duration,
                options,
                "SpeechBrain ECAPA was not available and Hugging Face token was not available.",
            )

        pyannote = optional_import("pyannote.audio")
        if pyannote is None:
            return heuristic_voice_activity_result(
                video_path,
                audio_path,
                duration,
                options,
                "pyannote.audio was not available.",
            )

        extract_audio(video_path, audio_path)
        try:
            loader = pyannote.Pipeline.from_pretrained
            parameters = inspect.signature(loader).parameters
            auth_argument = "token" if "token" in parameters else "use_auth_token"
            pipeline = loader(
                PYANNOTE_MODEL,
                revision=PYANNOTE_MODEL_REVISION,
                **{auth_argument: token},
            )
            if options.device != "auto":
                torch = optional_import("torch")
                if torch is not None:
                    configure_torch_runtime_threads(torch, logger=lambda message: print(message, flush=True))
                    pipeline.to(torch.device(options.device))
            diarization = pipeline(str(audio_path))
            intervals = dominant_speaker_intervals(diarization, threshold=options.speaker_confidence)
            if intervals:
                artifacts = retain_voice_audio_artifacts(audio_path, output_dir, intervals, keep_debug=options.keep_debug)
                warnings = reference_audio_warnings(self.reference_audio)
                if not options.keep_debug:
                    warnings.append("Skipped retained main-speaker WAV artifacts because keep debug artifacts is off.")
                return DetectionResult(intervals, "pyannote_speaker_diarization_3_1", artifacts, warnings)
        except Exception as exc:
            artifacts = retain_failed_audio_artifact(audio_path, keep_debug=options.keep_debug)
            return DetectionResult(
                intervals=[],
                method="pyannote_speaker_diarization_error",
                artifacts=artifacts,
                warnings=[
                    f"pyannote diarization failed: {exc}",
                    "No voice intervals were accepted because clean speaker beta requires model-backed main-speaker diarization.",
                ],
            )

        artifacts = retain_failed_audio_artifact(audio_path, keep_debug=options.keep_debug)
        return DetectionResult(
            [],
            "pyannote_speaker_diarization_3_1",
            artifacts,
            ["No dominant speaker intervals found.", *reference_audio_warnings(self.reference_audio)],
        )


def heuristic_voice_activity_result(
    video_path: Path,
    audio_path: Path,
    duration: float,
    options: ProcurementBetaOptions,
    reason: str,
) -> DetectionResult:
    """Return a fail-closed local audio-activity result when diarization is unavailable."""

    intervals = detect_audio_activity(video_path, duration, confidence=HEURISTIC_AUDIO_ACTIVITY_CONFIDENCE)
    artifacts: list[Path] = []
    if options.keep_debug:
        extract_audio(video_path, audio_path)
        if audio_path.exists():
            artifacts.append(audio_path)
    return DetectionResult(
        intervals=intervals,
        method="heuristic_audio_activity_no_diarization",
        artifacts=artifacts,
        warnings=[
            f"{reason} Direct local audio activity was recorded below the clean confidence threshold instead of being treated as main-speaker diarization."
        ],
        )


def analyze_with_speechbrain_ecapa(
    video_path: Path,
    audio_path: Path,
    duration: float,
    options: ProcurementBetaOptions,
    *,
    reference_audio: Path | None,
) -> DetectionResult | None:
    """Use SpeechBrain ECAPA embeddings to find the dominant recurring voice."""

    speaker_module = optional_import("speechbrain.inference.speaker")
    torch = optional_import("torch")
    if torch is not None:
        configure_torch_runtime_threads(torch, logger=lambda message: print(message, flush=True))
    if speaker_module is None or torch is None:
        return None

    extract_audio(video_path, audio_path)
    if not audio_path.exists():
        return None

    try:
        with SPEECHBRAIN_MODEL_LOCK:
            classifier = load_speechbrain_ecapa_classifier(speaker_module, options)
    except Exception:
        retain_failed_audio_artifact(audio_path, keep_debug=options.keep_debug)
        return None

    active_intervals = detect_audio_activity(audio_path, duration, confidence=float(options.speaker_confidence))
    windows = build_speechbrain_embedding_windows(active_intervals)
    if not windows:
        artifacts = retain_failed_audio_artifact(audio_path, keep_debug=options.keep_debug)
        return DetectionResult(
            [],
            "speechbrain_ecapa_dominant_speaker",
            artifacts,
            ["SpeechBrain ECAPA loaded, but no non-silent windows were found."],
        )

    embeddings = embed_speechbrain_windows(
        classifier,
        torch,
        audio_path,
        windows,
        options=options,
        output_path=audio_path.parent,
        stage="voice embedding",
    )
    artifacts: list[Path] = []
    warnings: list[str] = []
    method = "speechbrain_ecapa_dominant_speaker"

    if reference_audio is not None:
        reference_embedding = build_reference_audio_embedding(
            classifier,
            torch,
            reference_audio,
            audio_path.parent,
            options,
        )
        if not reference_embedding:
            artifacts = retain_failed_audio_artifact(audio_path, keep_debug=options.keep_debug)
            return DetectionResult(
                [],
                "speechbrain_ecapa_reference_speaker_unavailable",
                artifacts,
                [
                    *reference_audio_warnings(reference_audio),
                    "Reference audio was supplied, but no ECAPA speaker profile could be embedded; no voice intervals were accepted.",
                ],
            )
        intervals = reference_embedding_intervals(
            windows,
            embeddings,
            reference_embedding,
            confidence=max(float(options.speaker_confidence), 0.65),
            similarity_threshold=SPEECHBRAIN_REFERENCE_SIMILARITY,
        )
        method = "speechbrain_ecapa_reference_speaker"
        warnings.extend(
            [
                "Used supplied reference audio to select matching SpeechBrain ECAPA speaker windows.",
                *reference_audio_warnings(reference_audio),
            ]
        )
    else:
        intervals = dominant_embedding_intervals(
            windows,
            embeddings,
            confidence=max(float(options.speaker_confidence), 0.65),
            similarity_threshold=SPEECHBRAIN_CLUSTER_SIMILARITY,
            dominance_ratio=SPEECHBRAIN_DOMINANCE_RATIO,
        )
        warnings.append("Used SpeechBrain ECAPA speaker embeddings to cluster active speech and select the dominant recurring voice.")
    if intervals:
        artifacts = retain_voice_audio_artifacts(audio_path, audio_path.parent, intervals, keep_debug=options.keep_debug)
        if not options.keep_debug:
            warnings.append("Skipped retained main-speaker WAV artifacts because keep debug artifacts is off.")
    else:
        warnings.append("No dominant SpeechBrain speaker cluster met the configured dominance threshold.")
        artifacts = retain_failed_audio_artifact(audio_path, keep_debug=options.keep_debug)

    return DetectionResult(intervals, method, artifacts, warnings)




def build_reference_audio_embedding(
    classifier: Any,
    torch: Any,
    reference_audio: Path,
    work_dir: Path,
    options: ProcurementBetaOptions,
) -> list[float]:
    """Build one ECAPA centroid from a supplied target-speaker audio file."""

    if not reference_audio.exists():
        return []
    work_dir.mkdir(parents=True, exist_ok=True)
    reference_wav = work_dir / "reference_voice_audio.wav"
    extract_audio(reference_audio, reference_wav)
    if not reference_wav.exists():
        return []

    duration = backend.read_duration_seconds(reference_wav) or wav_duration_seconds(reference_wav)
    active_intervals = detect_audio_activity(reference_wav, duration, confidence=float(options.speaker_confidence))
    windows = build_speechbrain_embedding_windows(active_intervals)[:SPEECHBRAIN_REFERENCE_MAX_WINDOWS]
    if not windows:
        remove_audio_scratch(reference_wav)
        return []

    embeddings = embed_speechbrain_windows(classifier, torch, reference_wav, windows)
    remove_audio_scratch(reference_wav)
    return embedding_centroid([embedding for embedding in embeddings if embedding])


def reference_embedding_intervals(
    windows: list[Interval],
    embeddings: list[list[float]],
    reference_embedding: list[float],
    *,
    confidence: float,
    similarity_threshold: float,
) -> list[Interval]:
    """Return speech windows matching a supplied reference-speaker centroid."""

    if not reference_embedding:
        return []
    selected = []
    for window, embedding in zip(windows, embeddings):
        if not embedding:
            continue
        if cosine_similarity(embedding, reference_embedding) >= similarity_threshold:
            selected.append(Interval(window.start, window.end, max(0.0, min(1.0, confidence))))
    return merge_nearby_intervals(selected, gap_seconds=0.1)


def embedding_centroid(embeddings: list[list[float]]) -> list[float]:
    """Average already-normalized embeddings and normalize the centroid."""

    if not embeddings:
        return []
    width = len(embeddings[0])
    centroid = [0.0] * width
    for embedding in embeddings:
        for index, value in enumerate(embedding[:width]):
            centroid[index] += float(value)
    centroid = [value / len(embeddings) for value in centroid]
    norm = sum(value * value for value in centroid) ** 0.5
    if norm == 0:
        return []
    return [value / norm for value in centroid]


def wav_duration_seconds(audio_path: Path) -> float:
    """Return WAV duration without requiring ffprobe metadata parsing."""

    try:
        with wave.open(str(audio_path), "rb") as handle:
            frame_rate = float(handle.getframerate() or 0)
            if frame_rate <= 0:
                return 0.0
            return float(handle.getnframes()) / frame_rate
    except Exception:
        return 0.0

def load_speechbrain_ecapa_classifier(speaker_module: Any, options: ProcurementBetaOptions) -> Any:
    """Load the ungated SpeechBrain ECAPA model into the local user cache."""

    savedir = local_model_cache_dir() / "speechbrain" / "spkrec-ecapa-voxceleb"
    savedir.mkdir(parents=True, exist_ok=True)
    run_opts = {}
    if options.device != "auto":
        run_opts["device"] = options.device
    kwargs: dict[str, Any] = {
        "source": SPEECHBRAIN_ECAPA_MODEL,
        "savedir": str(savedir),
        "run_opts": run_opts or None,
    }
    fetching_module = optional_import("speechbrain.utils.fetching")
    fetch_config_type = getattr(fetching_module, "FetchConfig", None)
    if fetch_config_type is None:
        raise RuntimeError("SpeechBrain FetchConfig is required to pin the ECAPA model revision.")
    kwargs["fetch_config"] = fetch_config_type(
        revision=SPEECHBRAIN_ECAPA_REVISION,
        allow_updates=True,
    )
    local_strategy = getattr(getattr(fetching_module, "LocalStrategy", None), "COPY", None)
    if local_strategy is not None:
        # COPY avoids Windows symlink privileges, which are often unavailable
        # on researcher laptops without Developer Mode or administrator rights.
        kwargs["local_strategy"] = local_strategy
    return speaker_module.EncoderClassifier.from_hparams(**kwargs)


def build_speechbrain_embedding_windows(
    active_intervals: list[Interval],
    *,
    window_seconds: float = SPEECHBRAIN_WINDOW_SECONDS,
    min_window_seconds: float = SPEECHBRAIN_MIN_WINDOW_SECONDS,
) -> list[Interval]:
    """Split non-silent audio into contiguous windows for speaker embeddings."""

    windows: list[Interval] = []
    window_seconds = max(0.5, float(window_seconds))
    min_window_seconds = max(0.1, float(min_window_seconds))
    for interval in active_intervals:
        cursor = float(interval.start)
        while cursor < interval.end:
            end = min(float(interval.end), cursor + window_seconds)
            if end - cursor >= min_window_seconds:
                windows.append(Interval(cursor, end, interval.confidence))
            cursor = end
    return windows


def embed_speechbrain_windows(
    classifier: Any,
    torch: Any,
    audio_path: Path,
    windows: list[Interval],
    *,
    options: ProcurementBetaOptions | None = None,
    output_path: Path | None = None,
    stage: str = "voice embedding",
) -> list[list[float]]:
    """Extract one ECAPA embedding per audio window."""

    embeddings: list[list[float]] = []
    total = len(windows)
    for index, window in enumerate(windows, start=1):
        try:
            waveform = load_wav_window_tensor(torch, audio_path, window.start, window.duration)
            inference_mode = getattr(torch, "inference_mode", None)
            context = inference_mode() if callable(inference_mode) else contextlib.nullcontext()
            with SPEECHBRAIN_INFERENCE_LOCK:
                with context:
                    embedding = classifier.encode_batch(waveform).detach().cpu().flatten().tolist()
            del waveform
            embeddings.append([float(value) for value in embedding])
        except Exception:
            embeddings.append([])
        if options is not None and output_path is not None and index % ACTIVE_THROTTLE_AUDIO_WINDOW_INTERVAL == 0:
            throttle_active_detector_work(options, output_path, f"{stage} {index}/{total}")
        if index % 100 == 0 or index == total:
            print(f"Voice analysis: embedded {index}/{total} speaker windows.", flush=True)
    return embeddings


def load_wav_window_tensor(torch: Any, audio_path: Path, start_seconds: float, duration_seconds: float) -> Any:
    """Load a PCM WAV window without torchaudio/TorchCodec runtime coupling."""

    with wave.open(str(audio_path), "rb") as handle:
        sample_rate = int(handle.getframerate())
        channels = int(handle.getnchannels())
        sample_width = int(handle.getsampwidth())
        if sample_width != 2:
            raise ValueError(f"Expected 16-bit PCM WAV, got sample width {sample_width}.")
        frame_offset = max(0, int(round(float(start_seconds) * sample_rate)))
        frame_count = max(1, int(round(float(duration_seconds) * sample_rate)))
        frame_offset = min(frame_offset, max(0, handle.getnframes() - 1))
        handle.setpos(frame_offset)
        raw = handle.readframes(frame_count)

    values = array.array("h")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    if channels > 1:
        mono: list[float] = []
        for index in range(0, len(values), channels):
            mono.append(sum(values[index : index + channels]) / float(channels))
    else:
        mono = [float(value) for value in values]
    if not mono:
        raise ValueError("No audio samples in requested window.")
    normalized = [max(-1.0, min(1.0, value / 32768.0)) for value in mono]
    return torch.tensor(normalized, dtype=torch.float32).unsqueeze(0)


def dominant_embedding_intervals(
    windows: list[Interval],
    embeddings: list[list[float]],
    *,
    confidence: float,
    similarity_threshold: float,
    dominance_ratio: float,
) -> list[Interval]:
    """Return windows belonging to the dominant speaker embedding cluster."""

    pairs = [(window, embedding) for window, embedding in zip(windows, embeddings) if embedding]
    if not pairs:
        return []

    assignments = assign_identity_clusters([embedding for _window, embedding in pairs], similarity_threshold=similarity_threshold)
    cluster_durations: dict[int, float] = {}
    for (window, _embedding), cluster_id in zip(pairs, assignments):
        cluster_durations[cluster_id] = cluster_durations.get(cluster_id, 0.0) + window.duration
    if not cluster_durations:
        return []

    total_duration = sum(cluster_durations.values())
    dominant_cluster = max(cluster_durations, key=cluster_durations.get)
    if total_duration <= 0 or cluster_durations[dominant_cluster] / total_duration < dominance_ratio:
        return []

    selected = [
        Interval(window.start, window.end, max(0.0, min(1.0, confidence)))
        for (window, _embedding), cluster_id in zip(pairs, assignments)
        if cluster_id == dominant_cluster
    ]
    return merge_nearby_intervals(selected, gap_seconds=0.1)


def optional_import(module_name: str) -> Any | None:
    try:
        module = __import__(module_name)
        for part in module_name.split(".")[1:]:
            module = getattr(module, part)
        return module
    except Exception:
        return None



def prepare_insightface_app(insightface_module: Any, *, det_size: tuple[int, int] = (320, 320)) -> Any:
    """Reject the unverified Buffalo-L pack until immutable file digests exist."""

    del insightface_module, det_size
    raise RuntimeError(
        "InsightFace Buffalo-L is disabled for this release because its automatically "
        "downloaded model pack has no authoritative digest allowlist."
    )


def scan_insightface_reference_candidates(
    cv2: Any,
    app: Any,
    video_path: Path,
    output_dir: Path,
    duration: float,
    options: ProcurementBetaOptions,
) -> list[FrameCandidate]:
    """Sample the opening window like the older reference-photo extractor."""

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return []
    reference_duration = min(max(0.0, float(duration)), INSIGHTFACE_REFERENCE_WINDOW_SECONDS)
    candidates: list[FrameCandidate] = []
    try:
        for sample_index, (timestamp, frame) in enumerate(
            iter_sampled_video_frames(
                cv2,
                capture,
                duration=reference_duration,
                sample_step=INSIGHTFACE_REFERENCE_SAMPLE_STEP_SECONDS,
            ),
            start=1,
        ):
            sample = analyze_insightface_frame(cv2, app, frame, timestamp)
            if is_insightface_reference_candidate(sample.candidate):
                candidates.append(sample.candidate)
            if sample_index % ACTIVE_THROTTLE_FRAME_INTERVAL == 0:
                throttle_active_detector_work(options, output_dir, f"InsightFace reference scan at {timestamp:.1f}s")
            if sample_index % 50 == 0:
                print(f"Face reference scan: {timestamp:.1f}s analysed with InsightFace.", flush=True)
    finally:
        capture.release()
    return candidates


def analyze_with_insightface(
    cv2: Any,
    insightface_module: Any | None,
    video_path: Path,
    output_dir: Path,
    duration: float,
    options: ProcurementBetaOptions,
) -> DetectionResult | None:
    """Use the older InsightFace largest-face identity approach as the primary face track."""

    if insightface_module is None:
        return None
    try:
        app = prepare_insightface_app(insightface_module)
    except Exception as exc:
        return DetectionResult(
            [],
            "insightface_unavailable",
            [],
            [f"InsightFace Buffalo-L could not be initialized, so face analysis fell back if possible: {exc}"],
        )

    external_reference_embedding = load_external_reference_embedding(options.face_reference_dir)
    reference_scan_candidates = []
    if not external_reference_embedding:
        reference_scan_candidates = scan_insightface_reference_candidates(
            cv2,
            app,
            video_path,
            output_dir,
            duration,
            options,
        )

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return DetectionResult([], "insightface_buffalo_l_identity", [], [f"Could not open video: {video_path}"])

    sample_step = max(INSIGHTFACE_MIN_SAMPLE_STEP_SECONDS, 1.0 / max(0.1, options.scan_fps))
    samples: list[FaceSample] = []
    candidates: list[FrameCandidate] = []
    visibility_candidates: list[FrameCandidate] = []
    try:
        for sample_index, (timestamp, frame) in enumerate(
            iter_sampled_video_frames(cv2, capture, duration=duration, sample_step=sample_step),
            start=1,
        ):
            sample = analyze_insightface_frame(cv2, app, frame, timestamp)
            samples.append(sample)
            if is_insightface_visibility_candidate(sample.candidate):
                visibility_candidates.append(sample.candidate)
            if is_insightface_reference_candidate(sample.candidate):
                candidates.append(sample.candidate)
            if sample_index % ACTIVE_THROTTLE_FRAME_INTERVAL == 0:
                throttle_active_detector_work(options, output_dir, f"InsightFace face scan at {timestamp:.1f}s")
            if sample_index % INSIGHTFACE_PROGRESS_SAMPLE_INTERVAL == 0:
                print(f"Face scan: {timestamp:.1f}s analysed with InsightFace.", flush=True)
    finally:
        capture.release()

    if external_reference_embedding:
        reference_embedding = external_reference_embedding
        main_candidates = select_insightface_candidates_matching_embedding(
            visibility_candidates,
            reference_embedding,
            similarity_threshold=INSIGHTFACE_IDENTITY_ON_THRESHOLD,
        )
    else:
        reference_candidates = select_insightface_reference_candidates(
            reference_scan_candidates,
            visibility_candidates if visibility_candidates else candidates,
            similarity_threshold=INSIGHTFACE_IDENTITY_ON_THRESHOLD,
        )
        reference_embedding = face_embedding_centroid(reference_candidates)
        main_candidates = select_insightface_candidates_matching_reference(
            visibility_candidates + reference_candidates,
            reference_candidates,
            similarity_threshold=INSIGHTFACE_IDENTITY_ON_THRESHOLD,
        )
    intervals = build_insightface_subject_visibility_intervals(
        samples,
        reference_embedding,
        sample_step=sample_step,
        duration=duration,
        confidence=max(0.68, float(options.face_confidence)),
        identity_on_threshold=INSIGHTFACE_IDENTITY_ON_THRESHOLD,
        identity_off_threshold=INSIGHTFACE_IDENTITY_OFF_THRESHOLD,
        merge_gap_seconds=insightface_interval_gap(sample_step),
    )
    artifacts = save_best_insightface_stills(cv2, main_candidates, output_dir, options.identity_stills)
    reference_path = save_reference_embedding(output_dir, reference_embedding)
    if reference_path is not None:
        artifacts.append(reference_path)

    warnings = [
        insightface_reference_source_warning(external_reference_embedding),
        f"InsightFace reference candidates: {len(reference_scan_candidates)}; visible candidates: {len(visibility_candidates)}; strict still candidates: {len(candidates)}; main-person candidates: {len(main_candidates)}.",
    ]
    if insightface_intervals_under_recovered(intervals, duration):
        warnings.append("Identity-matched visibility is short for this video; unmatched large faces were not accepted as a fallback.")
    return DetectionResult(intervals, "insightface_buffalo_l_identity", artifacts, warnings)


def validate_insightface_segments(
    cv2: Any,
    insightface_module: Any | None,
    video_path: Path,
    output_dir: Path,
    candidate_intervals: list[Interval],
    duration: float,
    options: ProcurementBetaOptions,
) -> DetectionResult | None:
    """Validate candidate clean clips with the same InsightFace reference embedding."""

    if insightface_module is None:
        return None
    reference_embedding = load_reference_embedding(output_dir / "identity_stills")
    if not reference_embedding:
        return None
    try:
        app = prepare_insightface_app(insightface_module)
    except Exception:
        return None

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return DetectionResult(
            candidate_intervals,
            "insightface_segment_validation_unavailable",
            [],
            [f"Could not open video for InsightFace segment validation: {video_path}"],
        )

    sample_step = max(INSIGHTFACE_MIN_VALIDATION_STEP_SECONDS, 1.0 / max(0.1, float(options.validation_fps)))
    samples: list[FaceSample] = []
    try:
        for sample_index, (timestamp, frame) in enumerate(
            iter_interval_sampled_video_frames(cv2, capture, candidate_intervals, duration=duration, sample_step=sample_step),
            start=1,
        ):
            samples.append(analyze_insightface_frame(cv2, app, frame, timestamp))
            if sample_index % ACTIVE_THROTTLE_FRAME_INTERVAL == 0:
                throttle_active_detector_work(options, output_dir, f"InsightFace face validation frame {sample_index}")
            if sample_index % INSIGHTFACE_PROGRESS_SAMPLE_INTERVAL == 0:
                print(f"Face validation: {sample_index} candidate frames checked with InsightFace.", flush=True)
    finally:
        capture.release()

    refined = build_insightface_subject_visibility_intervals(
        samples,
        reference_embedding,
        sample_step=sample_step,
        duration=duration,
        confidence=max(0.68, float(options.face_confidence)),
        identity_on_threshold=INSIGHTFACE_IDENTITY_ON_THRESHOLD,
        identity_off_threshold=INSIGHTFACE_IDENTITY_OFF_THRESHOLD,
        merge_gap_seconds=insightface_interval_gap(sample_step),
    )

    validated_intervals = intersect_intervals(refined, candidate_intervals)
    summary_path = write_face_validation_summary(
        output_dir,
        candidate_intervals=candidate_intervals,
        validated_intervals=validated_intervals,
        sample_count=len(samples),
        validation_fps=float(options.validation_fps),
    )
    return DetectionResult(
        validated_intervals,
        "insightface_candidate_segment_validation",
        [summary_path],
        [f"Validated {len(candidate_intervals)} candidate clean face intervals with InsightFace at {options.validation_fps:g} FPS before stitching."],
    )


def analyze_insightface_frame(cv2: Any, app: Any, frame: Any, timestamp: float) -> FaceSample:
    """Return the largest clear InsightFace face in a sampled frame."""

    try:
        faces = list(app.get(frame) or [])
    except Exception:
        faces = []
    dark_ratio = dark_background_ratio(cv2, frame)
    face_count = len(faces)
    candidate = largest_insightface_candidate(cv2, frame, faces, timestamp, dark_ratio=dark_ratio)
    return FaceSample(
        timestamp=timestamp,
        candidate=candidate,
        face_count=face_count,
        dark_ratio=dark_ratio,
        audience_like=is_audience_like_frame(face_count, dark_ratio),
        stage_context=is_stage_context_frame(face_count, dark_ratio),
    )


def largest_insightface_candidate(
    cv2: Any,
    frame: Any,
    faces: list[Any],
    timestamp: float,
    *,
    dark_ratio: float,
) -> FrameCandidate | None:
    """Mirror the older tool: choose the largest sufficiently clear detected face."""

    if not faces:
        return None
    height, width = frame.shape[:2]
    face = max(faces, key=insightface_bbox_area)
    x1, y1, x2, y2 = [int(round(float(value))) for value in face.bbox]
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    face_width = x2 - x1
    face_height = y2 - y1
    if min(face_width, face_height) < INSIGHTFACE_MIN_VISIBILITY_FACE_PX:
        return None

    geometry = face_box_quality((x1, y1, face_width, face_height), width, height)
    if float(geometry.get("area", 0.0)) < INSIGHTFACE_MIN_VISIBILITY_FACE_AREA:
        return None
    crop = padded_crop(frame, x1, y1, face_width, face_height, padding_ratio=0.15)
    embedding = normalised_embedding(face.embedding)
    if not embedding:
        return None
    confidence = float(getattr(face, "det_score", 1.0) or 1.0)
    return FrameCandidate(
        timestamp=timestamp,
        confidence=max(0.0, min(1.0, confidence)),
        area=float(geometry["area"]),
        blur_score=blur_score(cv2, crop),
        frame=None,
        embedding=embedding,
        face_count=len(faces),
        dark_ratio=dark_ratio,
        crop=crop.copy(),
        center_score=float(geometry["center_score"]),
        face_width_px=face_width,
        face_height_px=face_height,
    )


def insightface_bbox_area(face: Any) -> float:
    x1, y1, x2, y2 = [float(value) for value in face.bbox]
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def is_insightface_reference_candidate(candidate: FrameCandidate | None) -> bool:
    """Quality gate for the older largest-face identity reference pool."""

    if candidate is None or not candidate.embedding:
        return False
    if candidate.area < MIN_CLEAR_FACE_AREA:
        return False
    if min(candidate.face_width_px, candidate.face_height_px) < INSIGHTFACE_MIN_FACE_PX:
        return False
    if candidate.blur_score < MIN_CLEAR_FACE_BLUR_SCORE:
        return False
    return True


def is_insightface_visibility_candidate(candidate: FrameCandidate | None) -> bool:
    """Return true for identity tracking, even when the face is too small for a still."""

    if candidate is None or not candidate.embedding:
        return False
    if candidate.area < INSIGHTFACE_MIN_VISIBILITY_FACE_AREA:
        return False
    if min(candidate.face_width_px, candidate.face_height_px) < INSIGHTFACE_MIN_VISIBILITY_FACE_PX:
        return False
    return True


def select_insightface_reference_candidates(
    opening_candidates: list[FrameCandidate],
    full_candidates: list[FrameCandidate],
    *,
    similarity_threshold: float,
) -> list[FrameCandidate]:
    """Choose the identity that best explains the video, not just the opening."""

    full_visibility = [candidate for candidate in full_candidates if is_insightface_visibility_candidate(candidate)]
    opening_reference = select_main_insightface_candidates(
        opening_candidates,
        similarity_threshold=similarity_threshold,
    )
    opening_matches = select_insightface_candidates_matching_reference(
        full_visibility,
        opening_reference,
        similarity_threshold=similarity_threshold,
    )
    if not full_visibility:
        return opening_matches

    minimum_recovery_count = max(
        3,
        min(MIN_RELAXED_IDENTITY_CLUSTER_CANDIDATES, int(round(len(full_visibility) * 0.05))),
    )
    if len(opening_matches) >= minimum_recovery_count:
        return opening_matches

    sampled = sample_identity_baseline_candidates(
        full_visibility,
        max_count=MAX_IDENTITY_BASELINE_CLUSTER_CANDIDATES,
    )
    dominant = dominant_cluster_candidates(sampled, similarity_threshold=similarity_threshold)
    dominant_matches = select_insightface_candidates_matching_reference(
        full_visibility,
        dominant,
        similarity_threshold=similarity_threshold,
    )
    if len(dominant_matches) >= minimum_recovery_count and len(dominant_matches) > len(opening_matches):
        return dominant_matches
    return opening_matches


def select_main_insightface_candidates(candidates: list[FrameCandidate], *, similarity_threshold: float) -> list[FrameCandidate]:
    """Cull largest-face candidates using the old early reference-window bootstrap."""

    valid = [candidate for candidate in candidates if is_insightface_reference_candidate(candidate)]
    if not valid:
        return []
    early_reference = [candidate for candidate in valid if candidate.timestamp <= INSIGHTFACE_REFERENCE_WINDOW_SECONDS]
    reference_pool = early_reference if len(early_reference) >= 2 else valid
    sampled = sample_identity_baseline_candidates(reference_pool, max_count=MAX_IDENTITY_BASELINE_CLUSTER_CANDIDATES)
    dominant = dominant_cluster_candidates(sampled, similarity_threshold=similarity_threshold)
    if not dominant:
        return []
    return select_insightface_candidates_matching_reference(
        valid,
        dominant,
        similarity_threshold=similarity_threshold,
    )


def select_insightface_candidates_matching_reference(
    candidates: list[FrameCandidate],
    reference_candidates: list[FrameCandidate],
    *,
    similarity_threshold: float,
) -> list[FrameCandidate]:
    """Keep only candidates matching the culled InsightFace reference identity."""

    reference_embedding = face_embedding_centroid(reference_candidates)
    if not reference_embedding:
        return []
    return select_insightface_candidates_matching_embedding(
        candidates,
        reference_embedding,
        similarity_threshold=similarity_threshold,
    )


def select_insightface_candidates_matching_embedding(
    candidates: list[FrameCandidate],
    reference_embedding: list[float],
    *,
    similarity_threshold: float,
) -> list[FrameCandidate]:
    """Keep only candidates matching a supplied face-reference embedding."""

    if not reference_embedding:
        return []
    selected: list[FrameCandidate] = []
    seen_timestamps: set[float] = set()
    for candidate in sorted(candidates, key=lambda item: item.timestamp):
        if not is_insightface_visibility_candidate(candidate):
            continue
        similarity = face_candidate_similarity(candidate, reference_embedding)
        if similarity is None or similarity < similarity_threshold:
            continue
        if candidate.timestamp in seen_timestamps:
            continue
        selected.append(candidate)
        seen_timestamps.add(candidate.timestamp)
    return selected


def build_insightface_subject_visibility_intervals(
    samples: list[FaceSample],
    reference_embedding: list[float],
    *,
    sample_step: float,
    duration: float,
    confidence: float,
    identity_on_threshold: float,
    identity_off_threshold: float,
    merge_gap_seconds: float | None = None,
) -> list[Interval]:
    """Label target visibility using InsightFace identity, not crowd-count heuristics."""

    if not reference_embedding:
        return []

    active = False
    pending_hits = 0
    min_run_samples = max(1, int(round(0.5 / max(sample_step, 0.001))))
    accepted: list[tuple[float, float]] = []

    for sample in sorted(samples, key=lambda item: item.timestamp):
        if not is_insightface_visibility_candidate(sample.candidate):
            active = False
            pending_hits = 0
            continue

        similarity = face_candidate_similarity(sample.candidate, reference_embedding)
        if similarity is not None:
            threshold = identity_off_threshold if active else identity_on_threshold
            if similarity >= threshold:
                pending_hits += 1
                if active or pending_hits >= min_run_samples:
                    active = True
                    accepted.append((sample.timestamp, sample.candidate.confidence if sample.candidate else confidence))
                continue

        active = False
        pending_hits = 0

    return intervals_from_weighted_sample_times(
        accepted,
        sample_step=sample_step,
        duration=duration,
        gap_seconds=strict_face_interval_gap(sample_step) if merge_gap_seconds is None else merge_gap_seconds,
    )



def insightface_interval_gap(sample_step: float) -> float:
    """Bridge one missed InsightFace sample when scanning sparsely on CPU."""

    return max(first_pass_face_interval_gap(sample_step), max(0.0, float(sample_step)) * 1.5)


def sum_interval_seconds(intervals: list[Interval]) -> float:
    return sum(interval.duration for interval in intervals)


def insightface_intervals_under_recovered(intervals: list[Interval], duration: float) -> bool:
    """Detect when strict identity matching found too little to trust on a long video."""

    total = sum_interval_seconds(intervals)
    expected = min(INSIGHTFACE_MIN_EXPECTED_IDENTITY_SECONDS, max(0.0, float(duration)) * 0.05)
    return total < max(10.0, expected)


def build_insightface_presence_intervals(
    samples: list[FaceSample],
    *,
    sample_step: float,
    duration: float,
    merge_gap_seconds: float,
) -> list[Interval]:
    """Build visibility intervals from largest-face presence when identity under-recovers."""

    accepted = [
        (sample.timestamp, sample.candidate.confidence)
        for sample in sorted(samples, key=lambda item: item.timestamp)
        if is_insightface_visibility_candidate(sample.candidate)
    ]
    return intervals_from_weighted_sample_times(
        accepted,
        sample_step=sample_step,
        duration=duration,
        gap_seconds=merge_gap_seconds,
    )

def save_best_insightface_stills(cv2: Any, candidates: list[FrameCandidate], output_dir: Path, count: int) -> list[Path]:
    """Save reference-quality InsightFace stills for the culled main identity."""

    selected = select_insightface_still_export_candidates(candidates, count)
    artifacts: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, candidate in enumerate(selected, start=1):
        path = output_dir / f"still_{index:03d}_{candidate.timestamp:.2f}s.jpg"
        image = candidate.crop if candidate.crop is not None else candidate.frame
        if write_jpeg(cv2, path, image):
            artifacts.append(path)
    return artifacts


def select_insightface_still_export_candidates(candidates: list[FrameCandidate], count: int) -> list[FrameCandidate]:
    """Prefer reference-quality stills, then fill from smaller verified identity crops."""

    if count <= 0:
        return []
    reference_quality = [candidate for candidate in candidates if is_insightface_reference_candidate(candidate)]
    if len(reference_quality) >= count:
        return select_diverse_insightface_still_candidates(reference_quality, count)
    reference_ids = {id(candidate) for candidate in reference_quality}
    visibility_quality = [
        candidate
        for candidate in candidates
        if id(candidate) not in reference_ids and is_insightface_visibility_candidate(candidate)
    ]
    return select_diverse_insightface_still_candidates(reference_quality + visibility_quality, count)


def select_diverse_insightface_still_candidates(candidates: list[FrameCandidate], count: int) -> list[FrameCandidate]:
    """Time-spread still picker for InsightFace candidates without the old face-count cap."""

    usable = [candidate for candidate in candidates if is_insightface_visibility_candidate(candidate)]
    if count <= 0 or not usable:
        return []
    ranked = sorted(usable, key=still_quality_score, reverse=True)
    if len(ranked) <= count:
        return sorted(ranked, key=lambda item: item.timestamp)
    start_time = min(candidate.timestamp for candidate in ranked)
    end_time = max(candidate.timestamp for candidate in ranked)
    span = max(1.0, end_time - start_time)
    buckets: list[list[FrameCandidate]] = [[] for _ in range(max(1, count))]
    for candidate in ranked:
        bucket_index = min(len(buckets) - 1, int(((candidate.timestamp - start_time) / span) * len(buckets)))
        buckets[bucket_index].append(candidate)
    selected = [max(bucket, key=still_quality_score) for bucket in buckets if bucket]
    selected_ids = {id(candidate) for candidate in selected}
    for candidate in ranked:
        if len(selected) >= count:
            break
        if id(candidate) in selected_ids:
            continue
        selected.append(candidate)
        selected_ids.add(id(candidate))
    return sorted(selected[:count], key=lambda item: item.timestamp)

def analyze_with_opencv_zoo(
    cv2: Any,
    video_path: Path,
    output_dir: Path,
    duration: float,
    options: ProcurementBetaOptions,
) -> DetectionResult | None:
    """Use OpenCV Zoo YuNet/SFace for identity-first face visibility."""

    if not has_opencv_zoo_face_api(cv2):
        return None
    model_paths = ensure_opencv_zoo_models()
    if model_paths is None:
        return None

    try:
        detector = cv2.FaceDetectorYN_create(
            str(model_paths["yunet"]),
            "",
            (320, 320),
            float(options.face_confidence),
            0.3,
            5000,
        )
        recognizer = cv2.FaceRecognizerSF_create(str(model_paths["sface"]), "")
    except Exception:
        return None

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return DetectionResult([], "opencv_zoo_yunet_sface_identity", [], [f"Could not open video: {video_path}"])

    sample_step = max(0.5, 1.0 / max(0.1, options.scan_fps))
    samples: list[FaceSample] = []
    candidates: list[FrameCandidate] = []
    try:
        for sample_index, (timestamp, frame) in enumerate(
            iter_sampled_video_frames(cv2, capture, duration=duration, sample_step=sample_step),
            start=1,
        ):
            sample = analyze_opencv_zoo_frame(cv2, detector, recognizer, frame, timestamp, options)
            samples.append(sample)
            if is_identity_baseline_candidate(sample.candidate) and not sample.audience_like:
                candidates.append(sample.candidate)
            if sample_index % ACTIVE_THROTTLE_FRAME_INTERVAL == 0:
                throttle_active_detector_work(options, output_dir, f"face scan at {timestamp:.1f}s")
            if sample_index % 500 == 0:
                print(f"Face scan: {timestamp:.1f}s analysed with OpenCV Zoo.", flush=True)
    finally:
        capture.release()

    main_candidates = select_main_face_candidates(candidates, similarity_threshold=OPENCV_ZOO_IDENTITY_ON_THRESHOLD)
    reference_embedding = face_embedding_centroid(main_candidates)
    intervals = build_subject_visibility_intervals(
        samples,
        reference_embedding,
        sample_step=sample_step,
        duration=duration,
        confidence=max(0.68, float(options.face_confidence)),
        identity_on_threshold=OPENCV_ZOO_IDENTITY_ON_THRESHOLD,
        identity_off_threshold=OPENCV_ZOO_IDENTITY_OFF_THRESHOLD,
        merge_gap_seconds=first_pass_face_interval_gap(sample_step),
    )
    artifacts = save_best_stills(cv2, main_candidates, output_dir, options.identity_stills)
    reference_path = save_reference_embedding(output_dir, reference_embedding)
    if reference_path is not None:
        artifacts.append(reference_path)

    return DetectionResult(
        intervals,
        "opencv_zoo_yunet_sface_identity",
        artifacts,
        ["Used OpenCV Zoo YuNet/SFace identity matching with audience-cutaway rejection."],
    )


def throttle_active_detector_work(options: ProcurementBetaOptions, output_path: Path, stage: str) -> None:
    """Pause inside long detector loops instead of waiting only between stages."""

    pause_if_resource_pressure(
        min_free_percent=options.resource_guard_percent,
        output_path=output_path,
        poll_seconds=options.resource_poll_seconds,
        timeout_seconds=options.resource_guard_timeout_seconds,
        logger=lambda message: print(message, flush=True),
        stage=stage,
    )


def has_opencv_zoo_face_api(cv2: Any) -> bool:
    """Return true when this OpenCV build supports YuNet and SFace."""

    return hasattr(cv2, "FaceDetectorYN_create") and hasattr(cv2, "FaceRecognizerSF_create")


def validate_opencv_zoo_segments(
    cv2: Any,
    video_path: Path,
    output_dir: Path,
    candidate_intervals: list[Interval],
    duration: float,
    options: ProcurementBetaOptions,
) -> DetectionResult | None:
    """Re-scan candidate clean clips before stitching them into the output."""

    if not has_opencv_zoo_face_api(cv2):
        return None
    reference_embedding = load_reference_embedding(output_dir / "identity_stills")
    if not reference_embedding:
        return DetectionResult(
            candidate_intervals,
            "face_segment_validation_skipped",
            [],
            ["No saved face reference embedding was available; candidate face intervals were left unchanged."],
        )

    model_paths = ensure_opencv_zoo_models()
    if model_paths is None:
        return None

    try:
        detector = cv2.FaceDetectorYN_create(
            str(model_paths["yunet"]),
            "",
            (320, 320),
            float(options.face_confidence),
            0.3,
            5000,
        )
        recognizer = cv2.FaceRecognizerSF_create(str(model_paths["sface"]), "")
    except Exception:
        return None

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return DetectionResult(
            candidate_intervals,
            "face_segment_validation_unavailable",
            [],
            [f"Could not open video for segment validation: {video_path}"],
        )

    sample_step = 1.0 / max(0.1, float(options.validation_fps))
    samples: list[FaceSample] = []
    try:
        for sample_index, (timestamp, frame) in enumerate(
            iter_interval_sampled_video_frames(cv2, capture, candidate_intervals, duration=duration, sample_step=sample_step),
            start=1,
        ):
            samples.append(analyze_opencv_zoo_frame(cv2, detector, recognizer, frame, timestamp, options))
            if sample_index % ACTIVE_THROTTLE_FRAME_INTERVAL == 0:
                throttle_active_detector_work(options, output_dir, f"face validation frame {sample_index}")
            if sample_index % 500 == 0:
                print(f"Face validation: {sample_index} candidate frames checked.", flush=True)
    finally:
        capture.release()

    validated_intervals = build_validated_subject_visibility_intervals(
        samples,
        reference_embedding,
        candidate_intervals,
        sample_step=sample_step,
        duration=duration,
        confidence=max(0.68, float(options.face_confidence)),
        identity_on_threshold=OPENCV_ZOO_IDENTITY_ON_THRESHOLD,
        identity_off_threshold=OPENCV_ZOO_IDENTITY_OFF_THRESHOLD,
        merge_gap_seconds=validation_face_interval_gap(sample_step),
    )
    summary_path = write_face_validation_summary(
        output_dir,
        candidate_intervals=candidate_intervals,
        validated_intervals=validated_intervals,
        sample_count=len(samples),
        validation_fps=float(options.validation_fps),
    )
    return DetectionResult(
        validated_intervals,
        "opencv_zoo_candidate_segment_validation",
        [summary_path],
        [f"Validated {len(candidate_intervals)} candidate clean face intervals at {options.validation_fps:g} FPS before stitching."],
    )


def validate_opencv_zoo_stitched_output(
    cv2: Any,
    video_path: Path,
    output_dir: Path,
    duration: float,
    options: ProcurementBetaOptions,
) -> dict[str, Any] | None:
    """Sample the stitched output and flag frames that are not the main speaker."""

    if not has_opencv_zoo_face_api(cv2):
        return None
    reference_embedding = load_reference_embedding(output_dir / "identity_stills")
    if not reference_embedding:
        return write_stitched_output_validation(
            output_dir,
            {
                "available": False,
                "duration_seconds": duration,
                "failure_count": 1,
                "failures": [{"reason": "No saved face reference embedding was available for final stitched-output validation."}],
            },
        )

    model_paths = ensure_opencv_zoo_models()
    if model_paths is None:
        return None

    try:
        detector = cv2.FaceDetectorYN_create(
            str(model_paths["yunet"]),
            "",
            (320, 320),
            float(options.face_confidence),
            0.3,
            5000,
        )
        recognizer = cv2.FaceRecognizerSF_create(str(model_paths["sface"]), "")
    except Exception:
        return None

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return write_stitched_output_validation(
            output_dir,
            {
                "available": False,
                "duration_seconds": duration,
                "failure_count": 1,
                "failures": [{"reason": f"Could not open stitched video for final validation: {video_path}"}],
            },
        )

    checked_count = 0
    sample_step = 1.0 / FINAL_STITCHED_VALIDATION_FPS
    records: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    try:
        for sample_index, (timestamp, frame) in enumerate(
            iter_sampled_video_frames(cv2, capture, duration=duration, sample_step=sample_step),
            start=1,
        ):
            checked_count = sample_index
            sample = analyze_opencv_zoo_frame(cv2, detector, recognizer, frame, timestamp, options)
            similarity = face_candidate_similarity(sample.candidate, reference_embedding)
            failure_reasons = stitched_sample_failure_reasons(sample, similarity)
            record = {
                "timestamp": round(float(timestamp), 3),
                "face_count": int(sample.face_count),
                "similarity": round(float(similarity), 4) if similarity is not None else None,
                "audience_like": bool(sample.audience_like),
                "accepted": not failure_reasons,
                "reasons": failure_reasons,
            }
            if options.keep_debug or failure_reasons:
                records.append(record)
            if failure_reasons:
                failures.append(record)
            if sample_index % ACTIVE_THROTTLE_FRAME_INTERVAL == 0:
                throttle_active_detector_work(options, output_dir, f"stitched output validation frame {sample_index}")
            if sample_index % 500 == 0:
                print(f"Final stitched validation: {sample_index} output frames checked.", flush=True)
    finally:
        capture.release()

    if checked_count == 0:
        return write_stitched_output_validation(
            output_dir,
            {
                "available": False,
                "duration_seconds": float(duration),
                "validation_fps": FINAL_STITCHED_VALIDATION_FPS,
                "identity_threshold": FINAL_STITCHED_IDENTITY_THRESHOLD,
                "sample_count": 0,
                "failure_count": 1,
                "failure_timestamps": [],
                "failures": [{"reason": "No frames were sampled from the stitched output for final validation."}],
                "records": records,
            },
        )

    payload = {
        "available": True,
        "duration_seconds": float(duration),
        "validation_fps": FINAL_STITCHED_VALIDATION_FPS,
        "identity_threshold": FINAL_STITCHED_IDENTITY_THRESHOLD,
        "sample_count": checked_count,
        "failure_count": len(failures),
        "failure_timestamps": [item["timestamp"] for item in failures if "timestamp" in item],
        "failures": failures[:100],
        "records": records,
    }
    return write_stitched_output_validation(output_dir, payload)


def stitched_sample_failure_reasons(sample: FaceSample, similarity: float | None) -> list[str]:
    """Explain why one stitched-output sample is not safe to call clean."""

    reasons: list[str] = []
    if sample.face_count != 1:
        reasons.append(f"expected exactly one face, found {sample.face_count}")
    if sample.audience_like:
        reasons.append("frame looks like an audience or cutaway shot")
    if not is_output_visibility_candidate(sample.candidate):
        reasons.append("main face is not prominent/clear enough")
    if similarity is None:
        reasons.append("no identity similarity could be computed")
    elif similarity < FINAL_STITCHED_IDENTITY_THRESHOLD:
        reasons.append(f"identity similarity {similarity:.3f} below {FINAL_STITCHED_IDENTITY_THRESHOLD:.2f}")
    return reasons


def write_stitched_output_validation(output_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist final stitched-output QA and return the manifest payload."""

    path = output_dir / "stitched_identity_validation.json"
    payload = dict(payload)
    payload["artifact"] = str(path)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload

def build_validated_subject_visibility_intervals(
    samples: list[FaceSample],
    reference_embedding: list[float],
    source_intervals: list[Interval],
    *,
    sample_step: float,
    duration: float,
    confidence: float,
    identity_on_threshold: float,
    identity_off_threshold: float,
    merge_gap_seconds: float | None = None,
) -> list[Interval]:
    """Build refined intervals and cap them to the original candidate spans."""

    refined = build_subject_visibility_intervals(
        samples,
        reference_embedding,
        sample_step=sample_step,
        duration=duration,
        confidence=confidence,
        identity_on_threshold=identity_on_threshold,
        identity_off_threshold=identity_off_threshold,
        merge_gap_seconds=merge_gap_seconds,
    )
    return intersect_intervals(refined, source_intervals)


def save_reference_embedding(output_dir: Path, embedding: list[float]) -> Path | None:
    """Persist the culled main-person embedding for the segment validator."""

    if not embedding:
        return None
    path = output_dir / REFERENCE_EMBEDDING_FILENAME
    path.write_text(json.dumps({"embedding": embedding}, indent=2) + "\n", encoding="utf-8")
    return path


def load_reference_embedding(output_dir: Path) -> list[float]:
    """Load the main-person embedding written during the first face scan."""

    return load_reference_embedding_file(output_dir / REFERENCE_EMBEDDING_FILENAME)


def load_external_reference_embedding(reference_dir: Path | str) -> list[float]:
    """Load a user-curated reference embedding from a speaker profile folder."""

    if not reference_dir:
        return []
    return load_reference_embedding_file(Path(reference_dir) / REFERENCE_EMBEDDING_FILENAME)


def load_reference_embedding_file(path: Path) -> list[float]:
    """Read and validate a reference embedding JSON payload."""

    try:
        payload = read_control_json(
            path,
            label="face reference",
            max_bytes=MAX_FACE_REFERENCE_JSON_BYTES,
            max_items=MAX_FACE_REFERENCE_JSON_ITEMS,
        )
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    embedding = payload.get("embedding")
    if not isinstance(embedding, list):
        return []
    return [float(value) for value in embedding]


def insightface_reference_source_warning(external_reference_embedding: list[float]) -> str:
    """Describe whether InsightFace used a curated or auto-learned identity."""

    if external_reference_embedding:
        return "Used a supplied curated face reference embedding with the InsightFace Buffalo-L identity pipeline."
    return "Used the earlier InsightFace Buffalo-L largest-face identity pipeline with a separate opening-window reference scan."


def write_face_validation_summary(
    output_dir: Path,
    *,
    candidate_intervals: list[Interval],
    validated_intervals: list[Interval],
    sample_count: int,
    validation_fps: float,
) -> Path:
    """Write a compact audit file for the second-pass face validation."""

    path = output_dir / "face_segment_validation.json"
    payload = {
        "validation_fps": validation_fps,
        "sample_count": int(sample_count),
        "candidate_intervals": [interval_payload(interval) for interval in candidate_intervals],
        "validated_intervals": [interval_payload(interval) for interval in validated_intervals],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def interval_payload(interval: Interval) -> dict[str, float]:
    """Return a JSON-safe interval record without importing runner helpers."""

    return {
        "start": interval.start,
        "end": interval.end,
        "duration": interval.duration,
        "confidence": interval.confidence,
    }


def iter_sampled_video_frames(
    cv2: Any,
    capture: Any,
    *,
    duration: float,
    sample_step: float,
):
    """Yield sampled frames without seeking for every timestamp.

    Random timestamp seeks are the slowest part of face analysis on long
    compressed videos. When the container exposes a sane FPS value, advancing
    through the stream with ``grab`` keeps decoding sequential and only returns
    the frames that the detector actually needs. If FPS metadata is missing,
    fall back to timestamp seeks so odd files remain processable.
    """

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0.0:
        yield from iter_seek_sampled_video_frames(cv2, capture, duration=duration, sample_step=sample_step)
        return

    timestamp = 0.0
    current_frame_index = 0
    consecutive_failures = 0
    while duration <= 0 or timestamp < duration:
        target_frame_index = max(0, int(round(timestamp * fps)))
        while current_frame_index < target_frame_index:
            if not safe_capture_grab(capture):
                break
            current_frame_index += 1

        ok, frame = safe_capture_read(capture)
        if ok and frame is not None:
            current_frame_index += 1
            consecutive_failures = 0
            yield timestamp, frame
        else:
            ok, frame = read_frame_by_timestamp_seek(cv2, capture, timestamp)
            if ok and frame is not None:
                current_frame_index = target_frame_index + 1
                consecutive_failures = 0
                yield timestamp, frame
            else:
                current_frame_index = target_frame_index + 1
                consecutive_failures += 1
                if duration <= 0 and consecutive_failures >= MAX_CONSECUTIVE_DECODE_FAILURES:
                    return
        timestamp += sample_step


def iter_seek_sampled_video_frames(
    cv2: Any,
    capture: Any,
    *,
    duration: float,
    sample_step: float,
):
    """Yield sampled frames using timestamp seeks for files without FPS metadata."""

    timestamp = 0.0
    consecutive_failures = 0
    while duration <= 0 or timestamp < duration:
        ok, frame = read_frame_by_timestamp_seek(cv2, capture, timestamp)
        if ok and frame is not None:
            consecutive_failures = 0
            yield timestamp, frame
        else:
            consecutive_failures += 1
            if duration <= 0 and consecutive_failures >= MAX_CONSECUTIVE_DECODE_FAILURES:
                return
        timestamp += sample_step


def safe_capture_grab(capture: Any) -> bool:
    """Advance a VideoCapture without letting one decoder exception abort a run."""

    try:
        return bool(capture.grab())
    except Exception:
        return False


def safe_capture_read(capture: Any) -> tuple[bool, Any | None]:
    """Read one frame from a VideoCapture, converting OpenCV errors to a miss."""

    try:
        ok, frame = capture.read()
    except Exception:
        return False, None
    return bool(ok), frame


def read_frame_by_timestamp_seek(cv2: Any, capture: Any, timestamp: float) -> tuple[bool, Any | None]:
    """Read a frame by timestamp seek as a fallback for odd decode positions."""

    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(timestamp)) * 1000.0)
    except Exception:
        return False, None
    return safe_capture_read(capture)


def iter_interval_sampled_video_frames(
    cv2: Any,
    capture: Any,
    intervals: list[Interval],
    *,
    duration: float,
    sample_step: float,
):
    """Yield sampled frames from selected intervals with one seek per interval.

    The first scan walks the whole video cheaply. Validation is different: it
    only needs the clips that might be stitched, so seeking once to each segment
    and then reading sequentially is quicker than random-seeking every sample.
    """

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0.0:
        for timestamp in iter_interval_timestamps(intervals, duration=duration, sample_step=sample_step):
            ok, frame = read_frame_by_timestamp_seek(cv2, capture, timestamp)
            if ok and frame is not None:
                yield timestamp, frame
        return

    for interval in sorted(intervals):
        start = max(0.0, float(interval.start))
        end = min(float(interval.end), float(duration) if duration > 0 else float(interval.end))
        if end <= start:
            continue

        try:
            capture.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
        except Exception:
            continue

        timestamp = start
        current_frame_index = max(0, int(round(start * fps)))
        while timestamp < end:
            target_frame_index = max(0, int(round(timestamp * fps)))
            while current_frame_index < target_frame_index:
                if not safe_capture_grab(capture):
                    break
                current_frame_index += 1

            ok, frame = safe_capture_read(capture)
            if ok and frame is not None:
                current_frame_index += 1
                yield timestamp, frame
            else:
                ok, frame = read_frame_by_timestamp_seek(cv2, capture, timestamp)
                if ok and frame is not None:
                    current_frame_index = target_frame_index + 1
                    yield timestamp, frame
            timestamp += sample_step


def iter_interval_timestamps(intervals: list[Interval], *, duration: float, sample_step: float):
    """Yield validation timestamps inside intervals without crossing boundaries."""

    step = max(0.1, float(sample_step))
    for interval in sorted(intervals):
        start = max(0.0, float(interval.start))
        end = min(float(interval.end), float(duration) if duration > 0 else float(interval.end))
        timestamp = start
        while timestamp < end:
            yield timestamp
            timestamp += step


def ensure_opencv_zoo_models() -> dict[str, Path] | None:
    """Download OpenCV Zoo model files into a user-local cache when needed."""

    with OPENCV_ZOO_MODEL_LOCK:
        cache_dir = local_model_cache_dir() / "opencv_zoo"
        paths: dict[str, Path] = {}
        for key, metadata in OPENCV_ZOO_MODELS.items():
            path = cache_dir / str(metadata["filename"])
            expected_sha256 = str(metadata["sha256"])
            if not model_file_ready(path, expected_sha256):
                path.unlink(missing_ok=True)
                if not download_model_file(str(metadata["url"]), path, expected_sha256):
                    return None
            paths[key] = path
        return paths


def local_model_cache_dir() -> Path:
    """Keep model weights outside git while retaining legacy cache compatibility."""

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        preferred = Path(local_app_data) / "MultimodalEmotionAnalysisTool" / "models"
        legacy = Path(local_app_data) / "MultimodalEmotionAnalysisPipeline" / "models"
    else:
        preferred = Path.home() / ".cache" / "multimodal-emotion-analysis-tool" / "models"
        legacy = Path.home() / ".cache" / "multimodal-emotion-analysis-pipeline" / "models"
    if legacy.exists() and not preferred.exists():
        return legacy
    return preferred


def model_file_ready(path: Path, expected_sha256: str) -> bool:
    """Accept a cached model only when its complete SHA-256 matches."""

    if not path.is_file():
        return False
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected_sha256.casefold()


def download_model_file(url: str, path: Path, expected_sha256: str) -> bool:
    """Verify a sibling temporary download before atomically installing it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    path.unlink(missing_ok=True)
    temporary.unlink(missing_ok=True)
    print(f"OpenCV Zoo: downloading {path.name}...", flush=True)
    try:
        urlretrieve(url, temporary)
    except (OSError, URLError):
        temporary.unlink(missing_ok=True)
        return False
    if not model_file_ready(temporary, expected_sha256):
        temporary.unlink(missing_ok=True)
        return False
    try:
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        return False
    return model_file_ready(path, expected_sha256)


def analyze_opencv_zoo_frame(
    cv2: Any,
    detector: Any,
    recognizer: Any,
    frame: Any,
    timestamp: float,
    options: ProcurementBetaOptions,
) -> FaceSample:
    """Detect and embed the best likely speaker face in one frame."""

    detection_frame, detection_scale = resize_for_yunet_detection(cv2, frame)
    height, width = detection_frame.shape[:2]
    detector.setInputSize((width, height))
    try:
        _retval, detections = detector.detect(detection_frame)
    except Exception:
        detections = None
    faces = [] if detections is None else [scale_yunet_detection(face, detection_scale) for face in detections]
    dark_ratio = dark_background_ratio(cv2, frame)
    face_count = len(faces)
    audience_like = is_audience_like_frame(face_count, dark_ratio)
    candidate = best_opencv_zoo_candidate(cv2, recognizer, frame, faces, timestamp, options, dark_ratio=dark_ratio)
    return FaceSample(
        timestamp=timestamp,
        candidate=candidate,
        face_count=face_count,
        dark_ratio=dark_ratio,
        audience_like=audience_like,
        stage_context=is_stage_context_frame(face_count, dark_ratio),
    )


def best_opencv_zoo_candidate(
    cv2: Any,
    recognizer: Any,
    frame: Any,
    faces: list[Any],
    timestamp: float,
    options: ProcurementBetaOptions,
    *,
    dark_ratio: float,
) -> FrameCandidate | None:
    """Return the strongest central face candidate with an SFace embedding."""

    if not faces or is_audience_like_frame(len(faces), dark_ratio):
        return None
    height, width = frame.shape[:2]
    scored: list[tuple[float, Any, dict[str, float]]] = []
    for face in faces:
        x, y, box_width, box_height = yunet_box(face)
        if min(box_width, box_height) < 32:
            continue
        confidence = float(face[-1])
        if confidence < float(options.face_confidence):
            continue
        geometry = face_box_quality((x, y, box_width, box_height), width, height)
        if not basic_face_geometry_is_clear(geometry, box_width, box_height):
            continue
        scored.append(((confidence * 0.6) + geometry["score"], face, geometry))
    if not scored:
        return None

    _score, face, geometry = max(scored, key=lambda item: item[0])
    x, y, box_width, box_height = yunet_box(face)
    crop = padded_crop(frame, x, y, box_width, box_height)
    try:
        aligned = recognizer.alignCrop(frame, face)
        embedding = normalised_embedding(recognizer.feature(aligned))
    except Exception:
        embedding = []
    area = float((box_width * box_height) / max(1, width * height))
    return FrameCandidate(
        timestamp=timestamp,
        confidence=max(0.0, min(1.0, float(face[-1]))),
        area=area,
        blur_score=blur_score(cv2, crop),
        frame=None,
        embedding=embedding,
        face_count=len(faces),
        dark_ratio=dark_ratio,
        crop=crop.copy(),
        center_score=float(geometry["center_score"]),
        face_width_px=box_width,
        face_height_px=box_height,
    )


def resize_for_yunet_detection(cv2: Any, frame: Any, *, max_width: int = YUNET_DETECTOR_MAX_WIDTH) -> tuple[Any, float]:
    """Downscale large frames for faster YuNet detection and return coordinate scale.

    SFace still receives boxes and landmarks in the original frame coordinate
    space, so detection rows are scaled back before alignment.
    """

    height, width = frame.shape[:2]
    if width <= max_width:
        return frame, 1.0
    scale = width / float(max_width)
    resized_height = max(1, int(round(height / scale)))
    resized = cv2.resize(frame, (max_width, resized_height), interpolation=cv2.INTER_AREA)
    return resized, scale


def scale_yunet_detection(face: Any, scale: float) -> Any:
    """Scale a YuNet detection row from resized-frame to source-frame coordinates."""

    if float(scale) == 1.0:
        return face
    scaled = face.copy()
    scaled[:14] = scaled[:14] * float(scale)
    return scaled


def yunet_box(face: Any) -> tuple[int, int, int, int]:
    """Convert a YuNet detection row into an integer bounding box."""

    x, y, width, height = [int(round(float(value))) for value in face[:4]]
    return x, y, max(0, width), max(0, height)


def padded_crop(frame: Any, x: int, y: int, width: int, height: int, *, padding_ratio: float = 0.18) -> Any:
    """Crop a face with a little context so identity stills are human-readable."""

    frame_height, frame_width = frame.shape[:2]
    padding = int(round(max(width, height) * padding_ratio))
    left = max(0, x - padding)
    top = max(0, y - padding)
    right = min(frame_width, x + width + padding)
    bottom = min(frame_height, y + height + padding)
    return frame[top:bottom, left:right]


def normalised_embedding(feature: Any) -> list[float]:
    """Flatten and normalise a model embedding for cosine comparisons."""

    values = [float(value) for value in feature.flatten().tolist()]
    norm = sum(value * value for value in values) ** 0.5
    if norm == 0:
        return []
    return [value / norm for value in values]


def analyze_with_opencv_haar(
    cv2: Any,
    video_path: Path,
    output_dir: Path,
    duration: float,
    options: ProcurementBetaOptions,
) -> DetectionResult:
    """Fail closed instead of loading OpenCV's unverified bundled Haar cascade."""

    del cv2, video_path, output_dir, duration, options
    return DetectionResult(
        intervals=[],
        method="unavailable_face_model",
        artifacts=[],
        warnings=["OpenCV Haar face fallback is disabled; verified OpenCV Zoo models are required."],
    )


def analyze_haar_frame(cv2: Any, cascade: Any, frame: Any, timestamp: float) -> HaarFrameResult:
    """Detect faces and speaker-stage context in one frame."""

    dark_ratio = dark_background_ratio(cv2, frame)
    faces = detect_scaled_haar_faces(cv2, cascade, frame)
    candidate = best_haar_face_candidate(cv2, frame, timestamp, faces, dark_ratio=dark_ratio)
    face_count = len(faces)
    return HaarFrameResult(candidate, face_count=face_count, dark_ratio=dark_ratio)


def best_haar_face_candidate(
    cv2: Any,
    frame: Any,
    timestamp: float,
    scaled_faces: list[tuple[int, int, int, int]] | None = None,
    *,
    dark_ratio: float | None = None,
) -> FrameCandidate | None:
    faces = scaled_faces or []
    if not faces:
        return None
    height, width = frame.shape[:2]
    scored = []
    for box in faces:
        x, y, w, h = [int(value) for value in box]
        geometry = face_box_quality((x, y, w, h), width, height)
        if not basic_face_geometry_is_clear(geometry, w, h):
            continue
        scored.append((geometry["score"], geometry["center_score"], box))
    if not scored:
        return None
    score, center_score, box = max(scored, key=lambda item: item[0])
    x, y, w, h = [int(value) for value in box]
    crop = frame[y : y + h, x : x + w]
    area = float((w * h) / max(1, width * height))
    confidence = max(0.65, min(0.95, 0.55 + score))
    return FrameCandidate(
        timestamp=timestamp,
        confidence=confidence,
        area=area,
        blur_score=blur_score(cv2, crop),
        frame=None,
        embedding=face_crop_embedding(cv2, crop),
        face_count=len(faces),
        dark_ratio=dark_background_ratio(cv2, frame) if dark_ratio is None else dark_ratio,
        crop=crop.copy(),
        center_score=float(center_score),
        face_width_px=w,
        face_height_px=h,
    )


def detect_scaled_haar_faces(cv2: Any, cascade: Any, frame: Any) -> list[tuple[int, int, int, int]]:
    gray, scale = gray_for_haar_detection(cv2, frame)
    minimum_face = max(24, int(round(48 / scale)))
    faces = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(minimum_face, minimum_face))
    return [scale_face_box(box, scale) for box in faces]


def gray_for_haar_detection(cv2: Any, frame: Any, *, max_width: int = 640) -> tuple[Any, float]:
    """Return a grayscale frame resized for faster Haar detection."""

    height, width = frame.shape[:2]
    if width <= max_width:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.0
    scale = width / float(max_width)
    resized_height = max(1, int(round(height / scale)))
    resized = cv2.resize(frame, (max_width, resized_height), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY), scale


def dark_background_ratio(cv2: Any, frame: Any) -> float:
    """Estimate how much of a frame is the dark speaker-stage background."""

    resized = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    return float((hsv[:, :, 2] < 60).sum()) / float(hsv.shape[0] * hsv.shape[1])


def is_audience_like_frame(face_count: int, dark_ratio: float) -> bool:
    """Return true for crowd cutaways that should not count as speaker visibility."""

    faces = int(face_count)
    darkness = float(dark_ratio)
    return faces >= 6 or (faces >= 4 and darkness < 0.68)


def is_stage_context_frame(face_count: int, dark_ratio: float) -> bool:
    """Return true for dark-stage frames that likely keep the main speaker visible."""

    return float(dark_ratio) >= 0.62 and not is_audience_like_frame(face_count, dark_ratio)


def intervals_from_sample_times(
    timestamps: list[float],
    *,
    sample_step: float,
    duration: float,
    confidence: float,
    gap_seconds: float,
) -> list[Interval]:
    """Convert accepted sample timestamps into smoothed visibility intervals."""

    intervals = [
        Interval(float(timestamp), min(float(timestamp) + sample_step, duration or float(timestamp) + sample_step), confidence)
        for timestamp in sorted(set(timestamps))
    ]
    return merge_nearby_intervals(intervals, gap_seconds=gap_seconds)


def intervals_from_weighted_sample_times(
    samples: list[tuple[float, float]],
    *,
    sample_step: float,
    duration: float,
    gap_seconds: float,
) -> list[Interval]:
    """Convert accepted timestamp/confidence samples into smoothed intervals."""

    intervals = [
        Interval(float(timestamp), min(float(timestamp) + sample_step, duration or float(timestamp) + sample_step), float(confidence))
        for timestamp, confidence in sorted(set(samples))
    ]
    return merge_nearby_intervals(intervals, gap_seconds=gap_seconds)


def candidate_intervals(candidates: list[FrameCandidate], *, sample_step: float, duration: float) -> list[Interval]:
    """Create visibility intervals directly from accepted face candidates."""

    return merge_nearby_intervals(
        [
            Interval(candidate.timestamp, min(candidate.timestamp + sample_step, duration or candidate.timestamp + sample_step), candidate.confidence)
            for candidate in candidates
        ],
        gap_seconds=strict_face_interval_gap(sample_step),
    )


def face_embedding_centroid(candidates: list[FrameCandidate]) -> list[float]:
    """Build a single reference embedding from same-person face candidates."""

    embeddings = [candidate.embedding or [] for candidate in candidates if candidate.embedding]
    if not embeddings:
        return []
    width = len(embeddings[0])
    centroid = [0.0] * width
    for embedding in embeddings:
        for index, value in enumerate(embedding[:width]):
            centroid[index] += float(value)
    centroid = [value / len(embeddings) for value in centroid]
    norm = sum(value * value for value in centroid) ** 0.5
    if norm == 0:
        return []
    return [value / norm for value in centroid]


def build_subject_visibility_intervals(
    samples: list[FaceSample],
    reference_embedding: list[float],
    *,
    sample_step: float,
    duration: float,
    confidence: float,
    identity_on_threshold: float,
    identity_off_threshold: float,
    merge_gap_seconds: float | None = None,
) -> list[Interval]:
    """Label same-speaker visibility using identity hysteresis and safe stage bridging."""

    if not reference_embedding:
        return []

    active = False
    pending_hits = 0
    min_run_samples = max(1, int(round(0.5 / max(sample_step, 0.001))))
    accepted: list[tuple[float, float]] = []

    for sample in sorted(samples, key=lambda item: item.timestamp):
        if sample.audience_like:
            active = False
            pending_hits = 0
            continue

        if not is_output_visibility_candidate(sample.candidate):
            active = False
            pending_hits = 0
            continue

        similarity = face_candidate_similarity(sample.candidate, reference_embedding)
        if similarity is not None:
            threshold = identity_off_threshold if active else identity_on_threshold
            if similarity >= threshold:
                pending_hits += 1
                if active or pending_hits >= min_run_samples:
                    active = True
                    accepted.append((sample.timestamp, sample.candidate.confidence if sample.candidate else confidence))
                continue

            active = False
            pending_hits = 0
            continue

        active = False
        pending_hits = 0

    return intervals_from_weighted_sample_times(
        accepted,
        sample_step=sample_step,
        duration=duration,
        gap_seconds=strict_face_interval_gap(sample_step) if merge_gap_seconds is None else merge_gap_seconds,
    )


def first_pass_face_interval_gap(sample_step: float) -> float:
    """Bridge tiny detector misses before second-pass validation checks frames."""

    return max(strict_face_interval_gap(sample_step), min(FIRST_PASS_FACE_INTERVAL_GAP_SECONDS, max(0.0, float(sample_step)) * 1.5))


def validation_face_interval_gap(sample_step: float) -> float:
    """Bridge short validation detector dropouts inside candidate clips."""

    return max(strict_face_interval_gap(sample_step), min(1.25, max(0.0, float(sample_step)) * 5.0))


def strict_face_interval_gap(sample_step: float) -> float:
    """Allow floating-point jitter but never bridge over a rejected sample.

    Clean speaker clips should fail closed: one audience, projection-screen, or
    no-face sample must split the interval so it cannot be stitched into a
    supposedly clean segment. A tiny gap still lets truly adjacent sampled
    intervals merge when timestamps carry codec/float noise.
    """

    return min(STRICT_FACE_INTERVAL_GAP_SECONDS, max(0.0, float(sample_step)) * 0.1)


def face_candidate_similarity(candidate: FrameCandidate | None, reference_embedding: list[float]) -> float | None:
    """Return candidate/reference identity similarity when both embeddings exist."""

    if candidate is None or not candidate.embedding or not reference_embedding:
        return None
    return cosine_similarity(candidate.embedding, reference_embedding)


def scale_face_box(box: Any, scale: float) -> tuple[int, int, int, int]:
    x, y, width, height = [float(value) for value in box]
    return (
        int(round(x * scale)),
        int(round(y * scale)),
        int(round(width * scale)),
        int(round(height * scale)),
    )


def face_box_score(box: Any, frame_width: int, frame_height: int) -> float:
    """Score a face box by useful face size and central framing."""

    return face_box_quality(box, frame_width, frame_height)["score"]


def face_box_quality(box: Any, frame_width: int, frame_height: int) -> dict[str, float]:
    """Return normalized face geometry signals used for quality gating."""

    x, y, width, height = [float(value) for value in box]
    area_score = (width * height) / max(1.0, float(frame_width * frame_height))
    center_x = (x + width / 2.0) / max(1.0, float(frame_width))
    center_y = (y + height / 2.0) / max(1.0, float(frame_height))
    center_distance = ((center_x - 0.5) ** 2 + (center_y - 0.45) ** 2) ** 0.5
    center_score = max(0.0, 1.0 - (center_distance * 2.0))
    return {
        "area": area_score,
        "center_score": center_score,
        "score": (area_score * 6.0) + (center_score * 0.4),
    }


def basic_face_geometry_is_clear(geometry: dict[str, float], width_px: int, height_px: int) -> bool:
    """Reject tiny or edge-of-frame faces before spending time on identity work."""

    if min(int(width_px), int(height_px)) < MIN_CLEAR_FACE_EDGE_PX:
        return False
    if float(geometry.get("area", 0.0)) < MIN_CLEAR_FACE_AREA:
        return False
    if float(geometry.get("center_score", 0.0)) < MIN_CLEAR_FACE_CENTER_SCORE:
        return False
    return True


def face_crop_embedding(cv2: Any, crop: Any) -> list[float]:
    if crop is None or crop.size == 0:
        return []
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (24, 24), interpolation=cv2.INTER_AREA)
    equalized = cv2.equalizeHist(resized)
    values = [float(value) / 255.0 for value in equalized.flatten()]
    return values


def is_identity_baseline_candidate(candidate: FrameCandidate | None) -> bool:
    """Return true when the target face is clear despite limited context faces."""

    if candidate is None or not candidate.embedding:
        return False
    if candidate.face_count < 1 or candidate.face_count > MAX_CONTEXT_FACE_COUNT:
        return False
    if candidate.area < MIN_CLEAR_FACE_AREA:
        return False
    if min(candidate.face_width_px, candidate.face_height_px) < MIN_CLEAR_FACE_EDGE_PX:
        return False
    if candidate.center_score < MIN_CLEAR_FACE_CENTER_SCORE:
        return False
    if candidate.blur_score < MIN_CLEAR_FACE_BLUR_SCORE:
        return False
    return True


def is_output_visibility_candidate(candidate: FrameCandidate | None) -> bool:
    """Return true when the target face is prominent enough for final clips.

    A small face on a projection screen or distant stage can be recognizable to
    a model but is not valid for downstream emotion analysis. Clean clips should
    only contain frames where the subject's face is large and inspectable.
    """

    if not is_identity_baseline_candidate(candidate):
        return False
    assert candidate is not None
    if candidate.area < MIN_OUTPUT_FACE_AREA:
        return False
    if min(candidate.face_width_px, candidate.face_height_px) < MIN_OUTPUT_FACE_EDGE_PX:
        return False
    return True


def select_main_face_candidates(candidates: list[FrameCandidate], *, similarity_threshold: float = 0.78) -> list[FrameCandidate]:
    """Keep candidates matching a dominant single-face identity baseline."""

    clear_candidates = [candidate for candidate in candidates if is_identity_baseline_candidate(candidate)]
    if not clear_candidates:
        return []

    baseline = select_dominant_baseline_candidates(
        clear_candidates,
        similarity_threshold=similarity_threshold,
        batch_size=IDENTITY_BASELINE_BATCH_SIZE,
        dominance_ratio=IDENTITY_BASELINE_DOMINANCE,
    )
    if baseline:
        centroid = face_embedding_centroid(baseline)
        selected: list[FrameCandidate] = []
        for candidate in clear_candidates:
            similarity = face_candidate_similarity(candidate, centroid)
            if similarity is not None and similarity >= similarity_threshold:
                selected.append(candidate)
        return sorted(selected, key=lambda item: item.timestamp)

    return []


def select_dominant_baseline_candidates(
    candidates: list[FrameCandidate],
    *,
    similarity_threshold: float,
    batch_size: int,
    dominance_ratio: float,
) -> list[FrameCandidate]:
    """Build one capped reference cluster for the dominant on-screen identity.

    Long videos can contain thousands of clear face candidates. Re-clustering a
    larger batch over and over is a hidden CPU sink, so we cluster a time-spread
    sample once and use that centroid to filter the full candidate list later.
    """

    valid = [candidate for candidate in candidates if is_identity_baseline_candidate(candidate)]
    if not valid:
        return []

    sample_limit = max(1, max(int(batch_size), MAX_IDENTITY_BASELINE_CLUSTER_CANDIDATES))
    sampled = sample_identity_baseline_candidates(valid, max_count=sample_limit)
    dominant = dominant_cluster_candidates(sampled, similarity_threshold=similarity_threshold)
    if dominant:
        dominance = len(dominant) / len(sampled)
        if dominance >= dominance_ratio:
            return dominant
        if dominance >= RELAXED_IDENTITY_CLUSTER_DOMINANCE and len(dominant) >= MIN_RELAXED_IDENTITY_CLUSTER_CANDIDATES:
            return dominant
    return []


def sample_identity_baseline_candidates(candidates: list[FrameCandidate], *, max_count: int) -> list[FrameCandidate]:
    """Return a high-quality, time-spread sample for bounded identity clustering."""

    if len(candidates) <= max_count:
        return list(candidates)

    ranked = sorted(candidates, key=still_quality_score, reverse=True)
    start_time = min(candidate.timestamp for candidate in ranked)
    end_time = max(candidate.timestamp for candidate in ranked)
    span = max(1.0, end_time - start_time)
    buckets: list[FrameCandidate | None] = [None for _ in range(max_count)]

    for candidate in ranked:
        bucket_index = min(max_count - 1, int(((candidate.timestamp - start_time) / span) * max_count))
        if buckets[bucket_index] is None:
            buckets[bucket_index] = candidate

    selected = [candidate for candidate in buckets if candidate is not None]
    selected_ids = {id(candidate) for candidate in selected}
    for candidate in ranked:
        if len(selected) >= max_count:
            break
        if id(candidate) in selected_ids:
            continue
        selected.append(candidate)
        selected_ids.add(id(candidate))

    return sorted(selected[:max_count], key=lambda item: item.timestamp)


def dominant_cluster_candidates(candidates: list[FrameCandidate], *, similarity_threshold: float) -> list[FrameCandidate]:
    """Return the largest identity cluster from an already-filtered candidate set."""

    embeddings = [candidate.embedding or [] for candidate in candidates]
    assignments = assign_identity_clusters(embeddings, similarity_threshold=similarity_threshold)
    cluster_counts: dict[int, int] = {}
    for cluster_id in assignments:
        cluster_counts[cluster_id] = cluster_counts.get(cluster_id, 0) + 1
    if not cluster_counts:
        return []
    main_cluster = max(cluster_counts, key=cluster_counts.get)
    return [candidate for candidate, cluster_id in zip(candidates, assignments) if cluster_id == main_cluster]


def stable_candidate_seed(candidates: list[FrameCandidate]) -> int:
    """Derive a reproducible shuffle seed from candidate timing and geometry."""

    seed = 17
    for candidate in candidates:
        seed = (seed * 31 + int(round(candidate.timestamp * 1000))) & 0xFFFFFFFF
        seed = (seed * 31 + int(round(candidate.area * 1_000_000))) & 0xFFFFFFFF
    return seed


def face_area(detection: Any) -> float:
    box = detection.location_data.relative_bounding_box
    return float(max(0.0, box.width) * max(0.0, box.height))


def blur_score(cv2: Any, frame: Any) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def still_quality_score(candidate: FrameCandidate) -> float:
    """Score face crops for human-reviewable identity still selection."""

    return (
        float(candidate.confidence) * 2.0
        + float(candidate.area) * 10.0
        + min(float(candidate.blur_score), 200.0) / 200.0
        + float(candidate.center_score)
    )


def select_diverse_still_candidates(candidates: list[FrameCandidate], count: int) -> list[FrameCandidate]:
    """Cull same-person candidates into a time-spread reference gallery.

    The old face-only prototype first oversampled possible reference faces and
    then pruned them. This keeps that idea: choose the best crop per timeline
    bucket first, then fill gaps only if the video has fewer usable regions.
    """

    usable = [candidate for candidate in candidates if is_output_visibility_candidate(candidate)]
    if count <= 0 or not usable:
        return []

    ranked = sorted(usable, key=still_quality_score, reverse=True)
    if len(ranked) <= count:
        return sorted(ranked, key=lambda item: item.timestamp)

    start_time = min(candidate.timestamp for candidate in ranked)
    end_time = max(candidate.timestamp for candidate in ranked)
    span = max(1.0, end_time - start_time)
    bucket_count = max(1, int(count))
    buckets: list[list[FrameCandidate]] = [[] for _ in range(bucket_count)]

    for candidate in ranked:
        bucket_index = min(bucket_count - 1, int(((candidate.timestamp - start_time) / span) * bucket_count))
        buckets[bucket_index].append(candidate)

    selected: list[FrameCandidate] = []
    for bucket in buckets:
        if not bucket:
            continue
        selected.append(max(bucket, key=still_quality_score))
        if len(selected) >= count:
            break

    min_gap = max(1.0, span / max(1, count * 2))
    for minimum_gap in (min_gap, max(1.0, min_gap / 3.0), 0.0):
        for candidate in ranked:
            if len(selected) >= count:
                break
            if candidate in selected:
                continue
            if minimum_gap and any(abs(candidate.timestamp - item.timestamp) < minimum_gap for item in selected):
                continue
            selected.append(candidate)
        if len(selected) >= count:
            break

    return sorted(selected[:count], key=lambda item: item.timestamp)


def save_best_stills(cv2: Any, candidates: list[FrameCandidate], output_dir: Path, count: int) -> list[Path]:
    """Pick high-quality stills while spreading them across the video timeline."""

    selected = select_diverse_still_candidates(candidates, count)
    if not selected:
        return []

    artifacts: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, candidate in enumerate(selected, start=1):
        path = output_dir / f"still_{index:03d}_{candidate.timestamp:.2f}s.jpg"
        image = candidate.crop if candidate.crop is not None else candidate.frame
        if write_jpeg(cv2, path, image):
            artifacts.append(path)
    return artifacts


def write_jpeg(cv2: Any, path: Path, image: Any) -> bool:
    """Write a JPEG through Python paths so Unicode Windows folders work."""

    if image is None:
        return False
    try:
        ok, encoded = cv2.imencode(".jpg", image)
    except Exception:
        return False
    if not ok:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded.tobytes())
    return True


def extract_even_stills_with_ffmpeg(video_path: Path, output_dir: Path, duration: float, count: int) -> list[Path]:
    if duration <= 0 or count <= 0:
        return []
    artifacts: list[Path] = []
    for index in range(1, count + 1):
        timestamp = (duration * index) / (count + 1)
        target = output_dir / f"still_{index:03d}_{timestamp:.2f}s.jpg"
        try:
            subprocess.run(
                [str(resolve_media_binary("ffmpeg", excluded_roots=(video_path.parent, output_dir))), "-y", "-ss", f"{timestamp:.3f}", "-i", str(video_path), "-frames:v", "1", str(target)],
                check=True,
                capture_output=True,
                env=credential_free_media_environment(),
            )
            artifacts.append(target)
        except Exception:
            break
    return artifacts


def extract_audio(video_path: Path, audio_path: Path) -> None:
    try:
        subprocess.run(
            [str(resolve_media_binary("ffmpeg", excluded_roots=(video_path.parent, audio_path.parent))), "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", str(audio_path)],
            check=True,
            capture_output=True,
            env=credential_free_media_environment(),
        )
    except Exception:
        return


def detect_audio_activity(audio_path: Path, duration: float, *, confidence: float) -> list[Interval]:
    """Detect non-silent audio regions when speaker diarization is unavailable."""

    if duration <= 0 or not audio_path.exists():
        return []
    try:
        result = subprocess.run(
            [
                str(resolve_media_binary("ffmpeg", excluded_roots=(audio_path.parent,))),
                "-hide_banner",
                "-i",
                str(audio_path),
                "-af",
                "silencedetect=noise=-35dB:d=0.45",
                "-f",
                "null",
                "-",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=credential_free_media_environment(),
        )
    except Exception:
        return [Interval(0.0, duration, confidence)]
    return parse_audio_activity_from_silencedetect(result.stderr + "\n" + result.stdout, duration=duration, confidence=confidence)


def parse_audio_activity_from_silencedetect(output: str, *, duration: float, confidence: float) -> list[Interval]:
    """Convert ffmpeg silencedetect logs into non-silent intervals."""

    silence_events: list[tuple[str, float]] = []
    for line in output.splitlines():
        start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
        if start_match:
            silence_events.append(("start", float(start_match.group(1))))
        end_match = re.search(r"silence_end:\s*([0-9.]+)", line)
        if end_match:
            silence_events.append(("end", float(end_match.group(1))))

    if duration <= 0:
        return []
    if not silence_events:
        return [Interval(0.0, duration, confidence)]

    intervals: list[Interval] = []
    active_start = 0.0
    in_silence = False
    for event_type, timestamp in sorted(silence_events, key=lambda item: item[1]):
        timestamp = max(0.0, min(duration, timestamp))
        if event_type == "start" and not in_silence:
            if timestamp > active_start:
                intervals.append(Interval(active_start, timestamp, confidence))
            in_silence = True
        elif event_type == "end" and in_silence:
            active_start = timestamp
            in_silence = False
    if not in_silence and active_start < duration:
        intervals.append(Interval(active_start, duration, confidence))
    return [interval for interval in intervals if interval.duration > 0.05]


def isolate_audio_intervals(audio_path: Path, target_path: Path, intervals: list[Interval], *, keep_debug: bool) -> None:
    """Create a main-speaker-only audio file by concatenating diarized intervals."""

    if not intervals or not audio_path.exists():
        return
    segment_files: list[Path] = []
    for index, interval in enumerate(intervals, start=1):
        segment = target_path.parent / f"_main_voice_segment_{index:03d}.wav"
        try:
            subprocess.run(
                [
                    str(resolve_media_binary(
                        "ffmpeg",
                        excluded_roots=(audio_path.parent, target_path.parent),
                    )),
                    "-y",
                    "-ss",
                    f"{interval.start:.3f}",
                    "-i",
                    str(audio_path),
                    "-t",
                    f"{interval.duration:.3f}",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    str(segment),
                ],
                check=True,
                capture_output=True,
                env=credential_free_media_environment(),
            )
            segment_files.append(segment)
        except Exception:
            return
    concat_list = target_path.parent / "_main_voice_concat.txt"
    concat_list.write_text("".join(f"file '{item.as_posix()}'\n" for item in segment_files), encoding="utf-8")
    try:
        subprocess.run(
            [str(resolve_media_binary("ffmpeg", excluded_roots=(concat_list.parent, target_path.parent))), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(target_path)],
            check=True,
            capture_output=True,
            env=credential_free_media_environment(),
        )
    except Exception:
        return
    if not keep_debug:
        concat_list.unlink(missing_ok=True)
        for segment in segment_files:
            segment.unlink(missing_ok=True)


def retain_voice_audio_artifacts(audio_path: Path, output_dir: Path, intervals: list[Interval], *, keep_debug: bool) -> list[Path]:
    """Keep heavy voice WAVs only when the researcher explicitly asks for debug artifacts."""

    if not keep_debug:
        remove_audio_scratch(audio_path)
        return []

    artifacts: list[Path] = []
    if audio_path.exists():
        artifacts.append(audio_path)
    isolated = output_dir / "main_voice_isolated.wav"
    isolate_audio_intervals(audio_path, isolated, intervals, keep_debug=True)
    if isolated.exists():
        artifacts.append(isolated)
    return artifacts


def retain_failed_audio_artifact(audio_path: Path, *, keep_debug: bool) -> list[Path]:
    """Return or remove extracted audio after an unsuccessful voice path."""

    if keep_debug and audio_path.exists():
        return [audio_path]
    remove_audio_scratch(audio_path)
    return []


def remove_audio_scratch(audio_path: Path) -> None:
    """Best-effort cleanup for large temporary WAVs produced during voice analysis."""

    try:
        audio_path.unlink(missing_ok=True)
    except OSError:
        pass


def dominant_speaker_intervals(diarization: Any, *, threshold: float) -> list[Interval]:
    durations: dict[str, float] = {}
    tracks: list[tuple[Any, str]] = []
    for turn, _track, speaker in diarization.itertracks(yield_label=True):
        durations[speaker] = durations.get(speaker, 0.0) + float(turn.end - turn.start)
        tracks.append((turn, speaker))
    if not durations:
        return []
    dominant = max(durations, key=durations.get)
    return [Interval(float(turn.start), float(turn.end), max(0.0, min(1.0, threshold))) for turn, speaker in tracks if speaker == dominant]


def huggingface_token() -> str:
    return (
        os.getenv("HF_TOKEN")
        or os.getenv("HUGGINGFACE_TOKEN")
        or os.getenv("HUGGING_FACE_HUB_TOKEN")
        or ""
    ).strip()


def reference_audio_warnings(reference_audio: Path | None) -> list[str]:
    if reference_audio is None:
        return []
    if not reference_audio.exists():
        return [f"Reference audio was supplied but not found: {reference_audio}"]
    return ["Reference audio supplied; ECAPA speaker-profile matching is enabled for this run."]
