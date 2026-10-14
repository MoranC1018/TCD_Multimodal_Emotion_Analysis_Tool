"""Exercise real Python pipes without loading Whisper or starting the desktop UI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from application.launcher import child_process_environment
from procurement.external_tools import credential_free_media_environment


REPO_ROOT = Path(__file__).resolve().parents[3]
MULTILINGUAL_TEXT = "Zażółć gęślą jaźń — łódź / français / 中文"
MULTILINGUAL_ARGUMENT = "Zażółć_łódź_français_中文"
MEDIA_CREDENTIALS = (
    "YOUTUBE_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN",
)


def legacy_environment() -> dict[str, str]:
    environment = credential_free_media_environment()
    environment.update(
        PYTHONIOENCODING="cp1252:strict",
        PYTHONUTF8="0",
        PYTHONUNBUFFERED="0",
    )
    return environment


def run_child(command: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess:
    # Capture bytes first so an encoding regression fails an assertion, rather
    # than concealing the original error in the parent's decoding exception.
    return subprocess.run(
        command, cwd=REPO_ROOT, env=environment, capture_output=True,
        timeout=30, check=False,
    )


def logging_child_code(exit_code: int = 0) -> str:
    return (
        "import json, os, sys; "
        f"print(json.dumps({{'text': {MULTILINGUAL_TEXT!r}, "
        f"'credentials': [name for name in {MEDIA_CREDENTIALS!r} if name in os.environ]}}, "
        "ensure_ascii=False)); "
        f"print('stderr: ' + {MULTILINGUAL_TEXT!r}, file=sys.stderr); "
        f"sys.exit({exit_code})"
    )


def test_launcher_child_round_trips_stdout_stderr_without_credentials() -> None:
    command = [sys.executable, "-B", "-c", logging_child_code()]
    inherited = legacy_environment()
    inherited.update({name: "synthetic-secret" for name in MEDIA_CREDENTIALS})

    completed = run_child(command, child_process_environment(command, base_environment=inherited))

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.decode("utf-8")) == {
        "text": MULTILINGUAL_TEXT, "credentials": [],
    }
    assert completed.stderr.decode("utf-8").splitlines() == ["stderr: " + MULTILINGUAL_TEXT]
    assert inherited["PYTHONIOENCODING"] == "cp1252:strict"
    assert all(inherited[name] == "synthetic-secret" for name in MEDIA_CREDENTIALS)


@pytest.mark.parametrize("exit_code", [0, 7])
def test_nested_text_child_preserves_multilingual_logs_and_failure_tail(
    tmp_path: Path, exit_code: int,
) -> None:
    command = [sys.executable, "-B", "-c", logging_child_code(exit_code)]
    # Only the outer stream is configured here. _run must configure the real
    # nested child and strip credentials itself, even under a legacy parent.
    outer_code = (
        "from pathlib import Path\n"
        "import sys\n"
        "from procurement.console import configure_utf8_stdio\n"
        "from processing.text_analysis.pipeline import _run\n"
        "configure_utf8_stdio()\n"
        "try:\n"
        f"    _run({command!r}, Path({str(tmp_path)!r}))\n"
        "except RuntimeError as exc:\n"
        "    print(str(exc), file=sys.stderr)\n"
        "    raise SystemExit(7)\n"
    )
    environment = legacy_environment()
    environment.update({name: "synthetic-secret" for name in MEDIA_CREDENTIALS})

    completed = run_child([sys.executable, "-B", "-c", outer_code], environment)

    assert completed.returncode == exit_code, completed.stderr
    lines = completed.stdout.decode("utf-8").splitlines()
    payloads = [json.loads(line) for line in lines if line.startswith("{")]
    assert payloads == [{"text": MULTILINGUAL_TEXT, "credentials": []}]
    assert "stderr: " + MULTILINGUAL_TEXT in lines
    diagnostic = completed.stderr.decode("utf-8")
    if exit_code:
        assert "Stage command failed with exit code 7" in diagnostic
        assert "Last output:" in diagnostic
        assert "stderr: " + MULTILINGUAL_TEXT in diagnostic
    else:
        assert diagnostic == ""


@pytest.mark.parametrize(
    "module",
    [
        "application.launcher",
        "processing.text_analysis",
        "processing.text_analysis.transcribe.transcribe",
        "processing.text_analysis.prepare_input.whisper_to_rocksteady",
        "processing.text_analysis.rocksteady_adapter",
        "analysis.text_pipeline.postprocess",
    ],
)
def test_direct_cli_preserves_multilingual_argument_errors(tmp_path: Path, module: str) -> None:
    # argparse treats unknown arguments containing spaces as positionals.
    arguments = ["--utf8-regression-unknown=" + MULTILINGUAL_ARGUMENT]
    # Prepare/transcribe acquire output locks before final argument validation.
    # Keep every such path in this test's own directory.
    if module.endswith("whisper_to_rocksteady"):
        arguments += [str(tmp_path / "unused-input"), "--output", str(tmp_path / "prepared")]
    elif module.endswith("transcribe.transcribe"):
        arguments += ["--output-dir", str(tmp_path / "transcripts")]

    completed = run_child([sys.executable, "-B", "-m", module, *arguments], legacy_environment())

    assert completed.returncode == 2, completed.stderr
    assert MULTILINGUAL_ARGUMENT.encode("utf-8") in completed.stderr
    diagnostic = completed.stderr.decode("utf-8")
    assert "unrecognized arguments:" in diagnostic
    assert "UnicodeEncodeError" not in diagnostic


@pytest.mark.parametrize("variant", ["original", "eng"])
def test_prepare_reuses_synthetic_saved_transcript_with_polish_output_path(
    tmp_path: Path, variant: str,
) -> None:
    # These are synthetic saved Whisper-format files, not Whisper inference.
    selected = tmp_path / variant
    source = selected / "PL/Synthetic Speaker/001_PL_Synthetic_Speaker_20250101.json"
    source.parent.mkdir(parents=True)
    text = MULTILINGUAL_TEXT if variant == "original" else "Synthetic English translation."
    source.write_text(
        json.dumps({"task": "transcribe", "segments": [{"id": 0, "text": text}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    original_bytes = source.read_bytes()
    original_mtime = source.stat().st_mtime_ns
    output = tmp_path / "przygotowane_ł"

    completed = run_child(
        [
            sys.executable, "-B", "-m",
            "processing.text_analysis.prepare_input.whisper_to_rocksteady",
            str(selected), "--output", str(output),
        ],
        legacy_environment(),
    )

    assert completed.returncode == 0, completed.stderr
    assert str(output).encode("utf-8") in completed.stdout
    assert "Done. 1 video(s) prepared" in completed.stdout.decode("utf-8")
    assert completed.stderr == b""
    prepared = list(output.rglob("*__segment_000001.txt"))
    assert len(prepared) == 1
    assert prepared[0].read_text(encoding="utf-8") == text
    assert source.read_bytes() == original_bytes
    assert source.stat().st_mtime_ns == original_mtime
