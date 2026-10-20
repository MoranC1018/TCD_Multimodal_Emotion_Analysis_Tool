"""Regression cases independently reproduced during the CLI review."""
import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

from application.automation import runner, stages
from application.automation.config import load_job
from application.automation.errors import ValidationError

REPO = Path(__file__).parents[2]


def test_effective_evidence_records_timeout_override(tmp_path, monkeypatch):
    filename = tmp_path / "job.json"
    filename.write_text(json.dumps({"schema_version": 1, "stage": "audio", "options": {"source_path": "input.mp4"}, "timeout_seconds": 60, "resources": {"resourceLimitsEnabled": False}}))
    def build(_stage, options, _native, **_kwargs):
        return stages.StagePlan([sys.executable, "-c", "import time;time.sleep(5)"], Path(options["output_root"]))
    monkeypatch.setattr(stages, "build_stage", build)
    result, code = runner.run_job(load_job(filename), tmp_path / "run", repo_root=REPO, python_executable=sys.executable, timeout_seconds=.2, stderr=io.StringIO())
    assert code == 124 and result["state"] == "timed_out"
    assert json.loads((tmp_path / "run" / "submitted.json").read_text())["timeout_seconds"] == 60
    for name in ("effective.json", "status.json", "result.json"):
        assert json.loads((tmp_path / "run" / name).read_text())["timeout_seconds"] == .2


def test_late_output_reader_failure_cannot_be_completed(tmp_path):
    class Sink:
        def write(self, text):
            time.sleep(.3)
            raise UnicodeEncodeError("ascii", text, 0, 1, "controlled late sink failure")
        def flush(self):
            pass
    result = runner.execute_command([sys.executable, "-c", "print('late output')"], cwd=REPO, log_path=tmp_path / "reader.log", stderr=Sink())
    assert result["returncode"] == 0
    assert result["errors"]
    assert result["state"] == "failed"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object ownership contract")
def test_unavailable_windows_job_stops_before_engine_work(tmp_path, monkeypatch):
    import psutil
    from application import launcher
    marker = tmp_path / "engine-work.pid"
    parent_ids = []
    def no_job(process):
        parent_ids.append(process.pid)
        return None
    monkeypatch.setattr(launcher, "assign_process_to_kill_job", no_job)
    script = "import subprocess,sys,pathlib;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);pathlib.Path(sys.argv[1]).write_text(str(p.pid));sys.exit(7)"
    try:
        result = runner.execute_command([sys.executable, "-c", script, str(marker)], cwd=REPO, log_path=tmp_path / "no-job.log", stderr=io.StringIO())
        assert result["state"] == "failed"
        assert not marker.exists(), "Engine ran before Windows process ownership was established"
        assert not any(psutil.pid_exists(pid) for pid in parent_ids)
        assert "Job Object" in " ".join(result["errors"])
    finally:
        if marker.exists():
            try:
                child = psutil.Process(int(marker.read_text()))
                if "time.sleep(30)" in " ".join(child.cmdline()):
                    child.terminate()
                    child.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass


@pytest.mark.parametrize("ending", ["failure", "cancel", "timeout"])
def test_owned_windows_descendants_end_with_run(tmp_path, ending):
    if os.name != "nt":
        pytest.skip("Windows process ownership contract")
    import psutil
    marker = tmp_path / "child.pid"
    script = "import subprocess,sys,pathlib,time;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);pathlib.Path(sys.argv[1]).write_text(str(p.pid));" + ("sys.exit(7)" if ending == "failure" else "time.sleep(30)")
    result = runner.execute_command([sys.executable, "-c", script, str(marker)], cwd=REPO, log_path=tmp_path / (ending + ".log"), stderr=io.StringIO(), timeout_seconds=.4 if ending == "timeout" else None, cancelled=lambda: ending == "cancel" and marker.exists())
    assert result["state"] == {"failure": "failed", "cancel": "cancelled", "timeout": "timed_out"}[ending]
    pid = int(marker.read_text())
    deadline = time.monotonic() + 2
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(.02)
    try:
        assert not psutil.pid_exists(pid)
    finally:
        if psutil.pid_exists(pid):
            child = psutil.Process(pid)
            if "time.sleep(30)" in " ".join(child.cmdline()):
                child.terminate()
                child.wait(timeout=5)


def test_auxiliary_docx_output_cannot_overwrite_submitted_job(tmp_path):
    filename = tmp_path / "job.json"
    payload = {"schema_version": 1, "stage": "native.docx-sampling", "options": {"args": ["input.docx", "--speaker-output-root", "out", "--output", "job.json"], "output_root": "out"}}
    filename.write_text(json.dumps(payload))
    before = filename.read_bytes()
    with pytest.raises(ValidationError, match="(?i)output|overwrite|protected"):
        runner.plan_job(load_job(filename), tmp_path / "run", repo_root=REPO, python_executable=sys.executable)
    assert not (tmp_path / "run").exists() and filename.read_bytes() == before


def test_auxiliary_output_hardlink_cannot_overwrite_submitted_job(tmp_path):
    filename = tmp_path / "job.json"
    payload = {"schema_version": 1, "stage": "native.docx-sampling", "options": {"args": ["input.docx", "--speaker-output-root", "out", "--output", "linked-report.docx"], "output_root": "out"}}
    filename.write_text(json.dumps(payload))
    os.link(filename, tmp_path / "linked-report.docx")
    before = filename.read_bytes()
    with pytest.raises(ValidationError, match="(?i)output|overwrite|protected"):
        runner.plan_job(load_job(filename), tmp_path / "run", repo_root=REPO, python_executable=sys.executable)
    assert filename.read_bytes() == before and not (tmp_path / "run").exists()


@pytest.mark.parametrize("target", ["status.json", "effective.json", "submitted.json", "result.json", "logs/main.log", "steps/main/control.json"])
def test_auxiliary_outputs_cannot_write_evidence(tmp_path, monkeypatch, target):
    filename = tmp_path / "job.json"
    filename.write_text(json.dumps({"schema_version": 1, "stage": "audio", "options": {"source_path": "input.mp4"}}))
    directory = tmp_path / "run"
    def build(_stage, options, _native, **_kwargs):
        return stages.StagePlan([sys.executable, "-c", "pass"], Path(options["output_root"]), {"output_paths": [str(directory / target)]})
    monkeypatch.setattr(stages, "build_stage", build)
    with pytest.raises(ValidationError, match="(?i)output|overwrite|protected"):
        runner.plan_job(load_job(filename), directory, repo_root=REPO, python_executable=sys.executable)
    assert not directory.exists()
