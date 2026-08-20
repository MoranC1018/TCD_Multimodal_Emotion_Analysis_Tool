from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from processing.face_analysis import pipeline
from processing.face_analysis.config import FaceProcessingConfig
from processing.face_analysis.media import VideoMetadata
from processing.face_analysis.model_provenance import (
    DETECTOR_V2_WEIGHT_SPECS,
    MODEL_WEIGHT_PROVENANCE_VERSION,
)
from processing.face_analysis.tests.helpers import complete_detection_row
from processing.io_utils import exclusive_process_lock


PYARROW_AVAILABLE = importlib.util.find_spec("pyarrow") is not None
requires_pyarrow = pytest.mark.skipif(
    not PYARROW_AVAILABLE,
    reason="PyArrow is an optional Face runtime dependency",
)


class FakeBackend:
    name = "fake"
    version = "1.2.3"

    def __init__(
        self,
        *,
        error: Exception | None = None,
        weights: dict[str, object] | None = None,
    ) -> None:
        self.calls = 0
        self.error = error
        self.weights = weights

    def analyse(self, *_args) -> pd.DataFrame:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return pd.DataFrame([complete_detection_row()])

    def provenance(self, config: FaceProcessingConfig) -> dict[str, object]:
        provenance = {
            "name": self.name,
            "version": self.version,
            "resolved_device": config.device,
            "models": {"test_model": "fixed"},
            "package_versions": {},
        }
        if self.weights is not None:
            provenance["weights"] = self.weights
        return provenance


def _source_and_metadata(tmp_path: Path) -> tuple[Path, VideoMetadata]:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    return video, VideoMetadata(
        str(video), "abcdef1234567890", 5, 1.0, 2.0, 2, 640, 360
    )


def test_windows_runtime_is_configured_before_video_discovery(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        pipeline,
        "configure_ffmpeg_shared_libraries",
        lambda: calls.append("runtime"),
    )

    def discover(_source: Path, *, recursive: bool) -> list[Path]:
        assert calls == ["runtime"]
        assert recursive is True
        raise ValueError("stop after proving call order")

    monkeypatch.setattr(pipeline, "discover_videos", discover)

    with pytest.raises(ValueError, match="call order"):
        pipeline.process_face_input(tmp_path, tmp_path / "out")


@requires_pyarrow
def test_directory_run_mirrors_input_and_writes_verified_index(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "Videos"
    video = source / "UK" / "Test Speaker" / "001_UK_Test_Speaker_20260101.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    destination = tmp_path / "face-output"
    metadata = VideoMetadata(str(video), "abcdef1234567890", 5, 1.0, 2.0, 2, 640, 360)
    backend = FakeBackend()
    progress: list[tuple[int, int, str, str]] = []

    monkeypatch.setattr(pipeline, "probe_video", lambda _video: metadata)
    result = pipeline.process_face_input(
        source,
        destination,
        config=FaceProcessingConfig(sample_fps=1.0, batch_size=1, device="cpu"),
        backend=backend,
        run_id="face-test-run",
        progress_callback=lambda *item: progress.append(item),
    )

    expected = destination / "UK" / "Test Speaker" / "001_UK_Test_Speaker_20260101__abcdef123456"
    assert (expected / "face_core.csv").is_file()
    assert (expected / "face_features.parquet").is_file()
    with result.run_index.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["input_relative"] == str(Path("UK/Test Speaker/001_UK_Test_Speaker_20260101.mp4"))
    assert rows[0]["input_sha256"] == metadata.sha256
    assert rows[0]["output_relative"] == str(Path("UK/Test Speaker/001_UK_Test_Speaker_20260101__abcdef123456"))
    assert rows[0]["status"] == "completed"
    assert progress == [
        (1, 1, "analysing", str(Path("UK/Test Speaker/001_UK_Test_Speaker_20260101.mp4"))),
        (1, 1, "completed", str(Path("UK/Test Speaker/001_UK_Test_Speaker_20260101.mp4"))),
    ]

    manifest = json.loads(result.run_manifest.read_text(encoding="utf-8"))
    assert manifest["run_id"] == "face-test-run"
    assert manifest["status"] == "completed"
    assert manifest["summary"] == {
        "discovered_videos": 1,
        "processed": 1,
        "skipped": 0,
        "failed": 0,
    }
    video_manifest = json.loads((expected / "video_manifest.json").read_text(encoding="utf-8"))
    assert video_manifest["schema_version"] == pipeline.VIDEO_MANIFEST_SCHEMA_VERSION
    assert video_manifest["backend"]["resolved_device"] == "cpu"
    assert video_manifest["sampling"]["frame_step"] == 2
    assert len(video_manifest["analysis_fingerprint"]) == 64
    for artifact in video_manifest["outputs"].values():
        assert artifact["size_bytes"] > 0
        assert artifact["rows"] >= 1
        assert artifact["columns"] >= 8
        assert len(artifact["sha256"]) == 64
        assert len(artifact["schema_fingerprint"]) == 64


@requires_pyarrow
def test_valid_outputs_are_reused_but_analysis_change_is_not(monkeypatch, tmp_path: Path) -> None:
    video, metadata = _source_and_metadata(tmp_path)
    destination = tmp_path / "output"
    backend = FakeBackend()
    monkeypatch.setattr(pipeline, "probe_video", lambda _video: metadata)

    first = pipeline.process_face_input(
        video,
        destination,
        config=FaceProcessingConfig(sample_fps=1.0, batch_size=1, device="cpu"),
        backend=backend,
    )
    second = pipeline.process_face_input(
        video,
        destination,
        config=FaceProcessingConfig(sample_fps=1.0, batch_size=1, device="cpu"),
        backend=backend,
    )
    changed = pipeline.process_face_input(
        video,
        destination,
        config=FaceProcessingConfig(sample_fps=2.0, batch_size=1, device="cpu"),
        backend=backend,
    )

    assert (first.processed, first.skipped) == (1, 0)
    assert (second.processed, second.skipped) == (0, 1)
    assert (changed.processed, changed.skipped) == (1, 0)
    assert backend.calls == 2


@requires_pyarrow
def test_corrupt_artifact_and_manifest_are_recomputed(monkeypatch, tmp_path: Path) -> None:
    video, metadata = _source_and_metadata(tmp_path)
    destination = tmp_path / "output"
    backend = FakeBackend()
    config = FaceProcessingConfig(sample_fps=1.0, batch_size=1, device="cpu")
    monkeypatch.setattr(pipeline, "probe_video", lambda _video: metadata)

    pipeline.process_face_input(video, destination, config=config, backend=backend)
    video_dir = destination / "video__abcdef123456"
    (video_dir / "face_core.csv").write_text("broken\n", encoding="utf-8")
    repaired = pipeline.process_face_input(video, destination, config=config, backend=backend)
    assert repaired.processed == 1
    assert backend.calls == 2

    (video_dir / "face_core.csv").write_bytes(b"")
    repaired_empty = pipeline.process_face_input(
        video, destination, config=config, backend=backend
    )
    assert repaired_empty.processed == 1
    assert backend.calls == 3

    (video_dir / "face_features.parquet").write_bytes(b"PAR1")
    repaired_parquet = pipeline.process_face_input(
        video, destination, config=config, backend=backend
    )
    assert repaired_parquet.processed == 1
    assert backend.calls == 4

    (video_dir / "video_manifest.json").write_text("{", encoding="utf-8")
    repaired_again = pipeline.process_face_input(video, destination, config=config, backend=backend)
    assert repaired_again.processed == 1
    assert backend.calls == 5


@requires_pyarrow
def test_old_manifest_schema_is_recomputed(monkeypatch, tmp_path: Path) -> None:
    video, metadata = _source_and_metadata(tmp_path)
    destination = tmp_path / "output"
    backend = FakeBackend()
    config = FaceProcessingConfig(sample_fps=1.0, batch_size=1, device="cpu")
    monkeypatch.setattr(pipeline, "probe_video", lambda _video: metadata)

    pipeline.process_face_input(video, destination, config=config, backend=backend)
    manifest_path = destination / "video__abcdef123456" / "video_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "1.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = pipeline.process_face_input(video, destination, config=config, backend=backend)
    assert result.processed == 1
    assert backend.calls == 2


@requires_pyarrow
def test_manifest_missing_one_detector_weight_is_recomputed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    video, metadata = _source_and_metadata(tmp_path)
    destination = tmp_path / "output"
    components = {
        spec.component: {
            "source": "huggingface-cache",
            "repo_id": spec.repo_id,
            "filename": spec.filenames[0],
            "requested_revision": "main",
            "snapshot_commit": "a" * 40,
            "size_bytes": 10,
            "sha256": "b" * 64,
        }
        for spec in DETECTOR_V2_WEIGHT_SPECS
    }
    backend = FakeBackend(
        weights={
            "schema_version": MODEL_WEIGHT_PROVENANCE_VERSION,
            "components": components,
        }
    )
    config = FaceProcessingConfig(sample_fps=1.0, batch_size=1, device="cpu")
    monkeypatch.setattr(pipeline, "probe_video", lambda _video: metadata)

    pipeline.process_face_input(video, destination, config=config, backend=backend)
    manifest_path = destination / "video__abcdef123456" / "video_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["backend"]["weights"]["components"]["arcface_r50"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = pipeline.process_face_input(
        video, destination, config=config, backend=backend
    )

    assert result.processed == 1
    assert backend.calls == 2


@requires_pyarrow
@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("backend", "resolved_device", "cuda"),
        ("config", "sample_fps", 99.0),
        ("sampling", "frame_step", 99),
        ("quality", "detected_face_rows", 99),
    ],
)
def test_internally_inconsistent_manifest_is_recomputed(
    monkeypatch,
    tmp_path: Path,
    section: str,
    key: str,
    value: object,
) -> None:
    video, metadata = _source_and_metadata(tmp_path)
    destination = tmp_path / "output"
    backend = FakeBackend()
    config = FaceProcessingConfig(sample_fps=1.0, batch_size=1, device="cpu")
    monkeypatch.setattr(pipeline, "probe_video", lambda _video: metadata)

    pipeline.process_face_input(video, destination, config=config, backend=backend)
    manifest_path = destination / "video__abcdef123456" / "video_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[section][key] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = pipeline.process_face_input(video, destination, config=config, backend=backend)
    assert result.processed == 1
    assert backend.calls == 2


def test_failure_records_stage_and_structured_error(monkeypatch, tmp_path: Path) -> None:
    video, metadata = _source_and_metadata(tmp_path)
    destination = tmp_path / "output"
    backend = FakeBackend(error=ValueError("model failed"))
    monkeypatch.setattr(pipeline, "probe_video", lambda _video: metadata)

    result = pipeline.process_face_input(
        video,
        destination,
        config=FaceProcessingConfig(sample_fps=1.0, batch_size=1, device="cpu"),
        backend=backend,
    )

    assert result.failed == 1
    payload = json.loads(result.run_manifest.read_text(encoding="utf-8"))
    failure = payload["videos"][0]
    assert failure["error_stage"] == "analyse"
    assert failure["error_type"] == "ValueError"
    assert failure["error_message"] == "model failed"
    with result.run_index.open(encoding="utf-8", newline="") as handle:
        index_row = next(csv.DictReader(handle))
    assert index_row["error_stage"] == "analyse"
    assert index_row["error_message"] == "model failed"


def test_keyboard_interrupt_writes_cancelled_run_manifest_before_propagating(
    monkeypatch, tmp_path: Path
) -> None:
    video, metadata = _source_and_metadata(tmp_path)
    destination = tmp_path / "output"

    class InterruptingBackend(FakeBackend):
        def analyse(self, *_args) -> pd.DataFrame:
            raise KeyboardInterrupt

    monkeypatch.setattr(pipeline, "probe_video", lambda _video: metadata)

    with pytest.raises(KeyboardInterrupt):
        pipeline.process_face_input(
            video,
            destination,
            config=FaceProcessingConfig(sample_fps=1.0, batch_size=1, device="cpu"),
            backend=InterruptingBackend(),
            run_id="cancelled-face-run",
        )

    payload = json.loads((destination / "run_manifest.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "cancelled-face-run"
    assert payload["status"] == "cancelled"
    assert payload["summary"]["interrupted"] == 1
    assert payload["videos"][0]["status"] == "interrupted"
    assert payload["videos"][0]["error_stage"] == "analyse"
    with (destination / "run_index.csv").open(encoding="utf-8", newline="") as handle:
        assert next(csv.DictReader(handle))["status"] == "interrupted"


def test_run_manifest_is_published_after_run_index(monkeypatch, tmp_path: Path) -> None:
    video, metadata = _source_and_metadata(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "probe_video", lambda _video: metadata)
    monkeypatch.setattr(pipeline, "_write_run_index", lambda *_args: calls.append("index"))
    monkeypatch.setattr(pipeline, "atomic_write_json", lambda *_args: calls.append("manifest"))

    pipeline.process_face_input(
        video,
        tmp_path / "output",
        config=FaceProcessingConfig(sample_fps=1.0, batch_size=1, device="cpu"),
        backend=FakeBackend(),
    )

    assert calls == ["index", "manifest"]


def test_live_face_run_lock_prevents_shared_manifest_overwrite(monkeypatch, tmp_path: Path) -> None:
    video, metadata = _source_and_metadata(tmp_path)
    destination = tmp_path / "output"
    monkeypatch.setattr(pipeline, "probe_video", lambda _video: metadata)
    # Claim the root once so the lock file is the only reason the second run fails.
    pipeline.prepare_face_output_root(video, destination)

    with exclusive_process_lock(destination / ".face.run.lock", purpose="test Face run"):
        with pytest.raises(RuntimeError, match="Another process"):
            pipeline.process_face_input(
                video,
                destination,
                config=FaceProcessingConfig(sample_fps=1.0, batch_size=1, device="cpu"),
                backend=FakeBackend(),
            )

    assert not (destination / "run_manifest.json").exists()
