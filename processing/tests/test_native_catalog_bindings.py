from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from procurement.catalog_runner import run_catalog
from processing import catalog_context
from processing.face_analysis import __main__ as face_cli
from processing.face_analysis.config import FaceProcessingConfig
from processing.face_analysis.media import VideoMetadata
from processing.face_analysis import pipeline as face_pipeline
from processing.text_analysis import __main__ as text_cli
from processing.text_analysis import pipeline as text_pipeline
from processing.text_analysis.transcribe import transcribe


def _catalog_run(tmp_path: Path) -> tuple[Path, str, bytes, bytes]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"catalog media")
    catalog = tmp_path / "sources.csv"
    with catalog.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Link", "Speaker", "Language", "Country"])
        writer.writerow(["clip.mp4", "Speaker A", "Research label", "Ireland"])

    def process(_source, output_directory: Path, _options) -> dict[str, str]:
        (output_directory / "stitched_imotions.mp4").write_bytes(b"canonical media")
        return {"video_directory": str(output_directory)}

    run_root = tmp_path / "catalog-run"
    run_catalog(
        catalog,
        run_root,
        selected_source_ids=["source-0001"],
        local_metadata_fetcher=lambda _source: {
            "title": "Interview",
            "youtube_language": "",
        },
        processor=process,
    )
    digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
    return (
        run_root,
        digest,
        (run_root / "source_manifest.json").read_bytes(),
        (run_root / "source_metadata.csv").read_bytes(),
    )


def test_face_config_and_cli_forward_repeated_source_ids_and_catalog_digest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Break caught: the Face CLI drops catalog authorization before processing."""

    captured: dict[str, object] = {}
    digest = "a" * 64

    class Ready:
        ready = True
        detail = "ready"

    monkeypatch.setattr(face_cli, "check_readiness", lambda _device: Ready())
    monkeypatch.setattr(
        face_cli,
        "process_face_input",
        lambda source, output, **kwargs: captured.update(
            source=source, output=output, kwargs=kwargs
        )
        or type(
            "Result",
            (),
            {
                "output_root": tmp_path,
                "processed": 1,
                "skipped": 0,
                "failed": 0,
                "run_manifest": tmp_path / "manifest.json",
                "run_index": tmp_path / "index.csv",
            },
        )(),
    )
    monkeypatch.setattr(
        face_cli.sys,
        "argv",
        [
            "face-analysis",
            str(tmp_path),
            "--source-id",
            "source-0002",
            "--source-id",
            "source-0001",
            "--catalog-sha256",
            digest,
        ],
    )

    assert face_cli.main() == 0
    config = captured["kwargs"]["config"]
    assert config.source_ids == ("source-0002", "source-0001")
    assert config.catalog_sha256 == digest


def test_face_catalog_binding_is_in_manifests_index_and_resume_fingerprint(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Break caught: identical media can be reused after its SourceID/context changes."""

    run_root, digest, manifest_bytes, metadata_bytes = _catalog_run(tmp_path)
    destination = tmp_path / "face-run"
    captured_manifest: dict[str, object] = {}

    class Backend:
        name = "test"
        version = "1"
        calls = 0

        def analyse(self, *_args):
            self.calls += 1
            return object()

        def provenance(self, config):
            return {
                "name": self.name,
                "version": self.version,
                "resolved_device": config.device,
                "models": {},
                "package_versions": {},
            }

    backend = Backend()
    monkeypatch.setattr(face_pipeline, "configure_ffmpeg_shared_libraries", lambda: None)
    monkeypatch.setattr(
        face_pipeline,
        "probe_video",
        lambda path: VideoMetadata(str(path), "b" * 64, 15, 1.0, 1.0, 1, 10, 10),
    )
    monkeypatch.setattr(
        face_pipeline,
        "build_output_tables",
        lambda *_args, **_kwargs: (object(), object(), {"sampled_frames": 1}),
    )

    def write_outputs(video_dir: Path, _raw, _core, manifest):
        captured_manifest.update(manifest)
        video_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / "video_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(face_pipeline, "write_video_outputs", write_outputs)

    result = face_pipeline.process_face_input(
        run_root,
        destination,
        config=FaceProcessingConfig(
            sample_fps=1,
            batch_size=1,
            device="cpu",
            source_ids=("source-0001",),
            catalog_sha256=digest,
        ),
        backend=backend,
        run_id="catalog-face",
    )

    assert backend.calls == 1
    assert (destination / "source_manifest.json").read_bytes() == manifest_bytes
    assert (destination / "source_metadata.csv").read_bytes() == metadata_bytes
    source = captured_manifest["source"]
    assert source["source_id"] == "source-0001"
    assert source["speaker"] == "Speaker A"
    assert source["catalog_sha256"] == digest
    assert source["user_metadata"]["Language"] == "Research label"
    assert source["content"] == {"sha256": "b" * 64, "size_bytes": 15}
    assert len(source["source_context_sha256"]) == 64
    with result.run_index.open(encoding="utf-8", newline="") as handle:
        index = next(csv.DictReader(handle))
    assert index["source_id"] == "source-0001"
    assert index["catalog_sha256"] == digest
    run_manifest = json.loads(result.run_manifest.read_text(encoding="utf-8"))
    assert run_manifest["processed_source_ids"] == ["source-0001"]
    assert run_manifest["videos"][0]["source_id"] == "source-0001"

    binding = source
    changed = {**binding, "source_id": "source-0002"}
    provenance = backend.provenance(FaceProcessingConfig(device="cpu"))
    assert face_pipeline._analysis_fingerprint(
        FaceProcessingConfig(device="cpu"), provenance, binding
    ) != face_pipeline._analysis_fingerprint(
        FaceProcessingConfig(device="cpu"), provenance, changed
    )


def test_face_catalog_reuses_json_config_and_rejects_changed_source_ids(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Break caught: saved SourceID lists invalidate unchanged tuple settings."""

    pytest.importorskip("pyarrow")
    import pandas as pd
    from processing.face_analysis.tests.helpers import complete_detection_row

    run_root, digest, _manifest_bytes, _metadata_bytes = _catalog_run(tmp_path)
    destination = tmp_path / "face-run"

    class Backend:
        name = "test"
        version = "1"

        def analyse(self, *_args):
            return pd.DataFrame([complete_detection_row()])

    monkeypatch.setattr(face_pipeline, "configure_ffmpeg_shared_libraries", lambda: None)
    monkeypatch.setattr(
        face_pipeline,
        "probe_video",
        lambda path: VideoMetadata(str(path), "b" * 64, 15, 1.0, 1.0, 1, 10, 10),
    )
    config = FaceProcessingConfig(
        sample_fps=1,
        batch_size=1,
        device="cpu",
        source_ids=("source-0001",),
        catalog_sha256=digest,
    )
    backend = Backend()
    first = face_pipeline.process_face_input(run_root, destination, config=config, backend=backend)
    second = face_pipeline.process_face_input(run_root, destination, config=config, backend=backend)

    assert (first.processed, first.skipped, first.failed) == (1, 0, 0)
    assert (second.processed, second.skipped, second.failed) == (0, 1, 0)

    manifest_path = next(destination.rglob("video_manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["config"]["source_ids"] == ["source-0001"]
    manifest["config"]["source_ids"] = ["source-0002"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    repaired = face_pipeline.process_face_input(run_root, destination, config=config, backend=backend)

    assert (repaired.processed, repaired.skipped, repaired.failed) == (1, 0, 0)


def test_face_rejects_tampered_catalog_before_runtime_or_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Break caught: Py-Feat starts after a SourceID context has been tampered."""

    run_root, digest, _manifest, _metadata = _catalog_run(tmp_path)
    context_path = next(run_root.rglob("source_context.json"))
    payload = json.loads(context_path.read_text(encoding="utf-8"))
    payload["catalog_sha256"] = "0" * 64
    context_path.write_text(json.dumps(payload), encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(
        face_pipeline,
        "configure_ffmpeg_shared_libraries",
        lambda: calls.append("runtime"),
    )

    with pytest.raises(ValueError, match="catalog digest"):
        face_pipeline.process_face_input(
            run_root,
            tmp_path / "face-run",
            config=FaceProcessingConfig(
                source_ids=("source-0001",),
                catalog_sha256=digest,
            ),
        )
    assert calls == []
    assert not (tmp_path / "face-run").exists()


def test_text_config_cli_command_and_language_precedence_keep_catalog_binding(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Break caught: Text loses repeated SourceIDs or treats researcher Language as Whisper input."""

    captured: dict[str, object] = {}
    digest = "c" * 64
    monkeypatch.setattr(
        text_cli,
        "run_text_pipeline",
        lambda config, **kwargs: captured.update(config=config, kwargs=kwargs)
        or type(
            "Result",
            (),
            {
                "completed_stages": ("transcribe",),
                "selected_output": None,
                "extra_output": None,
                "manifest": "manifest.json",
            },
        )(),
    )

    assert text_cli.main(
        [
            str(tmp_path),
            "--source-id",
            "source-0002",
            "--source-id",
            "source-0001",
            "--catalog-sha256",
            digest,
            "--whisper-language",
            "fr",
            "--to-stage",
            "transcribe",
        ]
    ) == 0
    config = captured["config"]
    assert config.source_ids == ("source-0002", "source-0001")
    assert config.catalog_sha256 == digest
    assert config.whisper_language == "fr"
    command = text_pipeline._transcribe_command(config, tmp_path, tmp_path / "manifest.json")
    assert command.count("--source-id") == 2
    assert command[command.index("--catalog-sha256") + 1] == digest
    assert command[command.index("--language") + 1] == "fr"

    run_root, run_digest, _manifest, _metadata = _catalog_run(tmp_path / "catalog")
    discovery = catalog_context.discover_catalog_jobs(
        run_root,
        expected_catalog_sha256=run_digest,
    )
    assert discovery is not None
    job = discovery.jobs[0]
    assert catalog_context.catalog_text_language(job, "fr") == "fr"
    assert dict(job.user_metadata)["Language"] == "Research label"
    system = {**dict(job.system_metadata), "youtube_language": "pl"}
    replaced = dataclasses.replace(job, system_metadata=system)
    assert catalog_context.catalog_text_language(replaced, "fr") == "pl"
    assert catalog_context.catalog_text_language(dataclasses.replace(job, system_metadata={}), "") == ""


def test_text_catalog_tamper_is_rejected_before_readiness_or_output(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Break caught: Text preflight/model work begins before catalog validation."""

    run_root, digest, _manifest, _metadata = _catalog_run(tmp_path)
    context_path = next(run_root.rglob("source_context.json"))
    payload = json.loads(context_path.read_text(encoding="utf-8"))
    payload["speaker"] = "Tampered"
    context_path.write_text(json.dumps(payload), encoding="utf-8")
    readiness_calls: list[str] = []
    monkeypatch.setattr(
        text_pipeline,
        "check_text_processing_readiness",
        lambda *_args, **_kwargs: readiness_calls.append("readiness") or {},
    )
    config = text_pipeline.TextProcessingConfig(
        input_path=str(run_root),
        whisper_root=str(tmp_path / "text-run" / "transcripts"),
        selected_whisper_root=str(tmp_path / "text-run" / "selected"),
        prepared_root=str(tmp_path / "text-run" / "prepared"),
        selected_csv_root=str(tmp_path / "text-run" / "core"),
        extra_csv_root=str(tmp_path / "text-run" / "all"),
        postprocessing_root=str(tmp_path / "text-run" / "analysis"),
        source_ids=("source-0001",),
        catalog_sha256=digest,
    )

    with pytest.raises(ValueError, match="speaker"):
        text_pipeline.run_text_pipeline(config, to_stage="transcribe", repo_root=tmp_path)
    assert readiness_calls == []
    assert not (tmp_path / "text-run").exists()


def test_standalone_text_catalog_tamper_is_rejected_before_torch_or_whisper(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Break caught: standalone Text imported model runtime before catalog validation."""

    run_root, digest, _manifest, _metadata = _catalog_run(tmp_path)
    context_path = next(run_root.rglob("source_context.json"))
    payload = json.loads(context_path.read_text(encoding="utf-8"))
    payload["speaker"] = "Tampered"
    context_path.write_text(json.dumps(payload), encoding="utf-8")
    runtime_calls: list[str] = []

    def unexpected_runtime_call(*_args, **_kwargs):
        runtime_calls.append("runtime")
        raise AssertionError("model runtime reached before catalog validation")

    monkeypatch.setattr(transcribe, "configure_ffmpeg_shared_libraries", lambda: None)
    monkeypatch.setattr(transcribe, "_resolve_device", unexpected_runtime_call)
    monkeypatch.setattr(transcribe, "collect_whisper_execution_identity", unexpected_runtime_call)

    with pytest.raises(SystemExit) as exc_info:
        transcribe._main_unlocked(
            [
                "--catalog-root",
                str(run_root),
                "--source-id",
                "source-0001",
                "--catalog-sha256",
                digest,
                "--output-dir",
                str(tmp_path / "text-run"),
            ]
        )

    assert exc_info.value.code == 2
    assert runtime_calls == []
    assert not (tmp_path / "text-run").exists()


def test_text_identity_set_rejects_source_id_swapping_between_stages() -> None:
    """Break caught: identity-only validation lets two SourceIDs exchange artifacts."""

    inventory = [
        {"identity": "Speaker/A", "source_id": "source-0001"},
        {"identity": "Speaker/B", "source_id": "source-0002"},
    ]
    swapped = [
        {"identity": "Speaker/A", "source_id": "source-0002"},
        {"identity": "Speaker/B", "source_id": "source-0001"},
    ]
    with pytest.raises(RuntimeError, match="SourceID"):
        text_pipeline._assert_identity_set(inventory, swapped, "selection")
