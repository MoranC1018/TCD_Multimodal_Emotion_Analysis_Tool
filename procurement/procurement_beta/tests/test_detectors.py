from __future__ import annotations
import json
import hashlib

import wave
from pathlib import Path

import pytest

from procurement.procurement_beta import detectors as detectors_module
from procurement.procurement_beta.detectors import (
    FaceVisibilityAnalyzer,
    FaceSample,
    FrameCandidate,
    MainVoiceAnalyzer,
    analyze_with_opencv_haar,
    build_validated_subject_visibility_intervals,
    build_subject_visibility_intervals,
    build_insightface_subject_visibility_intervals,
    build_speechbrain_embedding_windows,
    dominant_embedding_intervals,
    extract_audio,
    first_pass_face_interval_gap,
    gray_for_haar_detection,
    intervals_from_sample_times,
    is_audience_like_frame,
    is_identity_baseline_candidate,
    is_output_visibility_candidate,
    is_insightface_reference_candidate,
    is_insightface_visibility_candidate,
    load_external_reference_embedding,
    local_model_cache_dir,
    is_stage_context_frame,
    iter_sampled_video_frames,
    load_wav_window_tensor,
    load_speechbrain_ecapa_classifier,
    model_file_ready,
    download_model_file,
    parse_audio_activity_from_silencedetect,
    prepare_insightface_app,
    sample_identity_baseline_candidates,
    save_best_stills,
    select_diverse_still_candidates,
    select_dominant_baseline_candidates,
    select_main_face_candidates,
    select_main_insightface_candidates,
    select_insightface_candidates_matching_reference,
    select_insightface_reference_candidates,
    select_insightface_still_export_candidates,
)
from procurement.procurement_beta.intervals import Interval
from procurement.procurement_beta.pipeline import ProcurementBetaOptions
from procurement.procurement_beta.reference_bank_from_videos import load_seed_embedding


def test_model_cache_prefers_tool_path_but_reuses_existing_legacy_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = tmp_path / "MultimodalEmotionAnalysisPipeline" / "models"
    preferred = tmp_path / "MultimodalEmotionAnalysisTool" / "models"
    legacy.mkdir(parents=True)

    assert local_model_cache_dir() == legacy
    preferred.mkdir(parents=True)
    assert local_model_cache_dir() == preferred


def test_face_analyzer_never_loads_unverified_insightface_or_haar_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(detectors_module.backend, "read_duration_seconds", lambda _path: 10.0)

    def fake_optional_import(name: str) -> object:
        if name != "cv2":
            raise AssertionError(f"unexpected unverified model import: {name}")
        return object()

    monkeypatch.setattr(detectors_module, "optional_import", fake_optional_import)
    monkeypatch.setattr(detectors_module, "analyze_with_opencv_zoo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        detectors_module,
        "analyze_with_opencv_haar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Haar fallback must not run")),
    )
    options = ProcurementBetaOptions("clean", 0.10, 10, 30, 0, 20, 1, 0.65, 0.65, 1, "cpu", False)

    result = FaceVisibilityAnalyzer().analyze(tmp_path / "video.mp4", tmp_path / "output", options)

    assert result.method == "unavailable_face_model"
    assert not result.intervals


def test_insightface_preparer_is_disabled_before_faceanalysis_can_load_or_download() -> None:
    calls: list[object] = []

    class FakeFaceAnalysis:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def prepare(self, **kwargs):
            calls.append(kwargs)

    class FakeInsightFace:
        class app:
            FaceAnalysis = FakeFaceAnalysis

    with pytest.raises(RuntimeError, match="disabled"):
        prepare_insightface_app(FakeInsightFace())

    assert calls == []


def test_haar_analyzer_is_disabled_before_loading_the_package_cascade(tmp_path: Path) -> None:
    class FakeCv2:
        @property
        def data(self):
            raise AssertionError("the unverified Haar cascade must not be loaded")

    options = ProcurementBetaOptions("clean", 0.10, 10, 30, 0, 20, 1, 0.65, 0.65, 1, "cpu", False)

    result = analyze_with_opencv_haar(FakeCv2(), tmp_path / "video.mp4", tmp_path, 10.0, options)

    assert result.method == "unavailable_face_model"
    assert not result.intervals


def test_model_file_ready_requires_the_expected_sha256(tmp_path: Path) -> None:
    model = tmp_path / "model.onnx"
    payload = b"verified model bytes"
    model.write_bytes(payload)

    assert model_file_ready(model, hashlib.sha256(payload).hexdigest())
    assert not model_file_ready(model, hashlib.sha256(b"different").hexdigest())


def test_model_download_verifies_a_sibling_temp_before_atomic_install(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "model.onnx"
    target.write_bytes(b"untrusted cached bytes")
    payload = b"new verified model bytes"
    retrieval_paths = []

    def fake_retrieve(_url: str, destination: Path):
        retrieval_paths.append(Path(destination))
        Path(destination).write_bytes(payload)

    monkeypatch.setattr("procurement.procurement_beta.detectors.urlretrieve", fake_retrieve)

    assert download_model_file("https://example.invalid/model", target, hashlib.sha256(payload).hexdigest())
    assert retrieval_paths[0] != target
    assert target.read_bytes() == payload
    assert not retrieval_paths[0].exists()

def clear_candidate(
    timestamp: float,
    embedding: list[float],
    *,
    area: float = 0.20,
    confidence: float = 0.8,
    face_count: int = 1,
    blur_score: float = 20.0,
    center_score: float = 0.9,
    face_edge_px: int = 160,
) -> FrameCandidate:
    """Build a synthetic face candidate that passes the strict quality gate."""

    return FrameCandidate(
        timestamp,
        confidence,
        area,
        blur_score,
        object(),
        embedding,
        face_count=face_count,
        crop=object(),
        center_score=center_score,
        face_width_px=face_edge_px,
        face_height_px=face_edge_px,
    )



class FakeJpegBuffer:
    def __init__(self, payload: bytes = b"jpeg") -> None:
        self.payload = payload

    def tobytes(self) -> bytes:
        return self.payload


class FakeCv2JpegWriter:
    def imencode(self, extension: str, image: object):
        assert extension == ".jpg"
        assert image is not None
        return True, FakeJpegBuffer()
class FakeCv2Constants:
    CAP_PROP_FPS = 1
    CAP_PROP_POS_MSEC = 2


class FakeSequentialCapture:
    def __init__(self, fps: float, frame_count: int = 40) -> None:
        self.fps = fps
        self.frames = [object() for _ in range(frame_count)]
        self.index = 0
        self.grab_calls = 0
        self.read_calls = 0
        self.set_calls: list[tuple[int, float]] = []

    def get(self, prop: int) -> float:
        if prop == FakeCv2Constants.CAP_PROP_FPS:
            return self.fps
        return 0.0

    def grab(self) -> bool:
        if self.index >= len(self.frames):
            return False
        self.index += 1
        self.grab_calls += 1
        return True

    def read(self):
        if self.index >= len(self.frames):
            return False, None
        frame = self.frames[self.index]
        self.index += 1
        self.read_calls += 1
        return True, frame

    def set(self, prop: int, value: float) -> None:
        self.set_calls.append((prop, value))


class ReadRaisesOnceCapture(FakeSequentialCapture):
    """Capture double that simulates one OpenCV decoder exception."""

    def __init__(self, fps: float, frame_count: int = 40) -> None:
        super().__init__(fps=fps, frame_count=frame_count)
        self.raised = False

    def read(self):
        if not self.raised:
            self.raised = True
            raise RuntimeError("cv2 decode failed")
        return super().read()


def test_iter_sampled_video_frames_uses_sequential_grabs_when_fps_is_known() -> None:
    capture = FakeSequentialCapture(fps=4.0)

    samples = list(iter_sampled_video_frames(FakeCv2Constants, capture, duration=2.1, sample_step=1.0))

    assert [timestamp for timestamp, _frame in samples] == [0.0, 1.0, 2.0]
    assert capture.read_calls == 3
    assert capture.grab_calls == 6
    assert capture.set_calls == []


def test_iter_sampled_video_frames_falls_back_to_timestamp_seeks_without_fps() -> None:
    capture = FakeSequentialCapture(fps=0.0)

    samples = list(iter_sampled_video_frames(FakeCv2Constants, capture, duration=2.1, sample_step=1.0))

    assert [timestamp for timestamp, _frame in samples] == [0.0, 1.0, 2.0]
    assert capture.read_calls == 3
    assert capture.grab_calls == 0
    assert capture.set_calls == [
        (FakeCv2Constants.CAP_PROP_POS_MSEC, 0.0),
        (FakeCv2Constants.CAP_PROP_POS_MSEC, 1000.0),
        (FakeCv2Constants.CAP_PROP_POS_MSEC, 2000.0),
    ]


def test_iter_sampled_video_frames_recovers_from_one_read_exception() -> None:
    capture = ReadRaisesOnceCapture(fps=4.0)

    samples = list(iter_sampled_video_frames(FakeCv2Constants, capture, duration=2.1, sample_step=1.0))

    assert [timestamp for timestamp, _frame in samples] == [0.0, 1.0, 2.0]
    assert capture.set_calls[0] == (FakeCv2Constants.CAP_PROP_POS_MSEC, 0.0)


def test_parse_audio_activity_from_silencedetect_keeps_non_silent_intervals() -> None:
    output = """
    [silencedetect @ 000001] silence_start: 3.5
    [silencedetect @ 000001] silence_end: 6.0 | silence_duration: 2.5
    [silencedetect @ 000001] silence_start: 9.25
    [silencedetect @ 000001] silence_end: 11.0 | silence_duration: 1.75
    """

    intervals = parse_audio_activity_from_silencedetect(output, duration=15.0, confidence=0.65)

    assert intervals == [
        Interval(0.0, 3.5, 0.65),
        Interval(6.0, 9.25, 0.65),
        Interval(11.0, 15.0, 0.65),
    ]


def test_parse_audio_activity_from_silencedetect_marks_all_active_when_no_silence_is_found() -> None:
    intervals = parse_audio_activity_from_silencedetect("", duration=20.0, confidence=0.65)

    assert intervals == [Interval(0.0, 20.0, 0.65)]


def test_voice_analyzer_skips_full_audio_extract_when_diarization_is_unavailable(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"fake video")
    output_dir = tmp_path / "out"
    seen_paths: list[Path] = []
    imported_modules: list[str] = []

    monkeypatch.setattr("procurement.procurement_beta.detectors.huggingface_token", lambda: "")
    monkeypatch.setattr("procurement.procurement_beta.detectors.optional_import", lambda name: imported_modules.append(name) or None)
    monkeypatch.setattr("procurement.procurement_beta.detectors.backend.read_duration_seconds", lambda _path: 12.0)
    monkeypatch.setattr(
        "procurement.procurement_beta.detectors.detect_audio_activity",
        lambda path, duration, confidence: seen_paths.append(Path(path)) or [Interval(1.0, 4.0, confidence)],
    )
    monkeypatch.setattr(
        "procurement.procurement_beta.detectors.extract_audio",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("extract_audio should not run")),
    )

    result = MainVoiceAnalyzer().analyze(
        video_path,
        output_dir,
        ProcurementBetaOptions("clean", 0.10, 10, 30, 0.5, 20, 1, 0.65, 0.65, 1, "cpu", False),
    )

    assert result.intervals == [Interval(1.0, 4.0, 0.4)]
    assert seen_paths == [video_path]
    assert imported_modules == ["speechbrain.inference.speaker", "torch"]
    assert result.artifacts == []


def test_voice_analyzer_prefers_speechbrain_embedding_result_without_hf_token(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"fake video")
    output_dir = tmp_path / "out"
    expected = [Interval(2.0, 12.0, 0.72)]

    monkeypatch.setattr("procurement.procurement_beta.detectors.huggingface_token", lambda: "")
    monkeypatch.setattr("procurement.procurement_beta.detectors.backend.read_duration_seconds", lambda _path: 20.0)
    monkeypatch.setattr(
        "procurement.procurement_beta.detectors.analyze_with_speechbrain_ecapa",
        lambda *_args, **_kwargs: type(
            "SpeechBrainResult",
            (),
            {
                "intervals": expected,
                "method": "speechbrain_ecapa_dominant_speaker",
                "artifacts": [],
                "warnings": [],
            },
        )(),
    )
    monkeypatch.setattr(
        "procurement.procurement_beta.detectors.detect_audio_activity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("heuristic fallback should not run")),
    )

    result = MainVoiceAnalyzer().analyze(
        video_path,
        output_dir,
        ProcurementBetaOptions("clean", 0.10, 10, 30, 0.5, 20, 1, 0.65, 0.65, 1, "cpu", False),
    )

    assert result.intervals == expected
    assert result.method == "speechbrain_ecapa_dominant_speaker"


def test_voice_analyzer_does_not_accept_full_video_when_diarization_errors(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"fake video")
    output_dir = tmp_path / "out"

    pipeline_call = {}

    class FailingPipeline:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            pipeline_call["args"] = args
            pipeline_call["kwargs"] = kwargs
            raise RuntimeError("model access failed")

    class FakePyannote:
        Pipeline = FailingPipeline

    def fake_extract_audio(_video_path: Path, audio_path: Path) -> None:
        audio_path.write_bytes(b"fake audio")

    monkeypatch.setattr("procurement.procurement_beta.detectors.huggingface_token", lambda: "token")
    monkeypatch.setattr("procurement.procurement_beta.detectors.optional_import", lambda name: FakePyannote if name == "pyannote.audio" else None)
    monkeypatch.setattr("procurement.procurement_beta.detectors.backend.read_duration_seconds", lambda _path: 12.0)
    monkeypatch.setattr("procurement.procurement_beta.detectors.extract_audio", fake_extract_audio)

    result = MainVoiceAnalyzer().analyze(
        video_path,
        output_dir,
        ProcurementBetaOptions("clean", 0.10, 10, 30, 0.5, 20, 1, 0.65, 0.65, 1, "cpu", False),
    )

    assert result.intervals == []
    assert result.method == "pyannote_speaker_diarization_error"
    assert result.artifacts == []
    assert not (output_dir / "main_voice_audio.wav").exists()
    assert any("requires model-backed main-speaker diarization" in warning for warning in result.warnings)
    assert pipeline_call["kwargs"]["revision"] == "84fd25912480287da0247647c3d2b4853cb3ee5d"


def test_speechbrain_windows_split_active_audio_into_contiguous_chunks() -> None:
    windows = build_speechbrain_embedding_windows(
        [
            Interval(0.0, 13.0, 0.8),
            Interval(20.0, 22.0, 0.8),
        ],
        window_seconds=5.0,
        min_window_seconds=2.5,
    )

    assert windows == [
        Interval(0.0, 5.0, 0.8),
        Interval(5.0, 10.0, 0.8),
        Interval(10.0, 13.0, 0.8),
    ]


def test_speechbrain_loader_uses_copy_strategy_for_windows_laptops(monkeypatch) -> None:
    calls: dict[str, object] = {}
    copy_strategy = object()

    class FakeEncoderClassifier:
        @staticmethod
        def from_hparams(**kwargs):
            calls.update(kwargs)
            return "classifier"

    class FakeSpeakerModule:
        EncoderClassifier = FakeEncoderClassifier

    class FakeLocalStrategy:
        COPY = copy_strategy

    class FakeFetchingModule:
        LocalStrategy = FakeLocalStrategy

        class FetchConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

    monkeypatch.setattr(
        "procurement.procurement_beta.detectors.optional_import",
        lambda name: FakeFetchingModule if name == "speechbrain.utils.fetching" else None,
    )

    classifier = load_speechbrain_ecapa_classifier(
        FakeSpeakerModule,
        ProcurementBetaOptions("clean", 0.10, 10, 30, 0.5, 20, 1, 0.65, 0.65, 1, "cpu", False),
    )

    assert classifier == "classifier"
    assert calls["local_strategy"] is copy_strategy
    assert calls["run_opts"] == {"device": "cpu"}
    assert calls["fetch_config"].revision == "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"
    assert calls["fetch_config"].allow_updates is True


def test_load_wav_window_tensor_reads_pcm_without_torchaudio(tmp_path) -> None:
    torch = pytest.importorskip("torch")
    audio_path = tmp_path / "sample.wav"
    samples = [0, 16384, -16384, 32767]

    with wave.open(str(audio_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(4)
        handle.writeframes(b"".join(int(sample).to_bytes(2, "little", signed=True) for sample in samples))

    tensor = load_wav_window_tensor(torch, audio_path, start_seconds=0.25, duration_seconds=0.5)

    assert tensor.shape == (1, 2)
    assert tensor.tolist()[0] == [0.5, -0.5]


def test_dominant_embedding_intervals_require_dominant_cluster() -> None:
    windows = [
        Interval(0.0, 5.0, 0.8),
        Interval(5.0, 10.0, 0.8),
        Interval(10.0, 15.0, 0.8),
        Interval(15.0, 20.0, 0.8),
    ]
    embeddings = [
        [1.0, 0.0],
        [0.98, 0.02],
        [1.0, 0.01],
        [0.0, 1.0],
    ]

    intervals = dominant_embedding_intervals(
        windows,
        embeddings,
        confidence=0.7,
        similarity_threshold=0.9,
        dominance_ratio=0.6,
    )

    assert intervals == [Interval(0.0, 15.0, 0.7)]


def test_face_analyzer_does_not_mark_full_video_clean_without_face_model(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"fake video")

    monkeypatch.setattr("procurement.procurement_beta.detectors.optional_import", lambda _name: None)
    monkeypatch.setattr("procurement.procurement_beta.detectors.backend.read_duration_seconds", lambda _path: 12.0)

    result = FaceVisibilityAnalyzer().analyze(
        video_path,
        tmp_path / "out",
        ProcurementBetaOptions("clean", 0.10, 10, 30, 0.5, 20, 1, 0.65, 0.65, 1, "cpu", False),
    )

    assert result.intervals == []
    assert result.method == "unavailable_face_model"







def test_insightface_still_export_fills_with_verified_smaller_main_faces() -> None:
    candidates = [
        clear_candidate(10.0, [1.0, 0.0], face_edge_px=100, area=0.01),
        clear_candidate(20.0, [1.0, 0.0], face_edge_px=96, area=0.01),
        clear_candidate(30.0, [1.0, 0.0], face_edge_px=44, area=0.003),
        clear_candidate(40.0, [1.0, 0.0], face_edge_px=42, area=0.003),
    ]

    selected = select_insightface_still_export_candidates(candidates, 4)

    assert len(selected) == 4
    assert [candidate.timestamp for candidate in selected] == [10.0, 20.0, 30.0, 40.0]

def test_external_reference_embedding_loads_curated_reference_json(tmp_path: Path) -> None:
    reference_dir = tmp_path / "reference_faces"
    reference_dir.mkdir()
    (reference_dir / "reference_embedding.json").write_text(
        json.dumps({"embedding": [0.6, 0.8]}),
        encoding="utf-8",
    )

    embedding = load_external_reference_embedding(reference_dir)

    assert embedding == [0.6, 0.8]


def test_external_reference_embedding_rejects_excessive_semantic_items(tmp_path: Path) -> None:
    reference_dir = tmp_path / "reference_faces"
    reference_dir.mkdir()
    (reference_dir / "reference_embedding.json").write_text(
        json.dumps({"embedding": [0.0] * 8_193}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="more than 8192 items"):
        load_external_reference_embedding(reference_dir)


def test_reference_bank_seed_rejects_excessive_semantic_items(tmp_path: Path) -> None:
    (tmp_path / "reference_embedding.json").write_text(
        json.dumps({"embedding": [0.0] * 8_193}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="more than 8192 items"):
        load_seed_embedding(tmp_path)


def test_extract_audio_strips_credentials_from_ffmpeg_child(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*_args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    secret_names = ("YOUTUBE_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN")
    for name in secret_names:
        monkeypatch.setenv(name, f"secret-{name}")
    monkeypatch.setattr("procurement.procurement_beta.detectors.resolve_media_binary", lambda *_args, **_kwargs: Path("C:/trusted/ffmpeg.exe"))
    monkeypatch.setattr("procurement.procurement_beta.detectors.subprocess.run", fake_run)

    extract_audio(tmp_path / "source.mp4", tmp_path / "audio.wav")

    environment = captured.get("env")
    assert isinstance(environment, dict)
    assert all(name not in environment for name in secret_names)

def test_insightface_visibility_allows_smaller_faces_than_reference_stills() -> None:
    candidate = clear_candidate(10.0, [1.0, 0.0], face_count=6, face_edge_px=40, area=0.001, blur_score=3.0)

    assert not is_insightface_reference_candidate(candidate)
    assert is_insightface_visibility_candidate(candidate)

def test_insightface_main_selection_keeps_largest_matching_face_in_multi_face_frames() -> None:
    speaker_a = [1.0, 0.0]
    speaker_b = [0.0, 1.0]
    candidates = [
        clear_candidate(0.0, speaker_a, face_count=12, confidence=0.9),
        clear_candidate(1.0, speaker_a, face_count=9, confidence=0.88),
        clear_candidate(2.0, speaker_a, face_count=15, confidence=0.86),
        clear_candidate(3.0, speaker_b, face_count=1, confidence=0.95),
    ]

    selected = select_main_insightface_candidates(candidates, similarity_threshold=0.42)

    assert [candidate.timestamp for candidate in selected] == [0.0, 1.0, 2.0]




def test_insightface_main_selection_prefers_early_reference_window_over_later_cutaways() -> None:
    speaker = [1.0, 0.0]
    later_cutaway = [0.0, 1.0]
    candidates = [
        clear_candidate(200.0, speaker, face_count=2, confidence=0.9),
        clear_candidate(208.0, speaker, face_count=2, confidence=0.88),
        clear_candidate(520.0, later_cutaway, face_count=1, confidence=0.95),
        clear_candidate(528.0, later_cutaway, face_count=1, confidence=0.95),
        clear_candidate(536.0, later_cutaway, face_count=1, confidence=0.95),
    ]

    selected = select_main_insightface_candidates(candidates, similarity_threshold=0.42)

    assert [candidate.timestamp for candidate in selected] == [200.0, 208.0]



def test_insightface_reference_recovers_to_recurring_identity_when_opening_is_sparse() -> None:
    opening_person = [1.0, 0.0]
    recurring_person = [0.0, 1.0]
    opening = [
        clear_candidate(200.0, opening_person, confidence=0.9),
        clear_candidate(208.0, opening_person, confidence=0.88),
    ]
    full_candidates = opening + [
        clear_candidate(float(300 + index * 20), recurring_person, face_edge_px=44, area=0.003, confidence=0.72)
        for index in range(16)
    ]

    selected = select_insightface_reference_candidates(
        opening,
        full_candidates,
        similarity_threshold=0.42,
    )

    assert [candidate.timestamp for candidate in selected[:3]] == [300.0, 320.0, 340.0]
    assert len(selected) == 16
def test_insightface_matching_reference_culls_later_unmatched_large_faces() -> None:
    speaker = [1.0, 0.0]
    audience_closeup = [0.0, 1.0]
    reference = [
        clear_candidate(200.0, speaker, face_count=2, confidence=0.9),
        clear_candidate(208.0, speaker, face_count=2, confidence=0.88),
    ]
    candidates = reference + [
        clear_candidate(520.0, audience_closeup, face_count=1, confidence=0.95),
        clear_candidate(528.0, audience_closeup, face_count=1, confidence=0.95),
        clear_candidate(536.0, audience_closeup, face_count=1, confidence=0.95),
    ]

    selected = select_insightface_candidates_matching_reference(
        candidates,
        reference,
        similarity_threshold=0.42,
    )

    assert [candidate.timestamp for candidate in selected] == [200.0, 208.0]
def test_insightface_visibility_uses_identity_not_audience_like_face_count() -> None:
    reference = [1.0, 0.0]
    samples = [
        FaceSample(0.0, clear_candidate(0.0, reference, face_count=12, confidence=0.9), face_count=12, dark_ratio=0.0, audience_like=True, stage_context=False),
        FaceSample(1.0, clear_candidate(1.0, reference, face_count=8, confidence=0.88), face_count=8, dark_ratio=0.0, audience_like=True, stage_context=False),
    ]

    intervals = build_insightface_subject_visibility_intervals(
        samples,
        reference,
        sample_step=1.0,
        duration=5.0,
        confidence=0.9,
        identity_on_threshold=0.42,
        identity_off_threshold=0.38,
    )

    assert intervals == [Interval(0.0, 2.0, 0.89)]

def test_select_main_face_candidates_keeps_dominant_cluster_without_mutating_candidates() -> None:
    candidates = [
        clear_candidate(0.0, [1.0, 0.0]),
        clear_candidate(2.0, [0.98, 0.02], area=0.19),
        clear_candidate(4.0, [0.0, 1.0], area=0.02, confidence=0.9),
    ]

    selected = select_main_face_candidates(candidates)

    assert selected == candidates[:2]
    assert all(candidate.cluster_id is None for candidate in candidates)


def test_identity_baseline_candidate_allows_clear_context_faces() -> None:
    assert is_identity_baseline_candidate(
        clear_candidate(0.0, [1.0, 0.0])
    )
    assert is_identity_baseline_candidate(
        clear_candidate(0.0, [1.0, 0.0], face_count=2)
    )
    assert not is_identity_baseline_candidate(
        clear_candidate(0.0, [1.0, 0.0], face_count=5)
    )
    assert not is_identity_baseline_candidate(
        clear_candidate(0.0, [], face_count=1)
    )
    assert not is_identity_baseline_candidate(
        clear_candidate(0.0, [1.0, 0.0], area=0.001, face_edge_px=36)
    )
    assert not is_identity_baseline_candidate(
        clear_candidate(0.0, [1.0, 0.0], center_score=0.05)
    )
    assert not is_identity_baseline_candidate(
        clear_candidate(0.0, [1.0, 0.0], blur_score=1.0)
    )


def test_output_visibility_accepts_clear_smaller_face_not_projection_sized_face() -> None:
    """A clear speaker face can be small, but not projection-screen tiny."""

    assert not is_output_visibility_candidate(
        clear_candidate(0.0, [1.0, 0.0], area=0.001, face_edge_px=36)
    )
    assert is_output_visibility_candidate(
        clear_candidate(0.0, [1.0, 0.0], area=0.006, face_edge_px=80)
    )
    assert is_output_visibility_candidate(
        clear_candidate(0.0, [1.0, 0.0], area=0.03, face_edge_px=130)
    )


def test_select_main_face_candidates_discards_multi_face_audience_frames() -> None:
    speaker = clear_candidate(0.0, [1.0, 0.0])
    audience_wide = clear_candidate(2.0, [0.0, 1.0], area=0.40, confidence=0.9, face_count=5)

    selected = select_main_face_candidates([audience_wide, speaker])

    assert selected == [speaker]


def test_diverse_still_candidates_prefer_timeline_spread_over_adjacent_duplicates() -> None:
    adjacent_best = clear_candidate(101.0, [1.0, 0.0], confidence=0.99, area=0.30)
    adjacent_duplicate = clear_candidate(102.0, [1.0, 0.0], confidence=0.98, area=0.29)
    spread_candidates = [
        clear_candidate(0.0, [1.0, 0.0], confidence=0.8, area=0.20),
        adjacent_best,
        adjacent_duplicate,
        clear_candidate(200.0, [1.0, 0.0], confidence=0.8, area=0.20),
        clear_candidate(300.0, [1.0, 0.0], confidence=0.8, area=0.20),
    ]

    selected = select_diverse_still_candidates(spread_candidates, count=4)

    assert [candidate.timestamp for candidate in selected] == [0.0, 101.0, 200.0, 300.0]
    assert adjacent_duplicate not in selected


def test_gray_for_haar_detection_downscales_large_frames() -> None:
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    frame = numpy.zeros((720, 1280, 3), dtype=numpy.uint8)

    gray, scale = gray_for_haar_detection(cv2, frame, max_width=640)

    assert gray.shape == (360, 640)
    assert scale == 2.0


def test_audience_like_frame_rejects_crowd_cutaways() -> None:
    assert is_audience_like_frame(face_count=6, dark_ratio=0.42) is True
    assert is_audience_like_frame(face_count=7, dark_ratio=0.64) is True
    assert is_audience_like_frame(face_count=19, dark_ratio=0.41) is True
    assert is_audience_like_frame(face_count=2, dark_ratio=0.74) is False


def test_stage_context_accepts_dark_speaker_stage_without_frontal_face() -> None:
    assert is_stage_context_frame(face_count=0, dark_ratio=0.74) is True
    assert is_stage_context_frame(face_count=2, dark_ratio=0.74) is True
    assert is_stage_context_frame(face_count=7, dark_ratio=0.74) is False
    assert is_stage_context_frame(face_count=6, dark_ratio=0.42) is False



def test_save_best_stills_writes_jpeg_bytes_to_unicode_paths(tmp_path: Path) -> None:
    output_dir = tmp_path / "Speaker_H" / "identity_stills"
    candidate = clear_candidate(12.0, [1.0, 0.0], area=0.03, face_edge_px=130)

    artifacts = save_best_stills(FakeCv2JpegWriter(), [candidate], output_dir, 1)

    assert len(artifacts) == 1
    assert artifacts[0].read_bytes() == b"jpeg"
def test_intervals_from_sample_times_bridges_stage_samples_without_crossing_cutaways() -> None:
    intervals = intervals_from_sample_times(
        [0.0, 2.0, 4.0, 16.0, 18.0],
        sample_step=2.0,
        duration=30.0,
        confidence=0.7,
        gap_seconds=3.0,
    )

    assert intervals == [Interval(0.0, 6.0, 0.7), Interval(16.0, 20.0, 0.7)]


def test_subject_visibility_requires_target_face_and_breaks_on_audience() -> None:
    speaker = clear_candidate(0.0, [1.0, 0.0], confidence=0.9)
    other_person = clear_candidate(4.0, [0.0, 1.0], confidence=0.9)
    samples = [
        FaceSample(0.0, speaker, face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
        FaceSample(1.0, None, face_count=0, dark_ratio=0.78, audience_like=False, stage_context=True),
        FaceSample(2.0, None, face_count=7, dark_ratio=0.74, audience_like=True, stage_context=False),
        FaceSample(3.0, None, face_count=0, dark_ratio=0.78, audience_like=False, stage_context=True),
        FaceSample(4.0, other_person, face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
    ]

    intervals = build_subject_visibility_intervals(
        samples,
        [1.0, 0.0],
        sample_step=1.0,
        duration=10.0,
        confidence=0.7,
        identity_on_threshold=0.42,
        identity_off_threshold=0.38,
    )

    assert intervals == [Interval(0.0, 1.0, 0.9)]



def test_subject_visibility_accepts_non_audience_multi_face_target_samples() -> None:
    speaker = clear_candidate(0.0, [1.0, 0.0], confidence=0.9)
    multi_face_speaker = clear_candidate(1.0, [1.0, 0.0], confidence=0.9, face_count=2)
    samples = [
        FaceSample(0.0, speaker, face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
        FaceSample(1.0, multi_face_speaker, face_count=2, dark_ratio=0.72, audience_like=False, stage_context=False),
    ]

    intervals = build_subject_visibility_intervals(
        samples,
        [1.0, 0.0],
        sample_step=1.0,
        duration=5.0,
        confidence=0.7,
        identity_on_threshold=0.42,
        identity_off_threshold=0.38,
    )

    assert intervals == [Interval(0.0, 2.0, 0.9)]
def test_subject_visibility_rejects_tiny_single_face_wide_shots() -> None:
    speaker = clear_candidate(0.0, [1.0, 0.0], confidence=0.9)
    tiny_face = clear_candidate(1.0, [1.0, 0.0], confidence=0.9, area=0.001, face_edge_px=30)
    samples = [
        FaceSample(0.0, speaker, face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
        FaceSample(1.0, tiny_face, face_count=1, dark_ratio=0.50, audience_like=False, stage_context=False),
    ]

    intervals = build_subject_visibility_intervals(
        samples,
        [1.0, 0.0],
        sample_step=1.0,
        duration=10.0,
        confidence=0.7,
        identity_on_threshold=0.42,
        identity_off_threshold=0.38,
    )

    assert intervals == [Interval(0.0, 1.0, 0.9)]


def test_subject_visibility_rejects_projection_screen_sized_identity_match() -> None:
    speaker = clear_candidate(0.0, [1.0, 0.0], confidence=0.9, area=0.03, face_edge_px=130)
    projection_face = clear_candidate(1.0, [1.0, 0.0], confidence=0.9, area=0.001, face_edge_px=36)
    samples = [
        FaceSample(0.0, speaker, face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
        FaceSample(1.0, projection_face, face_count=1, dark_ratio=0.50, audience_like=False, stage_context=False),
    ]

    intervals = build_subject_visibility_intervals(
        samples,
        [1.0, 0.0],
        sample_step=1.0,
        duration=10.0,
        confidence=0.7,
        identity_on_threshold=0.42,
        identity_off_threshold=0.38,
    )

    assert intervals == [Interval(0.0, 1.0, 0.9)]


def test_subject_visibility_does_not_merge_across_rejected_samples() -> None:
    """One no-face/cutaway sample must split otherwise matching speaker clips."""

    first_speaker = clear_candidate(0.0, [1.0, 0.0], confidence=0.9)
    second_speaker = clear_candidate(2.0, [1.0, 0.0], confidence=0.9)
    samples = [
        FaceSample(0.0, first_speaker, face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
        FaceSample(1.0, None, face_count=0, dark_ratio=0.50, audience_like=False, stage_context=False),
        FaceSample(2.0, second_speaker, face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
    ]

    intervals = build_subject_visibility_intervals(
        samples,
        [1.0, 0.0],
        sample_step=1.0,
        duration=10.0,
        confidence=0.7,
        identity_on_threshold=0.42,
        identity_off_threshold=0.38,
    )

    assert intervals == [Interval(0.0, 1.0, 0.9), Interval(2.0, 3.0, 0.9)]




def test_first_pass_subject_visibility_can_bridge_one_detector_miss_for_validation() -> None:
    """Candidate generation may bridge one missed sample; second-pass validation stays strict."""

    first_speaker = clear_candidate(0.0, [1.0, 0.0], confidence=0.9)
    second_speaker = clear_candidate(2.0, [1.0, 0.0], confidence=0.9)
    samples = [
        FaceSample(0.0, first_speaker, face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
        FaceSample(1.0, None, face_count=0, dark_ratio=0.50, audience_like=False, stage_context=False),
        FaceSample(2.0, second_speaker, face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
    ]

    intervals = build_subject_visibility_intervals(
        samples,
        [1.0, 0.0],
        sample_step=1.0,
        duration=5.0,
        confidence=0.7,
        identity_on_threshold=0.42,
        identity_off_threshold=0.38,
        merge_gap_seconds=first_pass_face_interval_gap(1.0),
    )

    assert intervals == [Interval(0.0, 3.0, 0.9)]
def test_validated_subject_visibility_splits_bad_sample_inside_candidate_span() -> None:
    """Second-pass validation must split a candidate clip at audience/cutaway samples."""

    samples = [
        FaceSample(0.0, clear_candidate(0.0, [1.0, 0.0], confidence=0.9), face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
        FaceSample(1.0, clear_candidate(1.0, [1.0, 0.0], confidence=0.9), face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
        FaceSample(2.0, None, face_count=8, dark_ratio=0.40, audience_like=True, stage_context=False),
        FaceSample(3.0, clear_candidate(3.0, [1.0, 0.0], confidence=0.9), face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
        FaceSample(4.0, clear_candidate(4.0, [1.0, 0.0], confidence=0.9), face_count=1, dark_ratio=0.72, audience_like=False, stage_context=True),
    ]

    intervals = build_validated_subject_visibility_intervals(
        samples,
        [1.0, 0.0],
        [Interval(0.0, 5.0, 0.9)],
        sample_step=1.0,
        duration=5.0,
        confidence=0.7,
        identity_on_threshold=0.42,
        identity_off_threshold=0.38,
    )

    assert intervals == [Interval(0.0, 2.0, 0.9), Interval(3.0, 5.0, 0.9)]


def test_identity_baseline_sampling_caps_large_candidate_sets() -> None:
    candidates = [clear_candidate(float(index), [1.0, 0.0]) for index in range(1000)]

    sampled = sample_identity_baseline_candidates(candidates, max_count=600)

    assert len(sampled) == 600
    assert sampled == sorted(sampled, key=lambda item: item.timestamp)
    assert sampled[0].timestamp == 0.0
    assert sampled[-1].timestamp > 990.0

def test_dominant_baseline_returns_empty_when_no_identity_reaches_sixty_percent() -> None:
    candidates = [
        clear_candidate(0.0, [1.0, 0.0]),
        clear_candidate(1.0, [0.98, 0.02]),
        clear_candidate(2.0, [0.0, 1.0]),
        clear_candidate(3.0, [0.02, 0.98]),
        clear_candidate(4.0, [0.7, 0.7]),
    ]

    selected = select_dominant_baseline_candidates(
        candidates,
        similarity_threshold=0.95,
        batch_size=10,
        dominance_ratio=0.60,
    )

    assert selected == []

def test_dominant_baseline_accepts_recurring_mixed_stage_identity() -> None:
    candidates = [clear_candidate(float(index), [1.0, 0.0]) for index in range(12)]
    candidates.extend(clear_candidate(float(index + 12), [0.0, 1.0]) for index in range(24))

    selected = select_dominant_baseline_candidates(
        candidates,
        similarity_threshold=0.95,
        batch_size=10,
        dominance_ratio=0.60,
    )

    assert len(selected) == 24
