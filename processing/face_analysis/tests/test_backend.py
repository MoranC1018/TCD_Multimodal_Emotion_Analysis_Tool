from __future__ import annotations

import builtins
from pathlib import Path

import pandas as pd

from processing.face_analysis import backend
from processing.face_analysis.backend import PyFeatBackend
from processing.face_analysis.config import FaceProcessingConfig
from processing.face_analysis.media import VideoMetadata
from processing.face_analysis.model_provenance import (
    DETECTOR_V2_WEIGHT_SPECS,
    MODEL_WEIGHT_PROVENANCE_VERSION,
    model_weight_set_fingerprint,
)
from processing.face_analysis.pipeline import _analysis_fingerprint


class FakeDetector:
    info = {
        "face_model": "test-face",
        "multitask_model": "test-multitask",
        "identity_model": None,
    }

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def detect(self, inputs: str, **kwargs: object) -> pd.DataFrame:
        self.calls.append((inputs, kwargs))
        return pd.DataFrame([{"frame": 0, "FaceScore": 0.99}])


def complete_weights(seed: str = "a") -> dict[str, object]:
    components = {
        spec.component: {
            "component": spec.component,
            "source": "huggingface-cache",
            "status": "cached",
            "repo_id": spec.repo_id,
            "filename": spec.filenames[0],
            "requested_revision": "main",
            "snapshot_commit": seed * 40,
            "local_path": f"/machine/cache/{spec.filenames[0]}",
            "size_bytes": 10,
            "sha256": seed * 64,
        }
        for spec in DETECTOR_V2_WEIGHT_SPECS
    }
    payload: dict[str, object] = {
        "schema_version": MODEL_WEIGHT_PROVENANCE_VERSION,
        "status": "ready",
        "components": components,
    }
    payload["fingerprint"] = model_weight_set_fingerprint(payload)
    return payload


def test_pyfeat_detector_is_lazily_reused_per_resolved_device(monkeypatch) -> None:
    created: list[str] = []
    detectors: list[FakeDetector] = []

    def factory(device: str) -> FakeDetector:
        created.append(device)
        detector = FakeDetector()
        detectors.append(detector)
        return detector

    monkeypatch.setattr(backend, "configure_ffmpeg_shared_libraries", lambda: None)
    monkeypatch.setattr(
        backend, "resolve_detector_v2_weights", lambda _cache: complete_weights()
    )
    engine = PyFeatBackend(
        detector_factory=factory,
        model_components=FakeDetector.info,
    )
    config = FaceProcessingConfig(sample_fps=2.0, batch_size=4, device="cpu")
    metadata = VideoMetadata("video.mp4", "abc", 1, 1.0, 10.0, 10, 320, 240)

    assert created == []
    before = engine.provenance(config)
    fingerprint_before = _analysis_fingerprint(config, before)
    engine.analyse(Path("first.mp4"), metadata, config)
    engine.analyse(Path("second.mp4"), metadata, config)

    assert created == ["cpu"]
    assert len(detectors[0].calls) == 2
    assert detectors[0].calls[0][1]["skip_frames"] == 5
    provenance = engine.provenance(config)
    assert provenance == before
    assert _analysis_fingerprint(config, provenance) == fingerprint_before
    assert provenance["resolved_device"] == "cpu"
    assert provenance["models"]["face_model"] == "test-face"


def test_all_weight_provenance_is_refreshed_after_detector_construction(
    monkeypatch,
) -> None:
    before = complete_weights("a")
    before["status"] = "incomplete"
    before["components"]["arcface_r50"]["status"] = "not-cached"
    before["fingerprint"] = model_weight_set_fingerprint(before)
    after = complete_weights("b")
    resolutions = iter((before, after))
    monkeypatch.setattr(
        backend, "resolve_detector_v2_weights", lambda _cache: next(resolutions)
    )
    monkeypatch.setattr(backend, "configure_ffmpeg_shared_libraries", lambda: None)
    engine = PyFeatBackend(
        detector_factory=lambda _device: FakeDetector(),
        model_components=FakeDetector.info,
    )
    config = FaceProcessingConfig(device="cpu")
    metadata = VideoMetadata("video.mp4", "abc", 1, 1.0, 10.0, 10, 320, 240)

    assert engine.provenance(config)["weights"]["status"] == "incomplete"
    engine.analyse(Path("video.mp4"), metadata, config)

    recorded = engine.provenance(config)["weights"]
    assert recorded == after


def test_ensure_ready_constructs_detector_once(monkeypatch) -> None:
    created: list[str] = []
    monkeypatch.setattr(
        backend, "resolve_detector_v2_weights", lambda _cache: complete_weights()
    )
    engine = PyFeatBackend(
        detector_factory=lambda device: created.append(device) or FakeDetector(),
        model_components=FakeDetector.info,
    )
    config = FaceProcessingConfig(device="cpu")

    first = engine.ensure_ready(config)
    second = engine.ensure_ready(config)

    assert created == ["cpu"]
    assert first == second


def test_nested_pyfeat_dependency_error_is_not_reported_as_missing_pyfeat(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        backend, "resolve_detector_v2_weights", lambda _cache: complete_weights()
    )
    monkeypatch.setattr(backend, "model_weights_ready", lambda _weights: True)
    original_import = builtins.__import__

    def import_with_missing_runtime_dependency(name, *args, **kwargs):
        if name == "feat":
            raise ModuleNotFoundError("No module named 'pwd'", name="pwd")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_with_missing_runtime_dependency)
    engine = PyFeatBackend()

    try:
        engine.ensure_ready(FaceProcessingConfig(device="cpu"))
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("A missing nested Py-Feat dependency must fail readiness")

    assert "runtime dependency is missing (pwd)" in message
    assert "Py-Feat is not installed" not in message
