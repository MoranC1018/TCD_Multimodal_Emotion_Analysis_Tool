from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from procurement.procurement_beta import runner as runner_module
from procurement.procurement_beta.intervals import Interval
from procurement.procurement_beta.pipeline import ProcurementBetaOptions
from procurement.procurement_beta.runner import (
    DetectionResult,
    VideoWorkItem,
    concat_file_line,
    find_cached_result,
    output_directory_for_item,
    process_video_file,
    segment_cut_command,
    ignore_gap_validation_failures,
    trim_segment_for_stitching,
    write_run_manifest,
)



@pytest.fixture(autouse=True)
def skip_live_resource_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runner tests cover orchestration, not the host machine's current load."""

    monkeypatch.setattr(runner_module, "wait_for_resource_headroom", lambda **_kwargs: None)


class FakeFaceAnalyzer:
    def analyze(self, video_path: Path, output_dir: Path, options: ProcurementBetaOptions) -> DetectionResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "still_001.jpg").write_bytes(b"fake jpg")
        return DetectionResult(
            intervals=[Interval(0, 80, 0.9)],
            method="fake-face",
            artifacts=[output_dir / "still_001.jpg"],
            warnings=[],
        )


class FakeValidatingFaceAnalyzer(FakeFaceAnalyzer):
    def validate_segments(
        self,
        video_path: Path,
        output_dir: Path,
        candidate_intervals: list[Interval],
        options: ProcurementBetaOptions,
    ) -> DetectionResult:
        (output_dir / "face_segment_validation.json").write_text("{}", encoding="utf-8")
        return DetectionResult(
            intervals=[Interval(10, 30, 0.9), Interval(40, 70, 0.9)],
            method="fake-validation",
            artifacts=[output_dir / "face_segment_validation.json"],
            warnings=["validated"],
        )

class FakeReviewingFaceAnalyzer(FakeFaceAnalyzer):
    def validate_stitched_output(
        self,
        video_path: Path,
        output_dir: Path,
        options: ProcurementBetaOptions,
    ) -> dict[str, object]:
        artifact = output_dir / "stitched_identity_validation.json"
        payload: dict[str, object] = {
            "available": True,
            "failure_count": 1,
            "failures": [{"reason": "validator could not map this sampled failure"}],
            "artifact": str(artifact),
        }
        artifact.write_text(json.dumps(payload), encoding="utf-8")
        return payload


class FakeNoCleanFaceAnalyzer:
    def analyze(self, video_path: Path, output_dir: Path, options: ProcurementBetaOptions) -> DetectionResult:
        return DetectionResult(intervals=[], method="fake-face-empty", artifacts=[], warnings=[])


class FakeVoiceAnalyzer:
    def analyze(self, video_path: Path, output_dir: Path, options: ProcurementBetaOptions) -> DetectionResult:
        return DetectionResult(
            intervals=[Interval(10, 70, 0.8)],
            method="fake-voice",
            artifacts=[],
            warnings=[],
        )


def test_process_video_file_writes_auditable_outputs_and_stitches_selected_segments(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    stitched_calls: list[tuple[Path, list[Interval], float]] = []

    def fake_stitcher(video_path: Path, target_path: Path, segments: list[Interval], gap_seconds: float) -> None:
        stitched_calls.append((target_path, segments, gap_seconds))
        target_path.write_bytes(b"stitched")

    result = process_video_file(
        VideoWorkItem(
            speaker="Speaker One",
            title="A long interview",
            source_path=source_video,
            youtube_url="",
            video_id="abc123",
            duration_seconds=100,
        ),
        run_root=tmp_path / "run",
        options=ProcurementBetaOptions(
            output_mode="clean",
            percentage=0.10,
            min_clean_seconds=10,
            max_segment_seconds=30,
            gap_seconds=1.5,
            identity_stills=20,
            scan_fps=1,
            face_confidence=0.65,
            speaker_confidence=0.65,
            worker_count=2,
            device="cpu",
            keep_debug=True,
        ),
        face_analyzer=FakeFaceAnalyzer(),
        voice_analyzer=FakeVoiceAnalyzer(),
        stitcher=fake_stitcher,
    )

    assert result.status == "ok"
    assert result.output_video.name == "stitched_imotions.mp4"
    assert (result.output_dir / "identity_stills" / "still_001.jpg").exists()
    assert (result.output_dir / "face_visibility_intervals.json").exists()
    assert (result.output_dir / "voice_activity_intervals.csv").exists()
    assert (result.output_dir / "clean_overlap_segments.json").exists()
    assert (result.output_dir / "selected_segments.json").exists()
    assert stitched_calls == [
        (
            result.output_video,
            [Interval(10, 70, 0.8)],
            1.5,
        )
    ]




def test_process_video_file_skips_final_validation_by_default(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")

    result = process_video_file(
        VideoWorkItem("Speaker One", "A long interview", source_video, "", "abc123", 100),
        run_root=tmp_path / "run",
        options=ProcurementBetaOptions("clean", 0.10, 10, 30, 1.5, 20, 1, 0.65, 0.65, 2, "cpu", True),
        face_analyzer=FakeReviewingFaceAnalyzer(),
        voice_analyzer=FakeVoiceAnalyzer(),
        stitcher=lambda _source, target, _segments, _gap: target.write_bytes(b"stitched"),
    )

    manifest = json.loads((result.output_dir / "clean_speaker_beta_manifest.json").read_text(encoding="utf-8"))

    assert result.status == "ok"
    assert manifest["stitched_output_validation"]["skipped"] is True
    assert not (result.output_dir / "stitched_identity_validation.json").exists()

def test_process_video_file_marks_final_validation_failures_for_review(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")

    result = process_video_file(
        VideoWorkItem("Speaker One", "A long interview", source_video, "", "abc123", 100),
        run_root=tmp_path / "run",
        options=ProcurementBetaOptions("clean", 0.10, 10, 30, 1.5, 20, 1, 0.65, 0.65, 2, "cpu", True, skip_final_output_validation=False),
        face_analyzer=FakeReviewingFaceAnalyzer(),
        voice_analyzer=FakeVoiceAnalyzer(),
        stitcher=lambda _source, target, _segments, _gap: target.write_bytes(b"stitched"),
    )

    manifest = json.loads((result.output_dir / "clean_speaker_beta_manifest.json").read_text(encoding="utf-8"))

    assert result.status == "needs_review"
    assert manifest["status"] == "needs_review"
    assert manifest["stitched_output_validation"]["failure_count"] == 1
    assert manifest["timings_seconds"]["stitched_output_validation"] >= 0





def test_process_video_file_reuses_cut_clips_after_mapped_final_validation_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    commands: list[list[str]] = []

    def fake_run_command(command: list[str]) -> None:
        commands.append(command)
        output_path = Path(command[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"video")

    class ThreeSegmentFaceAnalyzer(FakeFaceAnalyzer):
        def analyze(self, video_path: Path, output_dir: Path, options: ProcurementBetaOptions) -> DetectionResult:
            output_dir.mkdir(parents=True, exist_ok=True)
            return DetectionResult(
                intervals=[Interval(0, 20, 0.9), Interval(30, 50, 0.9), Interval(60, 80, 0.9)],
                method="fake-face",
                artifacts=[],
                warnings=[],
            )

        def validate_stitched_output(
            self,
            video_path: Path,
            output_dir: Path,
            options: ProcurementBetaOptions,
        ) -> dict[str, object]:
            artifact = output_dir / "stitched_identity_validation.json"
            call_count = getattr(self, "call_count", 0) + 1
            self.call_count = call_count
            if call_count == 1:
                payload: dict[str, object] = {
                    "available": True,
                    "failure_count": 1,
                    "failure_timestamps": [20.0],
                    "failures": [{"timestamp": 20.0, "reason": "mapped to second clip"}],
                    "artifact": str(artifact),
                }
            else:
                payload = {"available": True, "failure_count": 0, "failures": [], "artifact": str(artifact)}
            artifact.write_text(json.dumps(payload), encoding="utf-8")
            return payload

    class WideVoiceAnalyzer(FakeVoiceAnalyzer):
        def analyze(self, video_path: Path, output_dir: Path, options: ProcurementBetaOptions) -> DetectionResult:
            return DetectionResult([Interval(0, 90, 0.9)], "fake-voice", [], [])

    face_analyzer = ThreeSegmentFaceAnalyzer()
    monkeypatch.setattr(runner_module, "run_command", fake_run_command)

    result = process_video_file(
        VideoWorkItem("Speaker One", "A long interview", source_video, "", "abc123", 100),
        run_root=tmp_path / "run",
        options=ProcurementBetaOptions("clean", 0.10, 10, 30, 0, 20, 1, 0.65, 0.65, 1, "cpu", False, skip_final_output_validation=False),
        face_analyzer=face_analyzer,
        voice_analyzer=WideVoiceAnalyzer(),
        stitcher=runner_module.stitch_with_ffmpeg,
    )

    manifest = json.loads((result.output_dir / "clean_speaker_beta_manifest.json").read_text(encoding="utf-8"))
    segment_cut_commands = [command for command in commands if "-t" in command]
    concat_commands = [command for command in commands if "concat" in command]

    assert result.status == "ok"
    assert face_analyzer.call_count == 2
    assert len(segment_cut_commands) == 3
    assert len(concat_commands) == 2
    assert manifest["stitched_output_validation"]["failure_count"] == 0
    assert manifest["stitched_output_repair_history"][0]["failure_count"] == 1
    assert manifest["segment_plan"]["rejected_segments"][-1]["reason"] == "removed_by_final_output_validation"
    assert len(manifest["segment_plan"]["selected_segments"]) == 2


def test_remove_failed_stitched_segments_uses_compact_failure_timestamps() -> None:
    segments = [Interval(0, 20), Interval(30, 50), Interval(60, 80)]
    validation = {"failure_count": 1, "failures": [], "failure_timestamps": [20.0]}

    repaired = runner_module.remove_failed_stitched_segments(segments, validation, gap_seconds=0)

    assert repaired == [segments[0], segments[2]]


def test_trim_segment_for_stitching_does_not_shorten_default_minimum_clip() -> None:
    assert trim_segment_for_stitching(Interval(0, 10, 0.9)) == Interval(0, 10, 0.9)
    assert trim_segment_for_stitching(Interval(0, 12, 0.9)) == Interval(0, 12, 0.9)

def test_process_video_file_reports_no_clean_when_final_validation_rejects_every_segment(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")

    class RejectingFaceAnalyzer(FakeFaceAnalyzer):
        def validate_stitched_output(
            self,
            video_path: Path,
            output_dir: Path,
            options: ProcurementBetaOptions,
        ) -> dict[str, object]:
            artifact = output_dir / "stitched_identity_validation.json"
            payload: dict[str, object] = {
                "available": True,
                "failure_count": 1,
                "failures": [{"timestamp": 1.0}],
                "artifact": str(artifact),
            }
            artifact.write_text(json.dumps(payload), encoding="utf-8")
            return payload

    result = process_video_file(
        VideoWorkItem("Speaker One", "A long interview", source_video, "", "abc123", 100),
        run_root=tmp_path / "run",
        options=ProcurementBetaOptions("clean", 0.10, 10, 30, 1.5, 20, 1, 0.65, 0.65, 2, "cpu", True, skip_final_output_validation=False),
        face_analyzer=RejectingFaceAnalyzer(),
        voice_analyzer=FakeVoiceAnalyzer(),
        stitcher=lambda _source, target, _segments, _gap: target.write_bytes(b"stitched"),
    )

    manifest = json.loads((result.output_dir / "clean_speaker_beta_manifest.json").read_text(encoding="utf-8"))

    assert result.status == "no_clean_segments"
    assert manifest["status"] == "no_clean_segments"
    assert manifest["message"] == "Final validation rejected every selected segment."
    assert manifest["segment_plan"]["selected_segments"] == []


def test_ignore_gap_validation_failures_keeps_real_segment_failures(tmp_path: Path) -> None:
    artifact = tmp_path / "stitched_identity_validation.json"
    validation = {
        "failure_count": 2,
        "failures": [{"timestamp": 1.0}, {"timestamp": 10.25}],
        "artifact": str(artifact),
    }

    updated = ignore_gap_validation_failures(validation, [Interval(0, 10), Interval(20, 30)], gap_seconds=2.0)
    saved = json.loads(artifact.read_text(encoding="utf-8"))

    assert updated is not None
    assert updated["failure_count"] == 1
    assert updated["failures"] == [{"timestamp": 1.0}]
    assert saved["ignored_failures"][0]["timestamp"] == 10.25
def test_process_video_file_runs_detectors_sequentially_by_default(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    calls: list[str] = []

    class RecordingFaceAnalyzer(FakeFaceAnalyzer):
        def analyze(self, video_path: Path, output_dir: Path, options: ProcurementBetaOptions) -> DetectionResult:
            calls.append("face")
            return super().analyze(video_path, output_dir, options)

    class RecordingVoiceAnalyzer(FakeVoiceAnalyzer):
        def analyze(self, video_path: Path, output_dir: Path, options: ProcurementBetaOptions) -> DetectionResult:
            calls.append("voice")
            return super().analyze(video_path, output_dir, options)

    result = process_video_file(
        VideoWorkItem("Speaker One", "A long interview", source_video, "", "abc123", 100),
        run_root=tmp_path / "run",
        options=ProcurementBetaOptions("clean", 0.10, 10, 30, 1.5, 20, 1, 0.65, 0.65, 2, "cpu", True),
        face_analyzer=RecordingFaceAnalyzer(),
        voice_analyzer=RecordingVoiceAnalyzer(),
        stitcher=lambda _source, target, _segments, _gap: target.write_bytes(b"stitched"),
    )

    assert result.status == "ok"
    assert calls == ["face", "voice"]
def test_process_video_file_replans_after_face_segment_validation(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")
    stitched_calls: list[list[Interval]] = []

    def fake_stitcher(video_path: Path, target_path: Path, segments: list[Interval], gap_seconds: float) -> None:
        stitched_calls.append(segments)
        target_path.write_bytes(b"stitched")

    result = process_video_file(
        VideoWorkItem("Speaker One", "A long interview", source_video, "", "abc123", 100),
        run_root=tmp_path / "run",
        options=ProcurementBetaOptions("clean", 0.10, 10, 30, 1.5, 20, 1, 0.65, 0.65, 2, "cpu", True),
        face_analyzer=FakeValidatingFaceAnalyzer(),
        voice_analyzer=FakeVoiceAnalyzer(),
        stitcher=fake_stitcher,
    )

    manifest = json.loads((result.output_dir / "clean_speaker_beta_manifest.json").read_text(encoding="utf-8"))

    assert result.status == "ok"
    assert stitched_calls == [[Interval(10, 30, 0.8), Interval(40, 70, 0.8)]]
    assert manifest["face_method"] == "fake-face+fake-validation"
    assert manifest["timings_seconds"]["face_segment_validation"] >= 0


def test_process_video_file_writes_no_clean_manifest_without_stitching(tmp_path: Path) -> None:
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"fake video")

    def fail_if_called(*_args) -> None:
        raise AssertionError("stitcher should not run when no clean segments exist")

    result = process_video_file(
        VideoWorkItem("Speaker One", "A long interview", source_video, "", "abc123", 100),
        run_root=tmp_path / "run",
        options=ProcurementBetaOptions("clean", 0.10, 10, 30, 1.5, 20, 1, 0.65, 0.65, 2, "cpu", True),
        face_analyzer=FakeNoCleanFaceAnalyzer(),
        voice_analyzer=FakeVoiceAnalyzer(),
        stitcher=fail_if_called,
    )

    manifest = json.loads((result.output_dir / "clean_speaker_beta_manifest.json").read_text(encoding="utf-8"))

    assert result.status == "no_clean_segments"
    assert manifest["status"] == "no_clean_segments"
    assert manifest["stitched_output_validation"] == {}

def test_find_cached_result_reuses_matching_manifest_without_reanalysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_module, "video_file_is_usable", lambda _path: True)
    item = VideoWorkItem(
        speaker="Speaker One",
        title="A long interview",
        source_path=tmp_path / "source.mp4",
        youtube_url="",
        video_id="abc123",
        duration_seconds=100,
    )
    item.source_path.write_bytes(b"video")
    options = ProcurementBetaOptions(
        output_mode="clean",
        percentage=0.10,
        min_clean_seconds=10,
        max_segment_seconds=30,
        gap_seconds=0,
        identity_stills=20,
        scan_fps=1,
        face_confidence=0.65,
        speaker_confidence=0.65,
        worker_count=2,
        device="cpu",
        keep_debug=False,
    )
    output_dir = output_directory_for_item(tmp_path / "cache", item)
    output_dir.mkdir(parents=True)
    output_video = output_dir / "stitched_imotions.mp4"
    output_video.write_bytes(b"cached")
    write_run_manifest(
        output_dir,
        item,
        options,
        DetectionResult([], "fake-face", [], []),
        DetectionResult([], "fake-voice", [], []),
        plan_with_no_segments(),
        output_video,
        "ok",
        "cached output",
    )
    manifest = json.loads((output_dir / "clean_speaker_beta_manifest.json").read_text(encoding="utf-8"))
    assert manifest["model_revisions"] == {
        "opencv_zoo": "47534e27c9851bb1128ccc0102f1145e27f23f98",
        "pyannote/speaker-diarization-3.1": "84fd25912480287da0247647c3d2b4853cb3ee5d",
        "speechbrain/spkrec-ecapa-voxceleb": "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286",
    }

    cached = find_cached_result(item, run_root=tmp_path / "cache", options=options)

    assert cached is not None
    assert cached.status == "cached"
    assert cached.output_video == output_video


def test_find_cached_result_rejects_oversized_manifest_before_parsing(tmp_path: Path) -> None:
    item = VideoWorkItem("Speaker One", "Interview", tmp_path / "source.mp4", "", "abc123", 100)
    options = ProcurementBetaOptions("clean", 0.10, 10, 30, 0, 20, 1, 0.65, 0.65, 2, "cpu", False)
    output_dir = output_directory_for_item(tmp_path / "cache", item)
    output_dir.mkdir(parents=True)
    (output_dir / "clean_speaker_beta_manifest.json").write_text(
        json.dumps({"padding": "x" * (1024 * 1024)}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="clean speaker manifest JSON exceeds 1048576 bytes"):
        find_cached_result(item, run_root=tmp_path / "cache", options=options)


def test_run_command_strips_credentials_from_ffmpeg_child(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(["ffmpeg"], 0, "", "")

    secret_names = ("YOUTUBE_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN")
    for name in secret_names:
        monkeypatch.setenv(name, f"secret-{name}")
    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)

    runner_module.run_command(["C:/trusted/ffmpeg.exe", "-version"])

    environment = captured.get("env")
    assert isinstance(environment, dict)
    assert all(name not in environment for name in secret_names)




def test_find_cached_result_includes_reference_audio_cache_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_module, "video_file_is_usable", lambda _path: True)
    item = VideoWorkItem("Speaker One", "A long interview", tmp_path / "source.mp4", "", "abc123", 100)
    item.source_path.write_bytes(b"video")
    options = ProcurementBetaOptions("clean", 0.10, 10, 30, 0, 20, 1, 0.65, 0.65, 2, "cpu", False)
    output_dir = output_directory_for_item(tmp_path / "cache", item)
    output_dir.mkdir(parents=True)
    output_video = output_dir / "stitched_imotions.mp4"
    output_video.write_bytes(b"cached")
    original_context = {"reference_audio": {"path": str(tmp_path / "speaker_a.wav"), "exists": True, "size": 10}}
    changed_context = {"reference_audio": {"path": str(tmp_path / "speaker_b.wav"), "exists": True, "size": 10}}
    write_run_manifest(
        output_dir,
        item,
        options,
        DetectionResult([], "fake-face", [], []),
        DetectionResult([], "fake-voice", [], []),
        plan_with_no_segments(),
        output_video,
        "ok",
        "cached output",
        cache_context=original_context,
    )

    assert find_cached_result(item, run_root=tmp_path / "cache", options=options, cache_context=original_context) is not None
    assert find_cached_result(item, run_root=tmp_path / "cache", options=options, cache_context=changed_context) is None


def test_find_cached_result_rejects_changed_source_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_module, "video_file_is_usable", lambda _path: True)
    item = VideoWorkItem("Speaker One", "Interview", tmp_path / "source.mp4", "", "abc123", 100)
    item.source_path.write_bytes(b"first")
    options = ProcurementBetaOptions("clean", 0.10, 10, 30, 0, 20, 1, 0.65, 0.65, 2, "cpu", False)
    output_dir = output_directory_for_item(tmp_path / "cache", item)
    output_dir.mkdir(parents=True)
    output_video = output_dir / "stitched_imotions.mp4"
    output_video.write_bytes(b"cached")
    write_run_manifest(
        output_dir,
        item,
        options,
        DetectionResult([], "face", [], []),
        DetectionResult([], "voice", [], []),
        plan_with_no_segments(),
        output_video,
        "ok",
        "cached",
    )
    item.source_path.write_bytes(b"replacement with a different size")

    assert find_cached_result(item, run_root=tmp_path / "cache", options=options) is None


def test_same_named_local_sources_without_video_ids_do_not_collide(tmp_path: Path) -> None:
    first = VideoWorkItem("Speaker", "Interview", tmp_path / "one" / "video.mp4", "", "", 10)
    second = VideoWorkItem("Speaker", "Interview", tmp_path / "two" / "video.mp4", "", "", 10)

    assert output_directory_for_item(tmp_path / "run", first) != output_directory_for_item(
        tmp_path / "run",
        second,
    )

def test_find_cached_result_rejects_needs_review_status(tmp_path: Path) -> None:
    item = VideoWorkItem("Speaker One", "A long interview", tmp_path / "source.mp4", "", "abc123", 100)
    item.source_path.write_bytes(b"video")
    options = ProcurementBetaOptions("clean", 0.10, 10, 30, 0, 20, 1, 0.65, 0.65, 2, "cpu", False)
    output_dir = output_directory_for_item(tmp_path / "cache", item)
    output_dir.mkdir(parents=True)
    write_run_manifest(
        output_dir,
        item,
        options,
        DetectionResult([], "fake-face", [], []),
        DetectionResult([], "fake-voice", [], []),
        plan_with_no_segments(),
        output_dir / "stitched_imotions.mp4",
        "needs_review",
        "Final validation found suspect frames.",
    )

    cached = find_cached_result(item, run_root=tmp_path / "cache", options=options)

    assert cached is None

def test_find_cached_result_rejects_no_clean_segment_status(tmp_path: Path) -> None:
    item = VideoWorkItem("Speaker One", "A long interview", tmp_path / "source.mp4", "", "abc123", 100)
    item.source_path.write_bytes(b"video")
    options = ProcurementBetaOptions("clean", 0.10, 10, 30, 0, 20, 1, 0.65, 0.65, 2, "cpu", False)
    output_dir = output_directory_for_item(tmp_path / "cache", item)
    output_dir.mkdir(parents=True)
    write_run_manifest(
        output_dir,
        item,
        options,
        DetectionResult([], "fake-face", [], []),
        DetectionResult([], "fake-voice", [], []),
        plan_with_no_segments(),
        output_dir / "stitched_imotions.mp4",
        "no_clean_segments",
        "No overlapping face and voice segments met the minimum duration.",
    )

    cached = find_cached_result(item, run_root=tmp_path / "cache", options=options)

    assert cached is None


def test_find_cached_result_ignores_old_manifest_without_pipeline_version(tmp_path: Path) -> None:
    item = VideoWorkItem("Speaker One", "A long interview", tmp_path / "source.mp4", "", "abc123", 100)
    item.source_path.write_bytes(b"video")
    options = ProcurementBetaOptions("clean", 0.10, 10, 30, 0, 20, 1, 0.65, 0.65, 2, "cpu", False)
    output_dir = output_directory_for_item(tmp_path / "cache", item)
    output_dir.mkdir(parents=True)
    (output_dir / "clean_speaker_beta_manifest.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "message": "old cache",
                "input": {"source_path": str(item.source_path)},
                "options": {
                    "output_mode": "clean",
                    "percentage": 0.10,
                    "min_clean_seconds": 10,
                    "max_segment_seconds": 30,
                    "gap_seconds": 0,
                    "identity_stills": 20,
                    "scan_fps": 1,
                    "face_confidence": 0.65,
                    "speaker_confidence": 0.65,
                    "worker_count": 2,
                    "device": "cpu",
                    "keep_debug": False,
                },
            }
        ),
        encoding="utf-8",
    )

    assert find_cached_result(item, run_root=tmp_path / "cache", options=options) is None


def test_concat_file_line_uses_absolute_paths_for_ffmpeg(tmp_path: Path) -> None:
    clip = tmp_path / "clips" / "clean segment 001.mp4"
    clip.parent.mkdir()
    clip.write_bytes(b"clip")

    line = concat_file_line(clip)

    assert line.startswith("file '")
    assert str(clip.resolve()).replace("\\", "/") in line


def test_segment_cut_command_uses_accurate_output_seek() -> None:
    command = segment_cut_command(Path("source.mp4"), Path("clip.mp4"), Interval(12.345, 30.345))
    seek_positions = [index for index, value in enumerate(command) if value == "-ss"]
    input_position = command.index("-i")

    assert seek_positions[0] < input_position < seek_positions[1]
    assert command[seek_positions[0] + 1] == "9.345"
    assert command[seek_positions[1] + 1] == "3.000"
    assert command[command.index("-t") + 1] == "18.000"


def plan_with_no_segments():
    from procurement.procurement_beta.pipeline import SegmentPlan

    return SegmentPlan([], [], [], [])
