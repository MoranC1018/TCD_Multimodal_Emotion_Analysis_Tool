from __future__ import annotations

import sys
import types
import weakref
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from processing.face_analysis import health


def test_prepare_models_constructs_with_network_enabled_and_validates_weights(
    monkeypatch,
) -> None:
    weights = {"schema_version": "test", "status": "ready", "components": {}}
    calls: list[str] = []

    class FakeEngine:
        def provenance(self, config):
            calls.append(f"inspect:{config.device}")
            return {"resolved_device": "cpu", "weights": {"status": "incomplete"}}

        def ensure_ready(self, config):
            calls.append(f"construct:{config.device}")
            return {"resolved_device": "cpu", "weights": weights}

    monkeypatch.setattr(
        health, "configure_ffmpeg_shared_libraries", lambda: Path("ffmpeg")
    )
    monkeypatch.setattr(health, "PyFeatBackend", FakeEngine)
    monkeypatch.setattr(
        health,
        "model_weights_ready",
        lambda value: value.get("status") == "ready",
    )
    monkeypatch.setattr(health, "_release_cuda_cache", lambda: None)

    result = health.prepare_detector_models("cpu")

    assert result.ready is True
    assert result.device == "cpu"
    assert result.model_weights == weights
    assert calls == ["inspect:cpu", "construct:cpu"]


def test_prepare_models_rejects_incomplete_final_provenance(monkeypatch) -> None:
    incomplete = {"status": "incomplete"}

    class FakeEngine:
        def provenance(self, _config):
            return {"resolved_device": "cpu", "weights": incomplete}

        def ensure_ready(self, _config):
            return {"resolved_device": "cpu", "weights": incomplete}

    monkeypatch.setattr(
        health, "configure_ffmpeg_shared_libraries", lambda: Path("ffmpeg")
    )
    monkeypatch.setattr(health, "PyFeatBackend", FakeEngine)
    monkeypatch.setattr(health, "model_weights_ready", lambda _value: False)
    monkeypatch.setattr(
        health,
        "unavailable_model_components",
        lambda _value: ["arcface_r50 (not-cached)"],
    )
    monkeypatch.setattr(health, "_release_cuda_cache", lambda: None)

    result = health.prepare_detector_models("cpu")

    assert result.ready is False
    assert result.model_weights == incomplete
    assert "arcface_r50 (not-cached)" in result.detail


def test_detector_smoke_constructs_backend_from_verified_local_weights(
    monkeypatch,
) -> None:
    weights = {"schema_version": "test", "components": {}}
    calls: list[str] = []

    class FakeEngine:
        def provenance(self, config):
            calls.append(f"inspect:{config.device}")
            return {"weights": weights}

        def ensure_ready(self, config):
            calls.append(f"construct:{config.device}")
            return {"weights": weights}

    monkeypatch.setattr(health, "PyFeatBackend", FakeEngine)
    monkeypatch.setattr(health, "model_weights_ready", lambda value: value is weights)
    monkeypatch.setattr(health, "_huggingface_cache_only", nullcontext)
    monkeypatch.setattr(health, "_release_cuda_cache", lambda: None)

    assert health._pyfeat_detector_smoke("cpu") == weights
    assert calls == ["inspect:cpu", "construct:cpu"]


def test_detector_smoke_reports_missing_models_without_constructing(
    monkeypatch,
) -> None:
    calls: list[str] = []

    class FakeEngine:
        def provenance(self, _config):
            return {"weights": {"status": "incomplete"}}

        def ensure_ready(self, _config):
            calls.append("constructed")
            raise AssertionError("must not construct with missing local weights")

    monkeypatch.setattr(health, "PyFeatBackend", FakeEngine)
    monkeypatch.setattr(health, "model_weights_ready", lambda _value: False)
    monkeypatch.setattr(
        health,
        "unavailable_model_components",
        lambda _value: ["arcface_r50 (not-cached)"],
    )

    try:
        health._pyfeat_detector_smoke("cpu")
    except RuntimeError as exc:
        assert "arcface_r50 (not-cached)" in str(exc)
    else:  # pragma: no cover - assertion aid
        raise AssertionError("missing models should fail readiness")
    assert calls == []


def test_readiness_requires_detector_construction_not_only_pyfeat_import(
    monkeypatch,
) -> None:
    monkeypatch.setattr(health, "configure_ffmpeg_shared_libraries", lambda: Path("ffmpeg"))
    monkeypatch.setattr(health, "resolve_media_binary", lambda *_args, **_kwargs: Path("ffprobe.exe"))
    monkeypatch.setattr(health, "_torch_device", lambda _requested="auto": "cpu")
    monkeypatch.setattr(health, "_torchcodec_decode_smoke", lambda: 8)
    monkeypatch.setattr(health, "_pyfeat_version", lambda: "2.1.1")
    monkeypatch.setattr(
        health,
        "_pyfeat_detector_smoke",
        lambda _device: (_ for _ in ()).throw(RuntimeError("weights missing")),
    )

    result = health.check_readiness()

    assert result.pyfeat is True
    assert result.detector is False
    assert result.ready is False
    assert "weights missing" in result.detail


def test_readiness_requires_pyarrow_even_when_detector_and_backend_are_ready(
    monkeypatch,
) -> None:
    monkeypatch.setattr(health, "configure_ffmpeg_shared_libraries", lambda: Path("ffmpeg"))
    monkeypatch.setattr(health, "resolve_media_binary", lambda *_args, **_kwargs: Path("ffprobe.exe"))
    monkeypatch.setattr(health, "_torch_device", lambda _requested="auto": "cpu")
    monkeypatch.setattr(health, "_torchcodec_decode_smoke", lambda: 8)
    monkeypatch.setattr(health, "_pyfeat_version", lambda: "2.1.1")
    monkeypatch.setattr(health, "_pyfeat_detector_smoke", lambda _device: {"status": "ready"})
    monkeypatch.setattr(
        health,
        "_pyarrow_version",
        lambda: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'pyarrow'")),
        raising=False,
    )

    result = health.check_readiness()

    assert result.pyarrow is False
    assert result.ready is False
    assert "PyArrow" in result.detail


def test_torchcodec_smoke_releases_decoder_before_temp_cleanup(monkeypatch, tmp_path) -> None:
    decoder_reference = None

    class TemporaryDirectoryGuard:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self) -> str:
            return str(tmp_path)

        def __exit__(self, *_args) -> None:
            assert decoder_reference is not None
            assert decoder_reference() is None

    class Frame:
        def numel(self) -> int:
            return 1

    class Decoder:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal decoder_reference
            decoder_reference = weakref.ref(self)

        def __len__(self) -> int:
            return 1

        def __getitem__(self, _index: int) -> Frame:
            return Frame()

    def fake_ffmpeg(command, **_kwargs):
        (tmp_path / "smoke.mp4").write_bytes(b"video")
        return SimpleNamespace(returncode=0, stderr="", stdout="", command=command)

    core = SimpleNamespace(
        ffmpeg_major_version=8,
        get_ffmpeg_library_versions=lambda: {"libavcodec": (62, 0, 0)},
    )
    torchcodec = types.ModuleType("torchcodec")
    torchcodec._core = core
    decoders = types.ModuleType("torchcodec.decoders")
    decoders.VideoDecoder = Decoder
    monkeypatch.setitem(sys.modules, "torchcodec", torchcodec)
    monkeypatch.setitem(sys.modules, "torchcodec.decoders", decoders)
    monkeypatch.setattr(health.tempfile, "TemporaryDirectory", TemporaryDirectoryGuard)
    monkeypatch.setattr(health, "resolve_media_binary", lambda *_args, **_kwargs: Path("ffmpeg.exe"))
    monkeypatch.setattr(health.subprocess, "run", fake_ffmpeg)

    assert health._torchcodec_decode_smoke() == 8
