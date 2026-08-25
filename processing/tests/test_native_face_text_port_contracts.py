from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes | None]]:
    snapshot: dict[str, tuple[str, bytes | None]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            snapshot[relative] = ("file", path.read_bytes())
        elif path.is_dir():
            snapshot[relative] = ("directory", None)
        else:
            snapshot[relative] = ("other", None)
    return snapshot


def _make_windows_junction(link: Path, target: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction regression")
    completed = subprocess.run(
        [
            os.environ.get("ComSpec", "cmd.exe"),
            "/d",
            "/c",
            "mklink",
            "/J",
            str(link),
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        pytest.skip(
            "directory junction creation is unavailable: "
            + (completed.stderr or completed.stdout).strip()
        )
    assert link.is_junction()


def _run_without_site_packages(
    module: str, *arguments: str, cwd: Path
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
    return subprocess.run(
        [sys.executable, "-S", "-m", module, *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "module",
    ("processing.face_analysis", "processing.text_analysis"),
)
def test_native_cli_help_imports_without_optional_site_packages(
    module: str, tmp_path: Path
) -> None:
    completed = _run_without_site_packages(module, "--help", cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.casefold()


@pytest.mark.parametrize(
    "module",
    ("processing.face_analysis", "processing.text_analysis"),
)
def test_native_readiness_is_clear_and_publishes_nothing_when_dependencies_are_missing(
    module: str, tmp_path: Path
) -> None:
    completed = _run_without_site_packages(module, "--check", cwd=tmp_path)

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload.get("ready") is False or payload.get("status") == "not_ready"
    detail = str(payload.get("detail") or payload.get("error") or "")
    assert detail.strip()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("module", "input_kind"),
    (
        ("processing.face_analysis", "file"),
        ("processing.text_analysis", "directory"),
    ),
)
def test_normal_native_execution_fails_before_publishing_when_dependencies_are_missing(
    module: str, input_kind: str, tmp_path: Path
) -> None:
    input_path = tmp_path / ("input.mp4" if input_kind == "file" else "input")
    if input_kind == "file":
        input_path.write_bytes(b"not-a-real-video")
    else:
        input_path.mkdir()
        (input_path / "interview.mp4").write_bytes(b"not-a-real-video")
    output_root = tmp_path / "output"
    before = _tree_snapshot(tmp_path)

    completed = _run_without_site_packages(
        module,
        str(input_path),
        "--output-root",
        str(output_root),
        cwd=tmp_path,
    )

    assert completed.returncode == 1
    assert _tree_snapshot(tmp_path) == before


def test_text_pipeline_cli_rejects_a_windows_junction_before_stage_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from processing.text_analysis import __main__ as text_cli
    from processing.text_analysis import pipeline

    input_path = tmp_path / "input"
    input_path.mkdir()
    (input_path / "interview.mp4").write_bytes(b"media")
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    linked_output = tmp_path / "linked-output"
    _make_windows_junction(linked_output, real_output)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        pipeline,
        "check_text_processing_readiness",
        lambda *_args, **_kwargs: {"status": "ready"},
    )
    monkeypatch.setattr(
        pipeline,
        "_run",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("stage dispatch reached")),
    )

    assert text_cli.main(
        [str(input_path), "--output-root", str(linked_output), "--to-stage", "transcribe"]
    ) == 1

    captured = capsys.readouterr()
    assert "symbolic link, junction, or reparse" in captured.err
    assert list(real_output.iterdir()) == []


def test_transcribe_entrypoint_rejects_a_windows_junction_before_lock_or_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from processing.text_analysis.transcribe import transcribe

    video = tmp_path / "interview.mp4"
    video.write_bytes(b"media")
    real_output = tmp_path / "real-transcripts"
    real_output.mkdir()
    linked_output = tmp_path / "linked-transcripts"
    _make_windows_junction(linked_output, real_output)
    monkeypatch.setattr(transcribe, "configure_ffmpeg_shared_libraries", lambda: None)
    monkeypatch.setattr(transcribe, "_resolve_device", lambda _device: "cpu")
    monkeypatch.setattr(
        transcribe,
        "collect_whisper_execution_identity",
        lambda _model: {
            "engine": {"distribution": "openai-whisper", "version": "test"},
            "checkpoint": {
                "requested_name": "small",
                "filename": "small.pt",
                "expected_sha256": "a" * 64,
                "hash_source": "openai_whisper_model_registry",
            },
            "runtime": {"torch_version": "test", "ffmpeg_version": "test"},
        },
    )
    monkeypatch.setattr(
        transcribe,
        "_load_whisper_model",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("model load reached")),
    )

    with pytest.raises(ValueError, match="symbolic link, junction, or reparse"):
        transcribe.main([str(video), "--output-dir", str(linked_output)])

    assert list(real_output.iterdir()) == []


def test_prepare_entrypoint_rejects_a_windows_junction_before_lock_or_manifest(
    tmp_path: Path,
) -> None:
    from processing.text_analysis.prepare_input import whisper_to_rocksteady

    source = tmp_path / "transcript.json"
    source.write_text(
        json.dumps({"segments": [{"id": 0, "text": "hello"}]}),
        encoding="utf-8",
    )
    real_output = tmp_path / "real-prepared"
    real_output.mkdir()
    linked_output = tmp_path / "linked-prepared"
    _make_windows_junction(linked_output, real_output)

    with pytest.raises(ValueError, match="symbolic link, junction, or reparse"):
        whisper_to_rocksteady.main([str(source), "--output", str(linked_output)])

    assert list(real_output.iterdir()) == []


def test_rocksteady_entrypoint_rejects_a_windows_junction_before_job_discovery(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from processing.text_analysis.rocksteady_adapter import runner

    video = tmp_path / "input" / "UK" / "Example Speaker" / "Interview_001"
    video.mkdir(parents=True)
    (video / "Interview_001__segment_000001.txt").write_text("hello", encoding="utf-8")
    real_output = tmp_path / "real-rocksteady"
    real_output.mkdir()
    linked_output = tmp_path / "linked-rocksteady"
    _make_windows_junction(linked_output, real_output)

    with pytest.raises(SystemExit) as error:
        runner.main([str(tmp_path / "input"), "--output-root", str(linked_output)])

    assert error.value.code == 2
    assert "symbolic link, junction, or reparse" in capsys.readouterr().err
    assert list(real_output.iterdir()) == []


def test_text_defaults_and_runtime_names_are_project_neutral(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from processing.text_analysis.pipeline import (
        CORE_CATEGORIES,
        TextProcessingConfig,
        _effective_rocksteady_categories,
    )
    from processing.text_analysis.rocksteady_adapter import runner

    defaults = TextProcessingConfig()
    privileged_fragment = "poli" + "t"
    assert all(privileged_fragment not in category.casefold() for category in CORE_CATEGORIES)
    assert all(privileged_fragment not in category.casefold() for category in defaults.categories)
    assert all(
        privileged_fragment not in category.casefold()
        for category in _effective_rocksteady_categories(("Research Theme",))
    )
    assert _effective_rocksteady_categories(("Research Theme",))[-1] == "Research Theme"
    assert defaults.postprocessing_root.startswith("analysis/")
    assert "preprocessing" not in defaults.input_path
    assert runner.MAIN_CLASS == "ie.tcd.multimodal.rocksteady.RockSteadyCli"
    assert runner.ROCKSTEADY_CACHE_OWNER.startswith("multimodal-emotion-analysis-")
    assert runner.ROCKSTEADY_HISTORY_OWNER.startswith("multimodal-emotion-analysis-")

    configured = tmp_path / "rocksteady"
    monkeypatch.setenv("MULTIMODAL_EMOTION_ROCKSTEADY_HOME", str(configured))
    assert runner.resolve_rocksteady_home(None) == configured.resolve()


def test_text_transcription_identity_serializes_optional_source_id(tmp_path: Path) -> None:
    from processing.text_analysis.transcribe.transcribe import (
        TranscriptionJob,
        _transcription_record,
    )

    source = tmp_path / "video.mp4"
    source.write_bytes(b"media")
    job = TranscriptionJob(
        source=source,
        output_stem=Path("Researcher/Interview_001"),
        source_relative="Researcher/Interview_001.mp4",
        source_id="SRC-001",
    )

    record = _transcription_record(job, {}, tmp_path, status="planned")

    assert record["identity"] == "Researcher/Interview_001"
    assert record["source_id"] == "SRC-001"


def test_text_source_id_flows_through_selection_and_prepare_manifests(tmp_path: Path) -> None:
    from processing.text_analysis.prepare_input.integrity import PREPARE_MANIFEST
    from processing.text_analysis.prepare_input.whisper_to_rocksteady import (
        PreparedSegment,
        replace_segment_directory,
    )
    from processing.text_analysis.selection import (
        SELECTION_MANIFEST,
        build_selected_whisper_tree,
    )

    whisper_root = tmp_path / "whisper"
    transcript = whisper_root / "eng" / "Researcher" / "Interview_001.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {
                "source_id": "SRC-001",
                "segments": [{"id": 0, "start": 0.0, "end": 1.0, "text": "Hello"}],
            }
        ),
        encoding="utf-8",
    )
    selected_root = tmp_path / "selected"

    assert build_selected_whisper_tree(whisper_root, selected_root) == 1
    selection = json.loads((selected_root / SELECTION_MANIFEST).read_text(encoding="utf-8"))
    assert selection["files"][0]["source_id"] == "SRC-001"

    prepared = tmp_path / "prepared" / "Researcher" / "Interview_001"
    replace_segment_directory(
        prepared,
        "Interview_001",
        [PreparedSegment(1, 0, 0, "Hello")],
        video_identity="Researcher/Interview_001",
        source_id="SRC-001",
    )
    prepare_manifest = json.loads((prepared / PREPARE_MANIFEST).read_text(encoding="utf-8"))
    assert prepare_manifest["source_id"] == "SRC-001"


def test_spreadsheet_value_keeps_strict_signed_numbers_and_neutralizes_attacks() -> None:
    from spreadsheet_safety import neutralize_spreadsheet_value

    assert neutralize_spreadsheet_value("-42") == "-42"
    assert neutralize_spreadsheet_value("+3.5e-2") == "+3.5e-2"
    assert neutralize_spreadsheet_value(" =SUM(A1:A2)") == "' =SUM(A1:A2)"
    assert neutralize_spreadsheet_value("@malicious") == "'@malicious"
    assert neutralize_spreadsheet_value("\n=SUM(A1:A2)") == "'\n=SUM(A1:A2)"
    assert neutralize_spreadsheet_value("\ufeff\t@malicious") == "'\ufeff\t@malicious"
