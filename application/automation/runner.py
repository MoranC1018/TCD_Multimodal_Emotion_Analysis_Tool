"""Foreground process ownership and durable, machine-readable run evidence."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from .config import Job, absolute_path, read_json, references, resolve_references
from .errors import CANCELLED, EXECUTION_ERROR, SUCCESS, TIMED_OUT, VALIDATION_ERROR, ValidationError

EXIT_BY_STATE = {"completed": SUCCESS, "failed": EXECUTION_ERROR, "cancelled": CANCELLED, "timed_out": TIMED_OUT, "validation_failed": VALIDATION_ERROR}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    from processing.io_utils import atomic_write_json
    target = absolute_path(path, Path.cwd())
    serializable = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False, default=str))
    atomic_write_json(target, serializable)


def _runner_identity() -> dict[str, Any]:
    import psutil
    return {"runner_pid": os.getpid(), "runner_create_time": psutil.Process().create_time()}


def read_status(run_dir: str | Path) -> dict[str, Any]:
    status = read_json(Path(run_dir) / "status.json", max_bytes=8 * 1024 * 1024)
    if not isinstance(status, dict) or not isinstance(status.get("run_id"), str):
        raise ValidationError("Directory does not contain valid automation run status.")
    if status.get("state") == "running":
        import psutil
        try:
            process = psutil.Process(status["runner_pid"])
            live = abs(process.create_time() - status["runner_create_time"]) < .01 and process.is_running()
        except (psutil.Error, KeyError, TypeError):
            live = False
        if not live:
            status = {**status, "recorded_state": "running", "state": "stale", "message": "The foreground runner is no longer alive; inspect logs/artifacts before retrying in a new run directory."}
    return status


def request_cancel(run_dir: str | Path) -> dict[str, Any]:
    directory = Path(run_dir)
    status = read_status(directory)
    if status.get("state") != "running":
        raise ValidationError("Only an active foreground run can receive a cancellation request.")
    request = {"run_id": status["run_id"], "requested_at": now()}
    atomic_json(directory / "cancel.request.json", request)
    return {"state": "cancel_requested", **request, "run_dir": str(directory.absolute())}


def execute_command(command: list[str], *, cwd: Path, log_path: Path,
                    timeout_seconds: float | None = None,
                    cancelled: Callable[[], bool] = lambda: False,
                    stderr: TextIO | None = None, resources: dict[str, Any] | None = None,
                    started: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Execute one literal argument list; only this function's child tree is owned."""
    from application import launcher

    destination = sys.stderr if stderr is None else stderr
    environment = launcher.child_process_environment(command)
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    if resources and resources["resourceLimitsEnabled"]:
        count = str(resources["nativeThreads"])
        for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "ONNX_NUM_THREADS", "ORT_NUM_THREADS", "MEA_NATIVE_THREADS"):
            environment[name] = count
    begin = time.monotonic()
    state = "running"
    process = None
    job_handle = None
    reader = None
    reader_errors: list[str] = []
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    with log_path.open("x", encoding="utf-8") as log:
        def write(message: str) -> None:
            with lock:
                if log.closed:
                    return
                log.write(message + "\n")
                log.flush()
                try:
                    destination.write(message + "\n")
                    destination.flush()
                except (BrokenPipeError, OSError):
                    pass

        def stop_owned() -> None:
            if process is None:
                return
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            launcher.terminate_process_tree(process)

        try:
            process = subprocess.Popen(command, cwd=str(cwd), env=environment,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace", bufsize=1,
                                       start_new_session=os.name != "nt",
                                       creationflags=0x00000004 if os.name == "nt" else 0)  # CREATE_SUSPENDED
            job_handle = launcher.assign_process_to_kill_job(process)
            if os.name == "nt" and not job_handle:
                raise RuntimeError(
                    "Unable to establish Windows Job Object ownership; the engine was not started. "
                    "Run the CLI from a host or scheduler that permits child Job Objects, then retry in a new run directory."
                )
            if started:
                started(process.pid)

            def drain() -> None:
                try:
                    assert process is not None and process.stdout is not None
                    for line in process.stdout:
                        write(line.rstrip("\r\n"))
                except Exception as exc:
                    reader_errors.append(str(exc))

            reader = threading.Thread(target=drain, daemon=True, name=f"automation-output-{process.pid}")
            reader.start()
            if os.name == "nt":
                import psutil
                psutil.Process(process.pid).resume()
            if resources:
                launcher.configure_process_resources(process, resources, logger=write)
            while process.poll() is None:
                if cancelled():
                    state = "cancelled"
                    stop_owned()
                    break
                if timeout_seconds is not None and time.monotonic() - begin >= timeout_seconds:
                    state = "timed_out"
                    stop_owned()
                    break
                if reader_errors:
                    stop_owned()
                    break
                time.sleep(.05)
            returncode = process.wait()
            if state == "running":
                if returncode in {130, -signal.SIGINT, 0xC000013A, -1073741510} and not reader_errors:
                    state = "cancelled"
                else:
                    state = "completed" if returncode == 0 and not reader_errors else "failed"
        except KeyboardInterrupt:
            state = "cancelled"
            stop_owned()
            returncode = process.poll() if process is not None else None
        except Exception as exc:
            write(f"Execution error: {exc}")
            state = "failed"
            stop_owned()
            returncode = process.poll() if process is not None else None
            reader_errors.append(str(exc))
        finally:
            if job_handle:
                launcher.close_windows_handle(job_handle)
            elif os.name != "nt" and process is not None:
                # The session belongs to this child even if its root exited first.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if reader:
                reader.join(timeout=10)
                if reader.is_alive():
                    state = "failed"
                    reader_errors.append("Child output pipe did not close after process termination.")
            if process is not None and process.stdout is not None and not (reader and reader.is_alive()):
                process.stdout.close()
            if reader_errors and state == "completed":
                state = "failed"
    return {"state": state, "returncode": returncode, "duration_seconds": round(time.monotonic() - begin, 3),
            "log_path": str(log_path), **({"errors": reader_errors} if reader_errors else {})}


def _build(job: Job, step, directory: Path, outputs: dict, repo_root: Path, python_executable: str, *, dry_run: bool):
    from .stages import build_stage
    options = resolve_references(step.options, outputs)
    options.setdefault("output_root", str(directory / "outputs" / step.id))
    return build_stage(step.stage, options, resolve_references(step.native_options, outputs),
                       base_dir=job.base_dir, repo_root=repo_root, python_executable=python_executable,
                       workspace=directory / "steps" / step.id, dry_run=dry_run)


def _overlap(left: Path, right: Path) -> bool:
    if left == right or left.is_relative_to(right) or right.is_relative_to(left):
        return True
    try:
        return left.samefile(right)
    except FileNotFoundError:
        return False


def _validate_outputs(job: Job, step_id: str, directory: Path, plan, *, protected_inputs=(), protected_outputs=()) -> None:
    """Protect source/configuration/evidence and earlier artifacts across every output."""
    paths = [plan.output_root, *plan.details.get("output_paths", [])]
    inputs = [job.source, *plan.details.get("input_paths", []), *protected_inputs]
    guarded_inputs = [absolute_path(value, job.base_dir) for value in inputs]
    guarded_prior = [absolute_path(value, job.base_dir) for value in protected_outputs]
    own_output_area = directory / "outputs" / step_id
    for value in paths:
        output = absolute_path(value, job.base_dir)
        if directory.is_relative_to(output) or (output.is_relative_to(directory) and not output.is_relative_to(own_output_area)):
            raise ValidationError(f"Engine output conflicts with protected run evidence or another step: {output}")
        if any(_overlap(output, source) for source in guarded_inputs):
            raise ValidationError(f"Engine output overlaps a protected input or job file: {output}")
        if any(_overlap(output, previous) for previous in guarded_prior):
            raise ValidationError(f"Engine output overlaps an earlier step's protected artifacts: {output}")


def plan_job(job: Job, run_dir: str | Path, *, repo_root: Path, python_executable: str) -> dict[str, Any]:
    directory = absolute_path(run_dir, Path.cwd())
    if directory.exists():
        raise ValidationError(f"Run directory must be new: {directory}")
    steps = []
    plans = []
    for step in job.steps:
        dependencies = sorted(set(references(step.options)) | set(references(step.native_options)))
        if dependencies:
            steps.append({"id": step.id, "stage": step.stage, "state": "deferred", "depends_on": dependencies,
                          "options": step.options, "native_options": step.native_options})
            continue
        plan = _build(job, step, directory, {}, repo_root, python_executable, dry_run=True)
        output = Path(plan.output_root)
        plans.append((step.id, plan))
        steps.append({"id": step.id, "stage": step.stage, "state": "planned", "command": plan.command,
                      "output_root": str(output), "details": plan.details})
    all_inputs = [value for _, plan in plans for value in plan.details.get("input_paths", [])]
    prior_outputs = []
    for step_id, plan in plans:
        _validate_outputs(job, step_id, directory, plan, protected_inputs=all_inputs, protected_outputs=prior_outputs)
        prior_outputs.extend([str(plan.output_root), *plan.details.get("output_paths", [])])
    return {"schema_version": 1, "state": "dry_run", "run_dir": str(directory), "job_file": str(job.source),
            "resources": job.resources, "timeout_seconds": job.timeout_seconds, "steps": steps}


def run_job(job: Job, run_dir: str | Path, *, repo_root: Path, python_executable: str,
            timeout_seconds: float | None = None, stderr: TextIO | None = None) -> tuple[dict[str, Any], int]:
    preview = plan_job(job, run_dir, repo_root=repo_root, python_executable=python_executable)
    limit = timeout_seconds if timeout_seconds is not None else job.timeout_seconds
    preview["timeout_seconds"] = limit
    directory = Path(preview["run_dir"])
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise ValidationError(f"Cannot create exclusive run directory {directory}: {exc}") from exc
    begin = time.monotonic()
    status = {"schema_version": 1, "run_id": uuid.uuid4().hex, "state": "running", "run_dir": str(directory),
              "started_at": now(), "job_file": str(job.source), "timeout_seconds": limit, **_runner_identity(),
              "steps": [{"id": step.id, "stage": step.stage, "state": "pending"} for step in job.steps]}
    atomic_json(directory / "submitted.json", job.submitted)
    atomic_json(directory / "effective.json", preview)
    atomic_json(directory / "status.json", status)
    outputs: dict[str, dict[str, Any]] = {}
    protected_outputs: list[str] = []
    protected_inputs = [value for item in preview["steps"] for value in item.get("details", {}).get("input_paths", [])]

    def cancellation_requested() -> bool:
        path = directory / "cancel.request.json"
        if not path.exists():
            return False
        try:
            return read_json(path).get("run_id") == status["run_id"]
        except (ValidationError, AttributeError):
            return False

    try:
        for step, entry in zip(job.steps, status["steps"]):
            if cancellation_requested():
                status["state"] = "cancelled"
                break
            remaining = None if limit is None else limit - (time.monotonic() - begin)
            if remaining is not None and remaining <= 0:
                status["state"] = "timed_out"
                break
            plan = _build(job, step, directory, outputs, repo_root, python_executable, dry_run=False)
            _validate_outputs(job, step.id, directory, plan, protected_inputs=protected_inputs, protected_outputs=protected_outputs)
            # Source inspection and command preparation count against an active
            # run's deadline, even when they take longer than a process launch.
            remaining = None if limit is None else limit - (time.monotonic() - begin)
            if cancellation_requested():
                status["state"] = "cancelled"
                break
            if remaining is not None and remaining <= 0:
                status["state"] = "timed_out"
                break
            entry.update(state="running", command=plan.command, output_root=str(plan.output_root), started_at=now(), details=plan.details)
            atomic_json(directory / "effective.json", {**preview, "state": "running", "steps": status["steps"]})
            atomic_json(directory / "status.json", status)
            def record_pid(pid):
                entry["child_pid"] = pid
                atomic_json(directory / "status.json", status)
            timeout = min(remaining, step.timeout_seconds) if remaining is not None and step.timeout_seconds is not None else remaining if remaining is not None else step.timeout_seconds
            result = execute_command(plan.command, cwd=repo_root, log_path=directory / "logs" / f"{step.id}.log",
                                     timeout_seconds=timeout, cancelled=cancellation_requested, stderr=stderr,
                                     resources=job.resources, started=record_pid)
            entry.update(result, finished_at=now())
            if result["state"] != "completed":
                status["state"] = result["state"]
                break
            outputs[step.id] = {"output_root": str(plan.output_root)}
            protected_outputs.extend([str(plan.output_root), *plan.details.get("output_paths", [])])
            atomic_json(directory / "status.json", status)
        else:
            status["state"] = "completed"
    except KeyboardInterrupt:
        status["state"] = "cancelled"
    except (ValidationError, ValueError) as exc:
        status.update(state="validation_failed", error=str(exc))
    except Exception as exc:
        status.update(state="failed", error=str(exc))
    status.update(finished_at=now(), duration_seconds=round(time.monotonic() - begin, 3), outputs=outputs)
    code = EXIT_BY_STATE[status["state"]]
    status["exit_code"] = code
    atomic_json(directory / "status.json", status)
    atomic_json(directory / "effective.json", {**preview, "state": status["state"], "steps": status["steps"]})
    atomic_json(directory / "result.json", status)
    return status, code
