import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]


def cli(*args):
    return subprocess.run([sys.executable, "-m", "application.cli", *map(str, args)], cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=40)


@pytest.mark.parametrize("args", [("unknown",), ("run",), ("schema", "--stage", "missing")])
def test_public_errors_are_one_json_object(args):
    result = cli(*args)
    assert result.returncode == 2
    assert json.loads(result.stdout)["state"] == "validation_failed"


def test_schema_and_settings_never_expose_credentials(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "never-save-this-token")
    result = cli("settings")
    assert result.returncode == 0
    assert json.loads(result.stdout)["credential_environment_present"]["hugging_face"] is True
    assert "never-save-this-token" not in result.stdout + result.stderr
    result = cli("schema")
    assert result.returncode == 0
    assert "procurement" in json.loads(result.stdout)["x-stage-options"]


def test_native_dry_run_resolves_paths_and_has_no_side_effect(tmp_path):
    job = tmp_path / "job with spaces.json"
    job.write_text(json.dumps({"schema_version": 1, "stage": "native.local", "options": {"args": ["--source", "literal $(no shell).mp4", "--output-root", "résultats", "--mode", "full"], "output_root": "résultats"}}), encoding="utf-8")
    run_dir = tmp_path / "new run"
    result = cli("run", "--job", job, "--run-dir", run_dir, "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert str(tmp_path / "literal $(no shell).mp4") in payload["steps"][0]["command"]
    assert str(tmp_path / "résultats") in payload["steps"][0]["command"]
    assert not run_dir.exists() and not (tmp_path / "résultats").exists()


def test_native_module_whitelist_and_unknown_flags_fail_before_run(tmp_path):
    for stage, args in [("native.os", []), ("native.local", ["--unknown"]), ("native.local", ["--source", "x", "--output-root", "different", "--mode", "full"])]:
        job = tmp_path / "job.json"
        job.write_text(json.dumps({"schema_version": 1, "stage": stage, "options": {"args": args, "output_root": "output"}}))
        run_dir = tmp_path / "new run"
        result = cli("run", "--job", job, "--run-dir", run_dir)
        assert result.returncode == 2, result.stdout + result.stderr
        assert not run_dir.exists()
