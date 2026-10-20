from __future__ import annotations

import json
from pathlib import Path

import pytest

from processing.text_analysis.contracts import inventory_digest
from processing.text_analysis.manifest_validation import (
    DERIVED,
    TRANSCRIPTION,
    read_completed_manifest,
    validate_derived_settings,
    validate_selection_settings,
    validate_transcription_settings,
)
from processing.text_analysis.transcribe.provenance import build_output_provenance


def _whisper_provenance(model: str = "small", language: str | None = None) -> dict[str, dict[str, object]]:
    return build_output_provenance(
        {
            "engine": {"distribution": "openai-whisper", "version": "test"},
            "checkpoint": {
                "requested_name": model,
                "filename": f"{model}.pt",
                "expected_sha256": "a" * 64,
                "hash_source": "openai_whisper_model_registry",
            },
            "runtime": {"torch_version": "test", "ffmpeg_version": "test"},
        },
        requested_task="bilingual",
        device="cpu",
        requested_language=language,
    )


def _transcription_manifest(tmp_path: Path) -> dict[str, object]:
    record = {"identity": "UK/Test Speaker/001_UK_Test_Speaker_20250101", "status": "completed"}
    return {
        "schema_version": "2.0",
        "kind": "whisper-transcription-batch",
        "status": "completed",
        "input_path": str(tmp_path / "input"),
        "output_root": str(tmp_path / "whisper"),
        "config": {"task": "bilingual", "model": "small", "device": "cpu", "language": None},
        "whisper_provenance": _whisper_provenance(),
        "inventory_sha256": inventory_digest([record]),
        "summary": {"total": 1, "completed": 1, "skipped": 0, "failed": 0},
        "videos": [record],
    }


def test_completed_manifest_recomputes_inventory_digest(tmp_path: Path) -> None:
    payload = _transcription_manifest(tmp_path)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert read_completed_manifest(path, "transcription", TRANSCRIPTION)["kind"] == TRANSCRIPTION.kind

    payload["videos"][0]["identity"] = "UK/Test Speaker/tampered"  # type: ignore[index]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="inventory digest"):
        read_completed_manifest(path, "transcription", TRANSCRIPTION)


def test_completed_manifest_rejects_wrong_schema_and_kind(tmp_path: Path) -> None:
    payload = _transcription_manifest(tmp_path)
    path = tmp_path / "manifest.json"
    for key, value, message in (
        ("schema_version", "1.0", "unsupported schema"),
        ("kind", "something-else", "expected"),
    ):
        changed = dict(payload)
        changed[key] = value
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(RuntimeError, match=message):
            read_completed_manifest(path, "transcription", TRANSCRIPTION)


def test_transcription_resume_rejects_changed_model(tmp_path: Path) -> None:
    payload = _transcription_manifest(tmp_path)
    with pytest.raises(RuntimeError, match="model"):
        validate_transcription_settings(
            payload,
            input_path=tmp_path / "input",
            output_root=tmp_path / "whisper",
            model="large-v3",
            requested_device="auto",
        )


@pytest.mark.parametrize("language", ["en", "fr", ""])
def test_pipeline_accepts_the_requested_transcription_language(tmp_path: Path, language: str) -> None:
    from processing.text_analysis.pipeline import TextProcessingConfig, _validate_transcription_manifest

    payload = _transcription_manifest(tmp_path)
    payload["config"]["language"] = language or None
    payload["whisper_provenance"] = _whisper_provenance(language=language or None)
    paths = {"input": tmp_path / "input", "whisper": tmp_path / "whisper"}
    settings = TextProcessingConfig(whisper_language=language)

    _validate_transcription_manifest(payload, settings, paths)

    payload["config"]["language"] = "de"
    with pytest.raises(RuntimeError, match="language"):
        _validate_transcription_manifest(payload, settings, paths)


def test_selection_resume_rejects_changed_language_policy(tmp_path: Path) -> None:
    payload = {
        "input_path": str(tmp_path / "input"),
        "default_variant": "eng",
        "language_policy": {"France": "original"},
    }
    with pytest.raises(RuntimeError, match="language policy"):
        validate_selection_settings(
            payload,
            input_path=tmp_path / "input",
            default_variant="eng",
            language_policy={},
        )


def test_derived_resume_rejects_changed_core_categories(tmp_path: Path) -> None:
    payload = {"source_root": str(tmp_path / "extra"), "categories": ["Positiv"]}
    with pytest.raises(RuntimeError, match="core category"):
        validate_derived_settings(
            payload,
            source_root=tmp_path / "extra",
            categories=("Positiv", "Strong"),
        )


def test_derived_manifest_contract_is_current_schema(tmp_path: Path) -> None:
    record = {"identity": "UK/Test Speaker/video", "status": "completed"}
    payload = {
        "schema_version": "2.0",
        "kind": DERIVED.kind,
        "status": "completed",
        "inventory_sha256": inventory_digest([record]),
        "summary": {"total": 1, "completed": 1, "failed": 0},
        "files": [record],
    }
    path = tmp_path / "derived.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert read_completed_manifest(path, "derived", DERIVED) == payload
