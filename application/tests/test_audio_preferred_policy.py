"""Preferred categorical policy through typed jobs and native AST planning."""
import json
from pathlib import Path

import pytest

from application.backend import AudioRunRequest, build_audio_command
from application.automation.config import job_schema, load_job
from application.automation.errors import ValidationError
from application.automation.stages import _native_parser, build_stage


REPO_ROOT = Path(__file__).resolve().parents[2]
FLAG = "--require-preferred-categorical"


def write_audio_job(tmp_path, **options):
    path = tmp_path / "job.json"
    path.write_text(json.dumps({"schema_version": 1, "stage": "audio",
                               "options": {"source_path": "input.mp4", **options}}), encoding="utf-8")
    return path


def plan(tmp_path, stage, options):
    return build_stage(stage, options, {}, base_dir=tmp_path, repo_root=REPO_ROOT,
                       python_executable="python", workspace=tmp_path / "stage", dry_run=True)


def test_generated_audio_schema_exposes_optional_boolean_policy():
    schema = job_schema()["x-stage-options"]["audio"]
    assert schema["properties"]["require_preferred_categorical"] == {"type": "boolean", "default": False}
    assert "require_preferred_categorical" not in schema["required"]


@pytest.mark.parametrize("enabled", [True, False])
def test_typed_audio_json_accepts_boolean_policy(tmp_path, enabled):
    job = load_job(write_audio_job(tmp_path, require_preferred_categorical=enabled))
    assert job.steps[0].options["require_preferred_categorical"] is enabled


@pytest.mark.parametrize("invalid", ["true", "false", 1, 0, None])
def test_typed_audio_json_rejects_nonboolean_policy(tmp_path, invalid):
    with pytest.raises(ValidationError, match="require_preferred_categorical.*invalid type"):
        load_job(write_audio_job(tmp_path, require_preferred_categorical=invalid))


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_typed_audio_plan_propagates_required_policy_once(tmp_path, mode):
    source = tmp_path / ("input.mp4" if mode == "single" else "media")
    if mode == "single":
        source.write_bytes(b"planning fixture only")
    else:
        source.mkdir()
    options = {"source_path": str(source), "output_root": "out", "mode": mode,
               "require_preferred_categorical": True}
    result = plan(tmp_path, "audio", options)
    assert result.command.count(FLAG) == 1
    assert "--skip-emotion-models" not in result.command
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "stage").exists()


def test_omitted_policy_preserves_default_audio_command(tmp_path):
    request = AudioRunRequest(mode="single", source_path=tmp_path / "input.mp4", output_root=tmp_path / "out")
    assert request.require_preferred_categorical is False
    assert FLAG not in build_audio_command(request, repo_root=REPO_ROOT)


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_audio_builder_rejects_required_policy_when_emotions_disabled(tmp_path, mode):
    request = AudioRunRequest(mode=mode, source_path=tmp_path / "input.mp4", output_root=tmp_path / "out",
                              include_emotions=False, require_preferred_categorical=True)
    with pytest.raises(ValueError, match="[Rr]equir.*emotion"):
        build_audio_command(request, repo_root=REPO_ROOT)


def test_typed_job_plan_rejects_skip_policy_conflict_before_writes(tmp_path):
    (tmp_path / "input.mp4").write_bytes(b"planning fixture only")
    job = load_job(write_audio_job(tmp_path, include_emotions=False, require_preferred_categorical=True))
    with pytest.raises(ValidationError, match="[Rr]equir.*emotion"):
        plan(tmp_path, job.steps[0].stage, {**job.steps[0].options, "output_root": "out"})
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize("mode", ["single", "batch"])
def test_native_audio_ast_parser_and_plan_accept_required_policy(tmp_path, mode):
    args = [mode, "input.mp4", "--output", "out", FLAG]
    parsed = _native_parser("audio", REPO_ROOT).parse_args(args)
    assert parsed.require_preferred_categorical is True
    assert parsed.skip_emotion_models is False
    result = plan(tmp_path, "native.audio", {"args": args, "output_root": "out"})
    assert result.command.count(FLAG) == 1
    assert result.command[:3] == ["python", "-m", "processing.audio_analysis.audio_pipeline"]


def test_native_audio_ast_parser_preserves_skip_conflict(tmp_path):
    args = ["single", "input.mp4", "--output", "out", FLAG, "--skip-emotion-models"]
    with pytest.raises(ValidationError, match="not allowed with"):
        plan(tmp_path, "native.audio", {"args": args, "output_root": "out"})
