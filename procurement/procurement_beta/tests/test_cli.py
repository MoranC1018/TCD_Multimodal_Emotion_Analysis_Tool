from __future__ import annotations

import json
import subprocess

from pathlib import Path

import pytest

from application import backend

from procurement.procurement_beta.cli import (
    cache_root_from_output_root,
    download_youtube_video,
    format_result_line,
    choose_random_video,
    normalise_video_id,
    options_from_args,
    prepare_work_item,
    read_json,
    run_child_process,
    select_videos,
    parse_args,
    summary_options_from_args,
    videos_from_source_input,
    youtube_format_fallback_selectors,
    youtube_format_selector,
)
from procurement.procurement_beta.runner import VideoRunResult



def make_video(video_id: str, *, speaker: str = "Speaker") -> backend.VideoItem:
    return backend.VideoItem(
        id=f"docx:{video_id}:0:1",
        title=f"Video {video_id}",
        speaker=speaker,
        source_path="input.docx",
        source_kind="docx",
        youtube_url=f"https://www.youtube.com/watch?v={video_id}",
        video_id=video_id,
    )
def test_cli_defaults_match_ui_expected_starting_values() -> None:
    args = parse_args(["--source", "videos", "--output-root", "out"])

    options = options_from_args(args)

    assert options.output_mode == "clean"
    assert options.percentage == 0.10
    assert options.min_clean_seconds == 10
    assert options.max_segment_seconds == 30
    assert options.gap_seconds == 0.5
    assert options.identity_stills == 20
    assert options.scan_fps == 1
    assert options.validation_fps == 4
    assert options.face_confidence == 0.65
    assert options.speaker_confidence == 0.65
    assert options.worker_count == 1
    assert options.device == "auto"
    assert options.keep_debug is False
    assert options.resource_guard_percent == 15
    assert options.resource_poll_seconds == 15
    assert options.resource_guard_timeout_seconds == 900
    assert options.parallel_detector_streams is False
    assert options.skip_final_output_validation is True
    assert args.max_download_height == 720
    assert args.isolated_video_processes is False
    assert args.skip_first_videos == 0
    assert args.skip_completed_outputs is False
    assert args.video_cooldown_seconds == 60
    assert args.max_affinity_cores == 2
    assert args.native_threads == 1
    assert args.cpu_throttle_high_percent == 95
    assert args.cpu_throttle_low_percent == 90
    assert args.ram_throttle_high_percent == 95
    assert args.ram_throttle_low_percent == 90

def test_cli_maps_explicit_beta_options() -> None:
    args = parse_args(
        [
            "--source",
            "videos",
            "--output-root",
            "out",
            "--output-mode",
            "percentage",
            "--percentage",
            "0.35",
            "--min-clean-seconds",
            "14",
            "--max-segment-seconds",
            "45",
            "--gap-seconds",
            "2",
            "--identity-stills",
            "12",
            "--scan-fps",
            "2",
            "--validation-fps",
            "3",
            "--max-download-height",
            "480",
            "--face-confidence",
            "0.8",
            "--speaker-confidence",
            "0.7",
            "--workers",
            "4",
            "--device",
            "cpu",
            "--keep-debug",
            "--resource-guard-percent",
            "12",
            "--resource-poll-seconds",
            "3",
            "--resource-guard-timeout-seconds",
            "120",
            "--isolated-video-processes",
            "--skip-first-videos",
            "12",
            "--skip-completed-outputs",
            "--video-cooldown-seconds",
            "45",
            "--max-affinity-cores",
            "2",
            "--native-threads",
            "1",
            "--cpu-throttle-high-percent",
            "96",
            "--cpu-throttle-low-percent",
            "91",
            "--ram-throttle-high-percent",
            "97",
            "--ram-throttle-low-percent",
            "92",
            "--parallel-detectors",
            "--run-final-output-validation",
            "--reference-face-dir",
            r"C:\profiles\faces",
        ]
    )

    options = options_from_args(args)

    assert options.output_mode == "percentage"
    assert options.percentage == 0.35
    assert options.min_clean_seconds == 14
    assert options.max_segment_seconds == 45
    assert options.gap_seconds == 2
    assert options.identity_stills == 12
    assert options.scan_fps == 2
    assert options.validation_fps == 3
    assert args.max_download_height == 480
    assert options.face_confidence == 0.8
    assert options.speaker_confidence == 0.7
    assert options.worker_count == 4
    assert options.device == "cpu"
    assert options.keep_debug is True
    assert options.resource_guard_percent == 12
    assert options.resource_poll_seconds == 3
    assert options.resource_guard_timeout_seconds == 120
    assert options.parallel_detector_streams is True
    assert options.skip_final_output_validation is False
    assert options.face_reference_dir == r"C:\profiles\faces"
    assert args.isolated_video_processes is True
    assert args.skip_first_videos == 12
    assert args.skip_completed_outputs is True
    assert args.video_cooldown_seconds == 45
    assert args.max_affinity_cores == 2
    assert args.native_threads == 1
    assert args.cpu_throttle_high_percent == 96
    assert args.cpu_throttle_low_percent == 91
    assert args.ram_throttle_high_percent == 97
    assert args.ram_throttle_low_percent == 92


def test_select_videos_filters_docx_scan_by_youtube_id() -> None:
    first = make_video("aaaaaaaaaaa", speaker="First")
    second = make_video("bbbbbbbbbbb", speaker="Second")

    selected = select_videos([first, second], only_video_ids=["https://www.youtube.com/watch?v=bbbbbbbbbbb"])

    assert selected == [second]


def test_select_videos_filters_case_and_whitespace_normalized_speaker_groups() -> None:
    first = make_video("aaaaaaaaaaa", speaker="Speaker A")
    second = make_video("bbbbbbbbbbb", speaker="Speaker B")

    selected = select_videos([first, second], selected_speakers=["  speaker   a "])

    assert selected == [first]


def test_choose_random_video_is_seedable_for_reproducible_validation() -> None:
    videos = [make_video("aaaaaaaaaaa"), make_video("bbbbbbbbbbb"), make_video("ccccccccccc")]

    first_pick = choose_random_video(videos, seed="validation-seed")
    second_pick = choose_random_video(videos, seed="validation-seed")

    assert len(first_pick) == 1
    assert first_pick == second_pick


def test_normalise_video_id_accepts_docx_ids_and_urls() -> None:
    assert normalise_video_id("docx:aaaaaaaaaaa:0:1") == "aaaaaaaaaaa"
    assert normalise_video_id("https://www.youtube.com/watch?v=bbbbbbbbbbb") == "bbbbbbbbbbb"
def test_summary_options_are_json_serializable() -> None:
    args = parse_args(["--source", "videos", "--output-root", "out"])

    payload = summary_options_from_args(args)

    json.dumps(payload)
    assert payload["source"] == "videos"
    assert payload["output_root"] == "out"


def test_result_line_does_not_claim_output_when_no_clean_segments() -> None:
    line = format_result_line(
        VideoRunResult(
            status="no_clean_segments",
            input_video=Path("input.mp4"),
            output_dir=Path("out"),
            output_video=Path("out/stitched_imotions.mp4"),
            message="No overlapping face and voice segments met the minimum duration.",
        )
    )

    assert line == "Clean speaker beta skipped: No overlapping face and voice segments met the minimum duration."


def test_result_line_reports_cached_outputs() -> None:
    line = format_result_line(
        VideoRunResult(
            status="cached",
            input_video=Path("input.mp4"),
            output_dir=Path("out"),
            output_video=Path("out/stitched_imotions.mp4"),
            message="Reused cached output.",
        )
    )

    assert line == "Clean speaker beta cached: out\\stitched_imotions.mp4"


def test_result_line_reports_needs_review() -> None:
    line = format_result_line(
        VideoRunResult(
            status="needs_review",
            input_video=Path("input.mp4"),
            output_dir=Path("out"),
            output_video=Path("out/stitched_imotions.mp4"),
            message="Final validation found suspect frames.",
        )
    )

    assert line == "Clean speaker beta needs review: Final validation found suspect frames."

def test_result_line_reports_cached_needs_review() -> None:
    line = format_result_line(
        VideoRunResult(
            status="cached_needs_review",
            input_video=Path("input.mp4"),
            output_dir=Path("out"),
            output_video=Path("out/stitched_imotions.mp4"),
            message="Final validation found suspect frames.",
        )
    )

    assert line == "Clean speaker beta cached needs review: Final validation found suspect frames."

def test_result_line_reports_cached_skips() -> None:
    line = format_result_line(
        VideoRunResult(
            status="cached_no_clean_segments",
            input_video=Path("input.mp4"),
            output_dir=Path("out"),
            output_video=Path("out/stitched_imotions.mp4"),
            message="No overlapping face and voice segments met the minimum duration.",
        )
    )

    assert line == "Clean speaker beta cached skip: No overlapping face and voice segments met the minimum duration."


def test_cache_root_is_stable_across_timestamped_runs() -> None:
    assert cache_root_from_output_root(Path("out")) == Path("out") / "_clean_speaker_beta_cache"






def test_youtube_format_fallback_selectors_try_progressive_and_lower_quality() -> None:
    selectors = youtube_format_fallback_selectors(720)

    assert selectors[0] == youtube_format_selector(720)
    assert "best[height<=720][ext=mp4]" in selectors[1]
    assert youtube_format_selector(480) in selectors
    assert youtube_format_selector(0) == selectors[-1]


def test_download_youtube_video_retries_fallback_after_format_failure(tmp_path: Path, monkeypatch) -> None:
    video = make_video("abcdefghijk")
    calls: list[list[str]] = []

    def fake_run(command: list[str], check: bool, timeout: float | None = None, **_kwargs: object) -> object:
        calls.append(command)
        if len(calls) == 1:
            partial = tmp_path / "abcdefghijk_h720.f140.m4a"
            partial.write_bytes(b"partial")
            raise subprocess.CalledProcessError(1, command)
        output_index = command.index("-o") + 1
        Path(command[output_index]).write_bytes(b"downloaded")
        return object()

    monkeypatch.setattr("procurement.procurement_beta.cli.subprocess.run", fake_run)

    output = download_youtube_video(video, tmp_path, max_height=720)

    assert output == tmp_path / "abcdefghijk_h720.mp4"
    assert output.read_bytes() == b"downloaded"
    assert len(calls) == 2
    assert not (tmp_path / "abcdefghijk_h720.f140.m4a").exists()
    assert calls[0][calls[0].index("-f") + 1] == youtube_format_selector(720)
    assert calls[1][calls[1].index("-f") + 1] == youtube_format_fallback_selectors(720)[1]


def test_download_youtube_video_strips_credentials_from_media_child(tmp_path: Path, monkeypatch) -> None:
    video = make_video("abcdefghijk")
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> object:
        captured.update(kwargs)
        Path(command[command.index("-o") + 1]).write_bytes(b"downloaded")
        return object()

    secret_names = ("YOUTUBE_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN")
    for name in secret_names:
        monkeypatch.setenv(name, f"secret-{name}")
    monkeypatch.setattr("procurement.procurement_beta.cli.subprocess.run", fake_run)

    download_youtube_video(video, tmp_path, max_height=720)

    environment = captured.get("env")
    assert isinstance(environment, dict)
    assert all(name not in environment for name in secret_names)


def test_isolated_model_child_retains_hugging_face_token_but_not_youtube_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 1234
        stdout: list[str] = []

        @staticmethod
        def wait() -> int:
            return 0

    def fake_popen(*_args: object, **kwargs: object) -> FakeProcess:
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setenv("HF_TOKEN", "model-secret")
    monkeypatch.setenv("YOUTUBE_API_KEY", "youtube-secret")
    monkeypatch.setattr("procurement.procurement_beta.cli.subprocess.Popen", fake_popen)
    args = parse_args(["--source", "videos", "--output-root", "out"])

    assert run_child_process(["python", "model_worker.py"], args=args) == 0
    environment = captured.get("env")
    assert isinstance(environment, dict)
    assert environment.get("HF_TOKEN") == "model-secret"
    assert "YOUTUBE_API_KEY" not in environment

def test_youtube_format_selector_caps_default_download_height() -> None:
    selector = youtube_format_selector(720)

    assert "height<=720" in selector
    assert "bestvideo" in selector


def test_youtube_format_selector_allows_uncapped_best_quality() -> None:
    selector = youtube_format_selector(0)

    assert "height<=" not in selector
    assert selector.startswith("bestvideo")
def test_direct_youtube_url_source_builds_single_video_item() -> None:
    source, videos = videos_from_source_input("https://www.youtube.com/watch?v=mZBHkYWKE5M", enrich_youtube=False)

    assert source == "https://www.youtube.com/watch?v=mZBHkYWKE5M"
    assert len(videos) == 1
    assert videos[0].source_kind == "youtube"
    assert videos[0].youtube_url == "https://www.youtube.com/watch?v=mZBHkYWKE5M"
    assert videos[0].video_id == "mZBHkYWKE5M"
    assert videos[0].title == "Title unavailable [mZBHkYWKE5M]"


def test_local_video_file_source_builds_single_work_item(tmp_path: Path) -> None:
    video_path = tmp_path / "Speaker C" / "speech.mp4"
    video_path.parent.mkdir()
    video_path.write_bytes(b"not a real mp4")

    source, videos = videos_from_source_input(video_path, enrich_youtube=False)
    item = prepare_work_item(videos[0], tmp_path / "downloads")

    assert source == str(video_path.resolve())
    assert len(videos) == 1
    assert videos[0].source_kind == "file"
    assert item.source_path == video_path.resolve()
    assert item.speaker == "Speaker C"


def test_isolated_control_json_rejects_oversized_bytes(tmp_path: Path) -> None:
    path = tmp_path / "video_0001_result.json"
    path.write_text(json.dumps({"padding": "x" * (1024 * 1024)}), encoding="utf-8")

    with pytest.raises(ValueError, match="clean speaker control JSON exceeds 1048576 bytes"):
        read_json(path)


def test_isolated_control_json_rejects_excessive_semantic_items(tmp_path: Path) -> None:
    path = tmp_path / "video_0001.json"
    path.write_text(json.dumps({"items": [None] * 50_001}), encoding="utf-8")

    with pytest.raises(ValueError, match="more than 50000 items"):
        read_json(path)

def test_download_youtube_video_reuses_cached_file(tmp_path: Path, monkeypatch) -> None:
    video = make_video("aaaaaaaaaaa")
    cached = tmp_path / "aaaaaaaaaaa_h720.mp4"
    cached.write_bytes(b"cached video")
    calls: list[object] = []

    monkeypatch.setattr("procurement.procurement_beta.cli.subprocess.run", lambda *args, **kwargs: calls.append(args))

    result = download_youtube_video(video, tmp_path)

    assert result == cached
    assert calls == []
