from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from procurement.catalog_runner import run_catalog
from processing.text_analysis import pipeline
from processing.text_analysis.transcribe import transcribe


@pytest.fixture
def completed_catalog_transcription(tmp_path: Path, monkeypatch):
    """Produce real catalog/stage contracts with only Whisper inference replaced."""
    for name in ("alpha", "bravo"):
        (tmp_path / f"{name}.mp4").write_bytes(name.encode())
    catalog = tmp_path / "sources.csv"
    with catalog.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Link", "Speaker", "Country"])
        writer.writerow(["alpha.mp4", "Speaker A", "Ireland"])
        writer.writerow(["bravo.mp4", "Speaker B", "Ireland"])

    def process(source, output_directory, _options):
        (output_directory / "stitched_imotions.mp4").write_bytes(str(source).encode())
        return {"video_directory": str(output_directory)}

    run = tmp_path / "catalog"
    run_catalog(
        catalog, run,
        selected_source_ids=["source-0001", "source-0002"],
        local_metadata_fetcher=lambda _source: {"title": "Interview", "youtube_language": ""},
        processor=process,
    )
    calls: list[str] = []

    class FakeWhisper:
        def transcribe(self, _source, **kwargs):
            calls.append(kwargs["task"])
            return {
                "language": "en",
                "segments": [{"id": 0, "start": 0, "end": 1, "text": "Hello there"}],
            }

    identity = {
        "engine": {"distribution": "openai-whisper", "version": "test"},
        "checkpoint": {
            "requested_name": "small", "filename": "small.pt",
            "expected_sha256": "a" * 64, "hash_source": "openai_whisper_model_registry",
        },
        "runtime": {"torch_version": "test", "ffmpeg_version": "test"},
    }
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setattr(transcribe, "configure_ffmpeg_shared_libraries", lambda: None)
    monkeypatch.setattr(transcribe, "collect_whisper_execution_identity", lambda _model: identity)
    monkeypatch.setattr(transcribe, "_load_whisper_model", lambda *_args: FakeWhisper())
    whisper = tmp_path / "results" / "transcripts"
    arguments = [
        "--catalog-root", str(run), "--source-id", "source-0001", "--source-id", "source-0002",
        "--model", "small", "--task", "bilingual", "--device", "cpu",
        "--output-dir", str(whisper), "--skip-existing",
    ]
    assert transcribe.main(arguments) == 0
    calls.clear()
    config = pipeline.TextProcessingConfig(
        input_path=str(run), whisper_root=str(whisper),
        selected_whisper_root=str(tmp_path / "results" / "selected"),
        prepared_root=str(tmp_path / "results" / "prepared"),
        extra_csv_root=str(tmp_path / "results" / "all"),
        selected_csv_root=str(tmp_path / "results" / "core"),
        postprocessing_root=str(tmp_path / "results" / "post"),
        whisper_device="cpu", source_ids=("source-0001", "source-0002"),
        catalog_sha256=hashlib.sha256(catalog.read_bytes()).hexdigest(), write_graphs=False,
    )
    return config, arguments, calls


def test_resume_rejects_a_different_catalog_cohort_before_publishing(
    tmp_path: Path, completed_catalog_transcription,
) -> None:
    config, _arguments, _calls = completed_catalog_transcription
    config = dataclasses.replace(config, source_ids=("source-0001",))
    with pytest.raises(RuntimeError, match="catalog.*(cohort|selection)"):
        pipeline.run_text_pipeline(config, from_stage="select", to_stage="select", repo_root=tmp_path)
    assert not Path(config.selected_whisper_root).exists()
    assert not (Path(config.whisper_root).parent / "processed_source_ids.json").exists()


@pytest.mark.parametrize("changed", ["catalog_digest", "source_context"])
def test_resume_rejects_changed_current_catalog_binding_before_publishing(
    tmp_path: Path, completed_catalog_transcription, monkeypatch, changed: str,
) -> None:
    config, _arguments, _calls = completed_catalog_transcription
    discovery = pipeline.discover_catalog_jobs(
        Path(config.input_path), selected_source_ids=config.source_ids,
        expected_catalog_sha256=config.catalog_sha256,
    )
    assert discovery is not None
    job = discovery.jobs[0]
    if changed == "catalog_digest":
        changed_job = dataclasses.replace(job, catalog_sha256="b" * 64)
        discovery = dataclasses.replace(discovery, catalog_sha256="b" * 64)
    else:
        changed_job = dataclasses.replace(job, source_context={**job.source_context, "revision_note": "updated"})
    discovery = dataclasses.replace(discovery, jobs=(changed_job, *discovery.jobs[1:]))
    monkeypatch.setattr(pipeline, "discover_catalog_jobs", lambda *_args, **_kwargs: discovery)
    with pytest.raises(RuntimeError, match="catalog.*binding"):
        pipeline.run_text_pipeline(config, from_stage="select", to_stage="select", repo_root=tmp_path)
    assert not Path(config.selected_whisper_root).exists()
    assert not (Path(config.whisper_root).parent / "processed_source_ids.json").exists()


def test_resume_keeps_the_exact_unchanged_catalog_cohort(
    tmp_path: Path, completed_catalog_transcription,
) -> None:
    config, _arguments, calls = completed_catalog_transcription
    pipeline.run_text_pipeline(config, from_stage="select", to_stage="select", repo_root=tmp_path)
    selection = json.loads((Path(config.selected_whisper_root) / "selection_manifest.json").read_text())
    assert {row["source_id"] for row in selection["files"]} == set(config.source_ids)
    assert calls == []


@pytest.mark.parametrize("invalid_payload", [[], None, 42, "not a transcript"])
def test_partial_cache_with_non_object_json_regenerates_only_the_invalid_pass(
    completed_catalog_transcription, invalid_payload,
) -> None:
    config, arguments, calls = completed_catalog_transcription
    original = next((Path(config.whisper_root) / "original" / "Speaker_A").glob("*.json"))
    original.write_text(json.dumps(invalid_payload), encoding="utf-8")
    assert transcribe.main(arguments) == 0
    assert calls == ["transcribe"]
    manifest = json.loads(
        (Path(config.whisper_root) / "_manifests" / "transcription_run_manifest.json").read_text()
    )
    assert manifest["status"] == "completed"
    assert manifest["summary"]["completed"] == 1
    assert manifest["summary"]["skipped"] == 1


def test_partial_cache_recovery_failure_writes_a_terminal_batch_status(
    completed_catalog_transcription, monkeypatch,
) -> None:
    config, arguments, _calls = completed_catalog_transcription
    original = next((Path(config.whisper_root) / "original" / "Speaker_A").glob("*.json"))
    original.write_text("[]", encoding="utf-8")

    class FailingWhisper:
        def transcribe(self, *_args, **_kwargs):
            raise RuntimeError("synthetic inference failure")

    monkeypatch.setattr(transcribe, "_load_whisper_model", lambda *_args: FailingWhisper())
    assert transcribe.main(arguments) == 1
    manifest = json.loads(
        (Path(config.whisper_root) / "_manifests" / "transcription_run_manifest.json").read_text()
    )
    assert manifest["status"] == "failed"
    assert manifest["summary"]["failed"] == 1
    assert manifest["summary"]["skipped"] == 1
    assert "synthetic inference failure" in manifest["videos"][0]["error"]
