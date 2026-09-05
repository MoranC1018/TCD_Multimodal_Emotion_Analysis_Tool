from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from procurement.external_tools import (
    credential_free_media_environment,
    resolve_media_binary,
)
from processing.face_analysis import media
from processing.face_analysis.media import VideoMetadata, probe_video
from processing.face_analysis.outputs import build_output_tables, expected_sampled_frames
from processing.face_analysis.tests.helpers import complete_detection_row


@pytest.fixture(scope="module")
def media_tools() -> tuple[Path, Path]:
    try:
        return resolve_media_binary("ffmpeg"), resolve_media_binary("ffprobe")
    except FileNotFoundError as exc:
        pytest.skip(f"Real video timing integration requires FFmpeg and FFprobe: {exc}")


def make_video(path: Path, ffmpeg: Path, *, audio_seconds: int) -> None:
    codecs = (
        ["-c:v", "ffv1", "-c:a", "pcm_s16le"]
        if path.suffix == ".mkv"
        else ["-c:v", "mpeg4", "-bf", "0", "-c:a", "aac"]
    )
    subprocess.run(
        [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:r=25:d=2",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-map", "0:v:0", "-map", "1:a:0", "-t", str(audio_seconds),
            *codecs, str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        env=credential_free_media_environment(),
    )


@pytest.mark.parametrize(
    ("suffix", "audio_seconds"), [(".mp4", 2), (".mp4", 4), (".mkv", 2), (".mkv", 4)]
)
def test_real_video_duration_and_coverage_ignore_longer_audio(
    tmp_path: Path, monkeypatch, media_tools, suffix: str, audio_seconds: int
) -> None:
    ffmpeg, ffprobe = media_tools
    video = tmp_path / f"video_2s_audio_{audio_seconds}s{suffix}"
    make_video(video, ffmpeg, audio_seconds=audio_seconds)
    original_run = subprocess.run
    probe_commands = []

    def recording_run(command, **kwargs):
        probe_commands.append(command)
        return original_run(command, **kwargs)

    monkeypatch.setattr(media.subprocess, "run", recording_run)
    metadata = probe_video(video, ffprobe=ffprobe)
    detections = pd.DataFrame(
        [complete_detection_row(frame=frame) for frame in [0, 5, 10, 15, 20, 25, 30, 35, 40, 45]]
    )
    _, core, quality = build_output_tables(
        detections, metadata, sample_fps=5, media_id="synthetic"
    )

    assert metadata.duration_seconds == pytest.approx(2.0)
    assert metadata.frame_count == 50
    assert metadata.fps == 25.0
    assert core.frame_index.tolist() == [0, 5, 10, 15, 20, 25, 30, 35, 40, 45]
    assert core.timestamp_seconds.tolist() == pytest.approx([0, .2, .4, .6, .8, 1, 1.2, 1.4, 1.6, 1.8])
    assert quality["sampled_frames"] == 10
    assert quality["frames_without_face"] == 0
    assert quality["face_coverage"] == 1.0
    # Every probe reads the header and scans timing, even with complete metadata.
    assert len(probe_commands) == 2
    assert "-show_frames" in probe_commands[1]


def test_real_video_preserves_missing_face_rows_and_rejects_frames_after_video(
    tmp_path: Path, media_tools
) -> None:
    ffmpeg, ffprobe = media_tools
    video = tmp_path / "video_2s_audio_4s.mkv"
    make_video(video, ffmpeg, audio_seconds=4)
    metadata = probe_video(video, ffprobe=ffprobe)
    detections = pd.DataFrame(
        [complete_detection_row(frame=frame) for frame in [0, 5, 10, 15, 25, 30, 35, 40, 45]]
    )

    _, core, quality = build_output_tables(
        detections, metadata, sample_fps=5, media_id="synthetic"
    )

    assert core.loc[~core.face_detected, "frame_index"].tolist() == [20]
    assert quality["frames_without_face"] == 1
    assert quality["face_coverage"] == 0.9
    with pytest.raises(RuntimeError, match="sampling grid"):
        build_output_tables(
            pd.DataFrame([complete_detection_row(frame=50)]),
            metadata,
            sample_fps=5,
            media_id="synthetic",
        )


def test_complete_metadata_vfr_is_rejected_before_face_analysis(tmp_path: Path, media_tools) -> None:
    from processing.face_analysis.pipeline import process_face_input

    ffmpeg, ffprobe = media_tools
    video = tmp_path / "variable_density.mp4"
    subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=s=64x64:r=25:d=4",
         "-vf", r"select=lt(n\,50)+gte(n\,50)*not(mod(n\,2))", "-fps_mode", "vfr",
         "-an", "-c:v", "libx264", "-bf", "0", str(video)],
        check=True, capture_output=True, text=True, timeout=30,
        env=credential_free_media_environment(),
    )
    header = json.loads(subprocess.run(
        [str(ffprobe), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=duration,nb_frames,avg_frame_rate", "-of", "json", str(video)],
        check=True, capture_output=True, text=True, timeout=30,
        env=credential_free_media_environment(),
    ).stdout)["streams"][0]
    assert int(header["nb_frames"]) == 75
    assert float(header["duration"]) > 0

    with pytest.raises(RuntimeError, match="nonuniform.*timestamps"):
        probe_video(video, ffprobe=ffprobe)

    class UnusedBackend:
        def analyse(self, *_args):
            pytest.fail("A rejected VFR video must not reach model inference")

    output = tmp_path / "output"
    result = process_face_input(video, output, backend=UnusedBackend())
    assert result.failed == 1
    failure = json.loads(result.run_manifest.read_text())["videos"][0]
    assert failure["error_stage"] == "probe"
    assert "nonuniform" in failure["error_message"]
    assert not list(output.rglob("face_core.csv"))
    assert not list(output.rglob("face_features.parquet"))


@pytest.mark.parametrize("suffix", [".mp4", ".mkv"])
@pytest.mark.parametrize("rate", ["25", "30000/1001"])
def test_real_cfr_timing_keeps_fractional_rates(tmp_path: Path, media_tools, suffix: str, rate: str) -> None:
    ffmpeg, ffprobe = media_tools
    video = tmp_path / f"constant_rate{suffix}"
    subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=s=64x64:r={rate}:d=2", "-an", "-c:v", "libx264",
         "-bf", "0", str(video)],
        check=True, capture_output=True, text=True, timeout=30,
        env=credential_free_media_environment(),
    )

    metadata = probe_video(video, ffprobe=ffprobe)

    assert metadata.fps == pytest.approx(25 if rate == "25" else 30000 / 1001)
    assert metadata.frame_count == (50 if rate == "25" else 60)
    assert metadata.duration_seconds == pytest.approx(2 if rate == "25" else 2.002, abs=.001)


@pytest.mark.parametrize("frame_count", [None, 0, -1])
def test_output_sampling_requires_an_evidenced_positive_frame_count(frame_count) -> None:
    metadata = VideoMetadata("video.mkv", "abc", 1, 4.0, 25.0, frame_count, 64, 64)
    with pytest.raises(RuntimeError, match="frame count"):
        expected_sampled_frames(metadata, sample_fps=5)


def install_probe_response(monkeypatch, tmp_path: Path, stream, *, frames=None):
    video = tmp_path / "video.mkv"
    video.write_bytes(b"controlled video metadata")
    monkeypatch.setattr(media, "resolve_media_binary", lambda *_args, **_kwargs: Path("ffprobe"))

    def fake_run(command, **kwargs):
        if "compact" in command[command.index("-of") + 1]:
            assert frames is not None, "Unexpected frame timing scan"
            kwargs["stdout"].write(frames)
            kwargs["stdout"].flush()
            return subprocess.CompletedProcess(command, 0, None, "")
        return subprocess.CompletedProcess(
            command, 0,
            json.dumps({"streams": [stream], "format": {"duration": "4.0"}}), ""
        )

    monkeypatch.setattr(media.subprocess, "run", fake_run)
    return video


def test_known_video_duration_counts_frames_without_estimating_from_rate(
    monkeypatch, tmp_path: Path
) -> None:
    video = install_probe_response(
        monkeypatch, tmp_path,
        {"duration": "2.0", "avg_frame_rate": "25/1", "width": 64, "height": 64},
        frames="".join(
            f"frame|best_effort_timestamp_time={frame / 25:.6f}|duration_time=0.040000\n"
            for frame in range(49)
        ),
    )
    metadata = probe_video(video)
    assert metadata.duration_seconds == 2.0
    assert metadata.frame_count == 49


@pytest.mark.parametrize("duration_field", ["duration_time", "pkt_duration_time"])
def test_frame_timestamp_fallback_uses_video_span_relative_to_first_frame(
    monkeypatch, tmp_path: Path, duration_field: str
) -> None:
    video = install_probe_response(
        monkeypatch, tmp_path,
        {"avg_frame_rate": "25/1", "time_base": "1/1000", "width": 64, "height": 64},
        frames=(
            f"frame|best_effort_timestamp_time=7.000000|{duration_field}=0.040000\n"
            f"frame|best_effort_timestamp_time=7.040000|{duration_field}=0.040000\n"
            f"frame|best_effort_timestamp_time=7.080000|{duration_field}=0.040000\n"
        ),
    )
    metadata = probe_video(video)
    assert metadata.duration_seconds == pytest.approx(.12)
    assert metadata.frame_count == 3


def test_frame_timestamp_fallback_allows_container_time_base_rounding(
    monkeypatch, tmp_path: Path
) -> None:
    video = install_probe_response(
        monkeypatch, tmp_path,
        {"avg_frame_rate": "30000/1001", "time_base": "1/1000", "width": 64, "height": 64},
        frames=(
            "frame|best_effort_timestamp_time=0.000000|duration_time=0.033000\n"
            "frame|best_effort_timestamp_time=0.033000|duration_time=0.033000\n"
            "frame|best_effort_timestamp_time=0.067000|duration_time=0.033000\n"
            "frame|best_effort_timestamp_time=0.100000|duration_time=0.033000\n"
        ),
    )
    metadata = probe_video(video)
    assert metadata.duration_seconds == pytest.approx(.133)
    assert metadata.frame_count == 4


@pytest.mark.parametrize(
    ("frames", "message"),
    [
        ("", "frame count"),
        ("frame|best_effort_timestamp_time=N/A|duration_time=0.040000\n", "timestamp"),
        ("frame|best_effort_timestamp_time=0.000000\n", "duration"),
        (
            "frame|best_effort_timestamp_time=0.000000|duration_time=0.040000\n"
            "frame|best_effort_timestamp_time=0.200000|duration_time=0.040000\n",
            "nonuniform|irregular",
        ),
    ],
)
def test_frame_timestamp_fallback_fails_closed_for_uncertain_timing(
    monkeypatch, tmp_path: Path, frames: str, message: str
) -> None:
    video = install_probe_response(
        monkeypatch, tmp_path,
        {"avg_frame_rate": "25/1", "width": 64, "height": 64},
        frames=frames,
    )
    with pytest.raises(RuntimeError, match=message):
        probe_video(video)


@pytest.mark.parametrize("duration", [None, "0.08"])
def test_timing_scan_rejects_short_decode_when_header_count_is_known(
    monkeypatch, tmp_path: Path, duration
) -> None:
    video = install_probe_response(
        monkeypatch, tmp_path,
        {"duration": duration, "avg_frame_rate": "25/1", "nb_frames": "2", "width": 64, "height": 64},
        frames="frame|best_effort_timestamp_time=0.000000|duration_time=0.040000\n",
    )
    with pytest.raises(RuntimeError, match="frame count"):
        probe_video(video)


def test_timing_scan_rejects_empty_decode_with_known_duration(monkeypatch, tmp_path: Path) -> None:
    video = install_probe_response(
        monkeypatch, tmp_path,
        {"duration": "2.0", "avg_frame_rate": "25/1", "width": 64, "height": 64},
        frames="",
    )
    with pytest.raises(RuntimeError, match="frame count"):
        probe_video(video)


@pytest.mark.parametrize("failure", ["decode_error", "timeout"])
def test_probe_does_not_publish_metadata_after_media_tool_errors(
    monkeypatch, tmp_path: Path, failure: str
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"invalid video")
    monkeypatch.setattr(media, "resolve_media_binary", lambda *_args, **_kwargs: Path("ffprobe"))

    def failed_run(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 300)
        return subprocess.CompletedProcess(
            command, 0,
            json.dumps({
                "streams": [{"duration": "2.0", "avg_frame_rate": "25/1", "nb_frames": "50"}],
                "format": {"duration": "4.0"},
            }),
            "Invalid data found when processing input",
        )

    monkeypatch.setattr(media.subprocess, "run", failed_run)
    with pytest.raises(RuntimeError, match="inspect video|timed out"):
        probe_video(video)
