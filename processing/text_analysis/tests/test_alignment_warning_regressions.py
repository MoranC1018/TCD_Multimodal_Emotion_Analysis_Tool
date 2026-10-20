"""Structural timing failures and warning visibility across cached Text runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.launcher import LauncherState
from processing.text_analysis import pipeline
from processing.text_analysis.tests.test_resume_catalog_and_cache import (
    completed_catalog_transcription,
)
from processing.text_analysis.transcribe import transcribe
from processing.text_analysis.transcribe.integrity import validate_transcription_artifact
from processing.text_analysis.transcribe.test_transcribe_alignment import fake_provenance


@pytest.mark.parametrize("field", ["start", "end"])
@pytest.mark.parametrize("bad_time", [float("nan"), float("inf"), -float("inf")])
def test_raw_nonfinite_timing_is_a_structural_error(field, bad_time):
    original = {"id": 0, "start": 0, "end": 5, "text": "Bonjour"}
    original[field] = bad_time
    with pytest.raises(ValueError, match="timing"):
        transcribe._build_bilingual_outputs(
            Path("synthetic.mp4"), "cpu", "fr", {"segments": [original]},
            {"segments": [{"id": 0, "start": 10, "end": 15, "text": "Hello"}]},
        )


@pytest.mark.parametrize("field", ["start", "end"])
@pytest.mark.parametrize("bad_time", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("task", ["transcribe", "translate", "bilingual"])
def test_cached_nonfinite_timing_is_not_reusable(tmp_path, field, bad_time, task):
    kind = {"transcribe": "original", "translate": "eng", "bilingual": "bilingual"}[task]
    provenance = fake_provenance("bilingual")[kind]
    segment = {"id": 0, "start": 0, "end": 5, "text": "Hello",
        "text_original": "Bonjour", "text_en": "Hello"}
    segment[field] = bad_time
    path = tmp_path / "cached.json"
    path.write_text(json.dumps({
        "schema_version": "2.0", "model": "small", "task": task,
        "source_sha256": "a" * 64, "whisper_provenance": provenance,
        "segments": [segment],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid segments"):
        validate_transcription_artifact(path, expected_task=task, expected_model="small",
            expected_source_sha256="a" * 64, expected_provenance=provenance)


def warning_catalog(completed_catalog_transcription, monkeypatch):
    config, arguments, _calls = completed_catalog_transcription

    class UnalignedWhisper:
        def transcribe(self, _source, *, task, **_kwargs):
            original = task == "transcribe"
            return {"language": "fr", "segments": [{"id": 0,
                "start": 0 if original else 10, "end": 5 if original else 15,
                "text": "Bonjour" if original else "Hello"}]}

    monkeypatch.setattr(transcribe, "_load_whisper_model", lambda *_args: UnalignedWhisper())
    assert transcribe.main([arg for arg in arguments if arg != "--skip-existing"]) == 0
    return config, arguments


def assert_launcher_sees_warning(output):
    state = LauncherState()
    state.reserve_process(["synthetic"], mode="text-native", total=2)
    for line in output.splitlines():
        state.append(line)
    assert state.snapshot()["progress"].get("bilingualAlignmentWarning"), output


def test_cached_warning_reaches_launcher_progress(
    completed_catalog_transcription, monkeypatch, capsys,
):
    config, arguments = warning_catalog(completed_catalog_transcription, monkeypatch)
    capsys.readouterr()

    def no_model(*_args):
        pytest.fail("A verified complete output set must not load Whisper")

    monkeypatch.setattr(transcribe, "_load_whisper_model", no_model)
    assert transcribe.main(arguments) == 0
    captured = capsys.readouterr()
    assert_launcher_sees_warning(captured.out + captured.err)
    manifest = json.loads((Path(config.whisper_root) / "_manifests/transcription_run_manifest.json").read_text())
    assert manifest["summary"]["skipped"] == 2
    assert manifest["summary"]["warnings"] == 2


def test_pipeline_resume_replays_upstream_warning(
    tmp_path, completed_catalog_transcription, monkeypatch, capsys,
):
    config, _arguments = warning_catalog(completed_catalog_transcription, monkeypatch)
    capsys.readouterr()
    pipeline.run_text_pipeline(config, from_stage="select", to_stage="select", repo_root=tmp_path)
    captured = capsys.readouterr()
    assert_launcher_sees_warning(captured.out + captured.err)
