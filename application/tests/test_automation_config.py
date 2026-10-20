import json
from pathlib import Path

import pytest

from application.automation.config import load_job, resolve_references
from application.automation.errors import ValidationError


def write_job(tmp_path, value):
    path = tmp_path / "job.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_single_stage_and_config_relative_base(tmp_path):
    job = load_job(write_job(tmp_path, {"schema_version": 1, "stage": "audio", "options": {"mode": "single", "source_path": "音声 clip.mp4"}}))
    assert job.base_dir == tmp_path
    assert job.steps[0].id == "main"
    assert job.steps[0].options["source_path"] == "音声 clip.mp4"


@pytest.mark.parametrize("change", [
    {"schema_version": True}, {"schema_version": 2}, {"typo": 1},
    {"timeout_seconds": 0}, {"timeout_seconds": float("nan")},
    {"timeout_seconds": 10**400}, {"resources": {"maxCpuCores": 10**400}},
    {"resources": {"nativeThreads": True}}, {"resources": {"maxCpuPercent": 101}},
    {"resources": {"maxRamPercent": 96}}, {"resources": {"nativeThreads": 257}},
    {"resources": {"resourcePollSeconds": .49}},
    {"options": {"mode": "single", "source_path": "x", "include_emotions": "false"}},
    {"options": {"mode": "single", "source_path": "x", "HF_TOKEN": "secret"}},
])
def test_malformed_job_rejected(tmp_path, change):
    value = {"schema_version": 1, "stage": "audio", "options": {"mode": "single", "source_path": "x"}}
    value.update(change)
    with pytest.raises(ValidationError):
        load_job(write_job(tmp_path, value))


def test_forward_and_duplicate_steps_rejected(tmp_path):
    steps = [{"id": "a", "stage": "audio", "options": {"mode": "batch", "source_path": {"from_step": "b", "output": "output_root"}}}]
    with pytest.raises(ValidationError, match="earlier"):
        load_job(write_job(tmp_path, {"schema_version": 1, "steps": steps}))
    steps = [{"id": "a", "stage": "audio", "options": {"mode": "single", "source_path": "x"}}] * 2
    with pytest.raises(ValidationError, match="unique"):
        load_job(write_job(tmp_path, {"schema_version": 1, "steps": steps}))


def test_structured_handoff_uses_actual_output():
    options = {"modalities": [{"source_path": {"from_step": "proc", "output": "output_root"}}]}
    assert resolve_references(options, {"proc": {"output_root": "actual/generated/catalog_run"}}) == {"modalities": [{"source_path": "actual/generated/catalog_run"}]}


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / "job.json"
    path.write_text('{"schema_version":1,"schema_version":2}', encoding="utf-8")
    with pytest.raises(ValidationError, match="Duplicate"):
        load_job(path)


def test_schema_describes_accepted_null_timeouts_and_native_output_default(tmp_path):
    from application.automation.config import job_schema
    job = load_job(write_job(tmp_path, {"schema_version": 1, "timeout_seconds": None, "steps": [{"id": "main", "stage": "native.local", "timeout_seconds": None, "options": {"args": ["--source", "clip.mp4", "--output-root", "output", "--mode", "full"]}}]}))
    assert job.timeout_seconds is None and job.steps[0].timeout_seconds is None
    schema = job_schema()
    assert "null" in schema["properties"]["timeout_seconds"]["type"]
    assert "null" in schema["properties"]["steps"]["items"]["properties"]["timeout_seconds"]["type"]
    assert "output_root" not in schema["x-stage-options"]["native.local"]["required"]


def test_job_path_alias_is_rejected_before_read(tmp_path):
    path = write_job(tmp_path, {"schema_version": 1, "stage": "audio", "options": {"source_path": "x"}})
    link = tmp_path / "linked.json"
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("Creating symlinks requires platform permission")
    with pytest.raises((ValidationError, ValueError), match="(?i)alias|link|reparse"):
        load_job(link)
