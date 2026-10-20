import io
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from application.automation.runner import execute_command, request_cancel, read_status
from application.automation.errors import ValidationError


def test_native_failed_child_is_failure_and_logs_preserved(tmp_path):
    result = execute_command([sys.executable, "-c", "import sys;print('artifact evidence');sys.exit(7)"], cwd=tmp_path, log_path=tmp_path / "step.log", stderr=io.StringIO())
    assert result["state"] == "failed"
    assert result["returncode"] == 7
    assert "artifact evidence" in (tmp_path / "step.log").read_text()


def test_native_cancel_exit_remains_cancellation(tmp_path):
    result = execute_command([sys.executable, "-c", "import sys;sys.exit(130)"], cwd=tmp_path, log_path=tmp_path / "cancel-exit.log", stderr=io.StringIO())
    assert result["state"] == "cancelled" and result["returncode"] == 130


def test_timeout_terminates_child_and_descendant(tmp_path):
    pid_path = tmp_path / "child.pid"
    script = "import subprocess,sys,time,pathlib;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(120)"
    result = execute_command([sys.executable, "-c", script, str(pid_path)], cwd=tmp_path, log_path=tmp_path / "timeout.log", timeout_seconds=1, stderr=io.StringIO())
    assert result["state"] == "timed_out"
    import psutil
    assert not psutil.pid_exists(int(pid_path.read_text()))


def test_cancel_only_writes_request_and_reports_stale(tmp_path):
    status = {"state": "running", "run_id": "owned-run", "runner_pid": os.getpid(), "runner_create_time": 0}
    (tmp_path / "status.json").write_text(json.dumps(status))
    assert read_status(tmp_path)["state"] == "stale"
    with pytest.raises(ValidationError, match="active"):
        request_cancel(tmp_path)
    assert not (tmp_path / "cancel.request.json").exists()


def test_cancel_callback_terminates_owned_process(tmp_path):
    start = time.monotonic()
    result = execute_command([sys.executable, "-c", "import time;time.sleep(120)"], cwd=tmp_path, log_path=tmp_path / "cancel.log", cancelled=lambda: time.monotonic() - start > .3, stderr=io.StringIO())
    assert result["state"] == "cancelled"
    assert result["returncode"] != 0


def test_workflow_real_children_fail_stop_and_preserve_prior_output(tmp_path, monkeypatch):
    from application.automation.config import load_job
    from application.automation.runner import run_job, plan_job
    from application.automation import stages
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps({"schema_version": 1, "resources": {"resourceLimitsEnabled": False}, "steps": [
        {"id": "first", "stage": "audio", "options": {"source_path": "input.mp4"}},
        {"id": "failure", "stage": "audio", "options": {"source_path": {"from_step": "first", "output": "output_root"}}},
        {"id": "never", "stage": "audio", "options": {"source_path": "input.mp4"}},
    ]}))
    builds = []
    def build(stage, options, native_options, **kwargs):
        output = Path(options["output_root"]) / "actual-generated-root"
        builds.append((output.parent.name, options["source_path"], kwargs["dry_run"]))
        code = "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.mkdir(parents=True);(p/'evidence.txt').write_text('preserved');sys.exit(int(sys.argv[2]))"
        return stages.StagePlan([sys.executable, "-c", code, str(output), "9" if output.parent.name == "failure" else "0"], output)
    monkeypatch.setattr(stages, "build_stage", build)
    job = load_job(job_file)
    run_dir = tmp_path / "run"
    preview = plan_job(job, run_dir, repo_root=tmp_path, python_executable=sys.executable)
    assert preview["steps"][1]["state"] == "deferred"
    assert not run_dir.exists()
    result, code = run_job(job, run_dir, repo_root=tmp_path, python_executable=sys.executable, stderr=io.StringIO())
    assert code == 3 and result["state"] == "failed"
    assert [item["state"] for item in result["steps"]] == ["completed", "failed", "pending"]
    assert builds[-1][1] == str(run_dir / "outputs" / "first" / "actual-generated-root")
    assert (run_dir / "outputs" / "first" / "actual-generated-root" / "evidence.txt").read_text() == "preserved"
    assert not (run_dir / "outputs" / "never").exists()
    assert json.loads((run_dir / "result.json").read_text())["exit_code"] == 3
    before = (run_dir / "result.json").read_bytes()
    with pytest.raises(ValidationError, match="new"):
        run_job(job, run_dir, repo_root=tmp_path, python_executable=sys.executable)
    assert (run_dir / "result.json").read_bytes() == before


@pytest.mark.skipif(os.name == "nt", reason="Windows encodes native termination as a positive status")
def test_negative_native_exit_cannot_be_success(tmp_path):
    result = execute_command([sys.executable, "-c", "import os,signal;os.kill(os.getpid(),signal.SIGTERM)"], cwd=tmp_path, log_path=tmp_path / "signal.log", stderr=io.StringIO())
    assert result["returncode"] < 0 and result["state"] == "failed"


def test_status_reader_and_cancel_poll_do_not_corrupt_atomic_updates(tmp_path):
    from application.automation.runner import atomic_json, _runner_identity
    status = {"state": "running", "run_id": "polling-run", **_runner_identity()}
    atomic_json(tmp_path / "status.json", status)
    errors = []
    finished = threading.Event()
    def reader():
        try:
            while not finished.is_set():
                assert read_status(tmp_path)["run_id"] == "polling-run"
                request_cancel(tmp_path)
                assert json.loads((tmp_path / "cancel.request.json").read_text())["run_id"] == "polling-run"
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for number in range(20):
            atomic_json(tmp_path / "status.json", {**status, "sequence": number})
    finally:
        finished.set()
        thread.join(timeout=5)
    assert not errors
    assert not thread.is_alive()
    assert read_status(tmp_path)["sequence"] == 19


@pytest.mark.skipif(os.name != "nt", reason="Windows readers deny file replacement while their handle is open")
def test_atomic_status_write_retries_real_windows_reader_lock(tmp_path):
    from application.automation.runner import atomic_json
    path = tmp_path / "status.json"
    atomic_json(path, {"sequence": 0})
    errors = []
    def writer():
        try:
            atomic_json(path, {"sequence": 1})
        except Exception as exc:
            errors.append(exc)
    with path.open("r", encoding="utf-8"):
        thread = threading.Thread(target=writer)
        thread.start()
        time.sleep(.15)
        assert thread.is_alive()
    thread.join(timeout=5)
    assert not errors and not thread.is_alive()
    assert json.loads(path.read_text())["sequence"] == 1
