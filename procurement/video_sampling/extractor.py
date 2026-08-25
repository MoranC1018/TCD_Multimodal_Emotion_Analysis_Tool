#!/usr/bin/env python3
"""
extractor.py

Given a YouTube link, this script:

1. Reads the video title and length using yt-dlp.
2. Calculates a maximum sample size, defaulting to 10% of the full video length.
3. Randomly selects mostly 30-second segments until that limit is reached.
4. Avoids any old / no-go ranges passed in with --exclude-segment.
5. Downloads those segments into a folder named:

       Video_Title_[youtubeVideoID]

6. Stitches the raw downloaded clips together into one temporary video.

7. Converts that one stitched video into a single iMotions-friendly MP4:

       stitched_imotions.mp4

   The iMotions-friendly output uses:

       H.264 / AVC video
       yuv420p pixel format
       constant frame rate, default 30 fps
       AAC stereo audio at 48 kHz
       MP4 fast-start metadata

8. Writes a clean timecode log into:

       video_timecodes/

9. Writes a full console log into:

       logs/latest.log

   At the end of a successful or failed run, latest.log is renamed to a dated
   permanent log file.

Requirements:
- yt-dlp
- ffmpeg
- ffprobe, normally installed with ffmpeg

Normal use:
    python procurement/video_sampling/extractor.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

With old no-go ranges:
    python procurement/video_sampling/extractor.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --exclude-segment 00:01:21-00:01:51
"""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import random
import re
import shlex
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__ in {None, ""}:  # pragma: no cover - supports direct script execution.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from procurement.console import configure_utf8_stdio
from procurement.external_tools import build_yt_dlp_command, credential_free_media_environment, resolve_media_binary
from procurement.video_sampling.run_docx_extractions import normalise_youtube_url

try:
    from procurement.video_sampling.naming import make_video_output_folder_name
except ModuleNotFoundError:  # pragma: no cover - supports direct script execution from this folder.
    from naming import make_video_output_folder_name


# -----------------------------
# Default settings
# -----------------------------

DEFAULT_SEGMENT_LENGTH_SECONDS = 30
DEFAULT_DOWNLOAD_PERCENTAGE = 0.10
DEFAULT_MAX_HEIGHT = 720
DEFAULT_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_IMOTIONS_FPS = 30
DEFAULT_IMOTIONS_CRF = 18
DEFAULT_IMOTIONS_AUDIO_BITRATE = "192k"
DEFAULT_IMOTIONS_AUDIO_RATE = 48000

TIMECODE_LOG_FOLDER_NAME = "video_timecodes"
FULL_LOG_FOLDER_NAME = "logs"
LATEST_LOG_NAME = "latest.log"

RAW_CLIP_FOLDER_NAME = "raw_clips"
STITCHED_VIDEO_NAME = "stitched_imotions.mp4"
RAW_STITCHED_VIDEO_NAME = "_stitched_raw_for_conversion.mp4"
CONCAT_RAW_LIST_NAME = "_concat_raw_clips.txt"
METADATA_FILE_NAME = "extraction_metadata.json"
COMPLETION_FILE_NAME = "_extraction_complete.json"

# Use ordinary MP4-friendly formats first. This is deliberately conservative.
# The old selector, bv*+ba/b, can choose huge 4K AV1 video plus Opus audio,
# which is slower and more fragile for iMotions-style batch work.
DEFAULT_FORMAT_SELECTOR_TEMPLATE = (
    "b[height<={max_height}][ext=mp4]/"
    "bv*[height<={max_height}][ext=mp4][vcodec^=avc1]+ba[ext=m4a]/"
    "bv*[height<={max_height}][vcodec^=avc1]+ba[acodec^=mp4a]/"
    "best[height<={max_height}]/best"
)

# Some YouTube progressive MP4 section URLs return 403 when ffmpeg opens the
# signed media URL. HLS sections are slower to initialise, but they are a useful
# recovery path because yt-dlp can keep the segment download small.
HLS_FALLBACK_FORMAT_SELECTOR_TEMPLATE = (
    "bv*[height<={max_height}][protocol^=m3u8]+ba[protocol^=m3u8]/"
    "b[height<={max_height}][protocol^=m3u8]/"
    "best[height<={max_height}][protocol^=m3u8]/"
    "best[height<={max_height}]/best"
)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov"}
VIDEO_INFO_RETRY_COUNT = 3
VIDEO_INFO_RETRY_DELAY_SECONDS = 5
DEFAULT_MAX_SEGMENT_REPLACEMENTS = 25
YT_DLP_COOKIES_BROWSER_ENV = "YT_DLP_COOKIES_FROM_BROWSER"
YT_DLP_COOKIES_FILE_ENV = "YT_DLP_COOKIES_FILE"


# -----------------------------
# Small data objects
# -----------------------------

@dataclass(frozen=True)
class TimeSegment:
    """A half-open time range: start <= t < end."""

    start: int
    end: int

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)


# -----------------------------
# General helpers
# -----------------------------

def make_filename_safe(text: str, max_length: int = 120) -> str:
    """
    Converts text into something safe to use as a file or folder name.

    Example:
        "My Cool Video: Part 1!" -> "My_Cool_Video_Part_1"
    """
    text = str(text).strip()
    text = text.replace(" ", "_")
    text = re.sub(r'[<>:"/\\|?*]', "", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip("._ ")

    if not text:
        text = "youtube_video"

    return text[:max_length]


def get_youtube_video_id(url: str) -> str:
    """Extracts the YouTube video ID from common YouTube URL formats."""
    parsed_url = urlparse(url)
    host = parsed_url.netloc.lower()
    host = host.removeprefix("www.").removeprefix("m.").removeprefix("music.")

    if host == "youtu.be":
        return parsed_url.path.strip("/").split("/")[0] or "unknown_id"

    if host in {"youtube.com", "youtube-nocookie.com"}:
        query_values = parse_qs(parsed_url.query)

        if "v" in query_values and query_values["v"]:
            return query_values["v"][0]

        path_parts = [part for part in parsed_url.path.split("/") if part]

        for marker in ("shorts", "embed", "live", "v"):
            if marker in path_parts:
                marker_index = path_parts.index(marker)
                if marker_index + 1 < len(path_parts):
                    return path_parts[marker_index + 1]

    return "unknown_id"


def timestamp_to_seconds(timestamp: str) -> int:
    """
    Converts a timestamp to seconds.

    Accepted examples:
        01:21       -> 81
        00:01:21    -> 81
        1:02:03     -> 3723
        81          -> 81
    """
    cleaned = timestamp.strip().replace("：", ":")

    if not cleaned:
        raise ValueError("Empty timestamp")

    if ":" not in cleaned:
        return int(round(float(cleaned)))

    parts = cleaned.split(":")

    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + int(round(float(seconds)))

    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + int(round(float(seconds)))

    raise ValueError(f"Unsupported timestamp format: {timestamp}")


def seconds_to_ytdlp_timestamp(seconds: int | float) -> str:
    """
    Converts seconds into HH:MM:SS format for yt-dlp and ffmpeg.

    Example:
        81 -> 00:01:21
    """
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def seconds_to_filename_time(seconds: int | float) -> str:
    """
    Converts seconds into MM_SS format for filenames.

    Example:
        81 -> 01_21

    If a video is over an hour long, the minutes simply keep increasing.
    Example:
        3665 -> 61_05
    """
    seconds = int(seconds)
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes:02d}_{secs:02d}"


def command_to_readable_text(command: list[str]) -> str:
    """Converts a command list into readable command-line text for logging."""
    return " ".join(shlex.quote(str(part)) for part in command)


def unique_path(path: Path) -> Path:
    """If a file already exists, adds _002, _003, etc."""
    path = Path(path)

    if not path.exists():
        return path

    counter = 2

    while True:
        candidate = path.with_name(f"{path.stem}_{counter:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def parse_ffmpeg_time_seconds(line: str) -> float | None:
    """
    Pulls ffmpeg progress time out of a line such as:

        frame= 126 ... time=00:00:04.04 ...

    Returns seconds, or None if the line does not contain a time field.
    """
    match = re.search(r"time=(-?\d+):(\d+):(\d+(?:\.\d+)?)", line)

    if not match:
        return None

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))

    sign = -1 if hours < 0 else 1
    return sign * (abs(hours) * 3600 + minutes * 60 + seconds)


def remove_partial_files(folder: Path) -> None:
    """Cleans up unfinished .part files after a failed or timed-out command."""
    if not folder.exists():
        return

    for partial_file in folder.rglob("*.part"):
        try:
            partial_file.unlink()
        except OSError:
            pass


def parse_exclude_segment(value: str) -> TimeSegment:
    """
    Parses --exclude-segment values.

    Accepted examples:
        00:01:21-00:01:51
        01:21-01:51
        81-111
    """
    cleaned = value.strip()

    if "-" not in cleaned:
        raise ValueError(f"Expected START-END format, got: {value}")

    start_text, end_text = cleaned.split("-", 1)
    start = timestamp_to_seconds(start_text)
    end = timestamp_to_seconds(end_text)

    if end <= start:
        raise ValueError(f"Exclude segment end must be after start: {value}")

    return TimeSegment(start=start, end=end)


def clamp_and_merge_segments(segments: list[TimeSegment], video_duration: int) -> list[TimeSegment]:
    """Clamps ranges to the video and merges overlaps/touching ranges."""
    cleaned: list[TimeSegment] = []

    for segment in segments:
        start = max(0, min(video_duration, int(segment.start)))
        end = max(0, min(video_duration, int(segment.end)))

        if end > start:
            cleaned.append(TimeSegment(start, end))

    if not cleaned:
        return []

    cleaned.sort(key=lambda segment: (segment.start, segment.end))
    merged: list[TimeSegment] = []

    current_start = cleaned[0].start
    current_end = cleaned[0].end

    for segment in cleaned[1:]:
        if segment.start <= current_end:
            current_end = max(current_end, segment.end)
        else:
            merged.append(TimeSegment(current_start, current_end))
            current_start = segment.start
            current_end = segment.end

    merged.append(TimeSegment(current_start, current_end))
    return merged


def invert_blocked_segments(blocked: list[TimeSegment], video_duration: int) -> list[TimeSegment]:
    """Returns the allowed video intervals left after blocking ranges."""
    blocked = clamp_and_merge_segments(blocked, video_duration)
    allowed: list[TimeSegment] = []
    cursor = 0

    for segment in blocked:
        if segment.start > cursor:
            allowed.append(TimeSegment(cursor, segment.start))
        cursor = max(cursor, segment.end)

    if cursor < video_duration:
        allowed.append(TimeSegment(cursor, video_duration))

    return allowed


def choose_start_from_allowed_intervals(allowed: list[TimeSegment], clip_length: int) -> int:
    """
    Randomly chooses a start time from intervals that can fit clip_length.

    Longer valid regions are weighted more heavily, because they contain more
    possible start times.
    """
    possible: list[tuple[int, int, int]] = []
    total_weight = 0

    for interval in allowed:
        latest_start = interval.end - clip_length
        if latest_start < interval.start:
            continue

        # +1 because randint endpoints are inclusive.
        weight = latest_start - interval.start + 1
        possible.append((interval.start, latest_start, weight))
        total_weight += weight

    if not possible:
        raise ValueError("No allowed interval is long enough for the next clip.")

    pick = random.randint(1, total_weight)
    running = 0

    for start_min, start_max, weight in possible:
        running += weight
        if pick <= running:
            return random.randint(start_min, start_max)

    # Should never happen, but keeps type-checkers happy.
    return random.randint(possible[-1][0], possible[-1][1])


def longest_allowed_interval_length(allowed: list[TimeSegment]) -> int:
    """Return the length of the largest currently available interval."""

    return max((interval.length for interval in allowed), default=0)


def resolve_seed(seed_argument: int | None) -> tuple[int, str]:
    """Return the active random seed and record where it came from."""

    if seed_argument is None:
        seed = random.randint(0, 2_147_483_647)
        seed_source = "generated"
    else:
        seed = int(seed_argument)
        seed_source = "cli"

    random.seed(seed)
    return seed, seed_source


# -----------------------------
# Full console logger
# -----------------------------

class RunLogger:
    """
    Writes messages to both:
    - the terminal
    - logs/latest.log

    At the end, logs/latest.log is renamed to a dated permanent log file.
    """

    def __init__(self) -> None:
        self.log_folder = Path(FULL_LOG_FOLDER_NAME)
        self.log_folder.mkdir(exist_ok=True)

        self.latest_log_path = self.log_folder / LATEST_LOG_NAME
        self.finished_log_path: Path | None = None

        self.log_file = open(self.latest_log_path, "w", encoding="utf-8")

        self.log("=" * 70)
        self.log(f"Run started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log("=" * 70)
        self.log("")

    def log(self, message: object = "") -> None:
        """Write a message to the run log and mirror it to the terminal.

        Terminal writes are intentionally best-effort. On Windows, long-running
        ffmpeg streams can occasionally lose or reject the console handle and
        raise ``OSError: [Errno 22] Invalid argument``. The log file is the
        durable audit trail, so a terminal display failure must not abort the
        video extraction.
        """
        message_text = str(message)
        self.log_file.write(message_text + "\n")
        self.log_file.flush()
        try:
            print(message_text, flush=True)
        except (OSError, UnicodeError):
            pass

    def run_command_capture(self, command: list[str], timeout_seconds: int | None = None) -> subprocess.CompletedProcess:
        """Runs a command where stdout needs to be captured."""
        self.log(f"$ {command_to_readable_text(command)}")

        return subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=credential_free_media_environment(),
        )

    def run_command_live(
        self,
        command: list[str],
        overall_timeout_seconds: int,
        stall_timeout_seconds: int,
    ) -> None:
        """
        Runs a command while streaming output to the terminal and log file.

        It watches ffmpeg-style media timestamps. If the media timestamp does
        not move for stall_timeout_seconds, the command is killed and treated
        as failed. This is designed to catch the repeated "frame=126" style
        stall you saw.
        """
        self.log(f"$ {command_to_readable_text(command)}")

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=credential_free_media_environment(),
        )

        start_clock = time.monotonic()
        last_media_progress_clock = time.monotonic()
        last_seen_media_time: float | None = None
        output_lines: list[str] = []

        assert process.stdout is not None
        output_queue: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            try:
                for raw_line in process.stdout:
                    output_queue.put(raw_line)
            finally:
                output_queue.put(None)

        reader = threading.Thread(
            target=read_output,
            daemon=True,
            name=f"extractor-output-{process.pid}",
        )
        reader.start()

        try:
            while True:
                now = time.monotonic()
                if now - start_clock > overall_timeout_seconds:
                    raise TimeoutError(
                        f"Command exceeded overall timeout of {overall_timeout_seconds} seconds."
                    )
                if (
                    last_seen_media_time is not None
                    and now - last_media_progress_clock > stall_timeout_seconds
                ):
                    raise TimeoutError(
                        "ffmpeg appears stalled: media timestamp has not advanced for "
                        f"{stall_timeout_seconds} seconds. Last media time was "
                        f"{last_seen_media_time:.2f}s."
                    )

                try:
                    raw_line = output_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if raw_line is None:
                    break
                line = raw_line.rstrip("\r\n")
                output_lines.append(line)
                self.log(line)

                now = time.monotonic()

                media_time = parse_ffmpeg_time_seconds(line)

                if media_time is not None and media_time >= 0:
                    if last_seen_media_time is None or media_time > last_seen_media_time + 0.25:
                        last_seen_media_time = media_time
                        last_media_progress_clock = now

            return_code = process.wait()

            if return_code != 0:
                raise subprocess.CalledProcessError(
                    return_code,
                    command,
                    output="\n".join(output_lines[-200:]),
                )

        except Exception:
            if process.poll() is None:
                self.log("Stopping stalled command...")
                process.terminate()

                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.log("Command did not terminate cleanly; killing it.")
                    process.kill()
                    process.wait(timeout=10)

            raise
        finally:
            reader.join(timeout=1)

    def finish(self, suffix: str | None = None) -> Path:
        """Closes logs/latest.log and renames it to a dated log file."""
        self.log("")
        self.log("=" * 70)
        self.log(f"Run finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log("=" * 70)

        self.log_file.close()

        finished_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        if suffix:
            finished_log_name = f"{finished_time}_{make_filename_safe(suffix)}.log"
        else:
            finished_log_name = f"{finished_time}.log"

        finished_log_path = unique_path(self.log_folder / finished_log_name)
        self.latest_log_path.rename(finished_log_path)
        self.finished_log_path = finished_log_path
        return finished_log_path


# -----------------------------
# YouTube information
# -----------------------------

def get_video_info(url: str, logger: RunLogger, info_timeout_seconds: int) -> dict[str, int | str]:
    """Uses yt-dlp to read title and duration without downloading the video."""
    canonical_url = normalise_youtube_url(url)
    if canonical_url is None:
        raise ValueError("A valid YouTube URL with an exact 11-character video ID is required.")
    logger.log("Reading YouTube video information...")

    command = build_yt_dlp_command(
        [
        "--dump-json",
        "--no-playlist",
        "--socket-timeout",
        "30",
        ],
        ffmpeg_binary=resolve_media_binary("ffmpeg"),
    )
    command.extend(yt_dlp_auth_args())
    command.append(canonical_url)

    last_error: subprocess.CalledProcessError | subprocess.TimeoutExpired | None = None

    for attempt_number in range(1, VIDEO_INFO_RETRY_COUNT + 1):
        try:
            result = logger.run_command_capture(command, timeout_seconds=info_timeout_seconds)
            break
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            last_error = error
            logger.log(f"Video information attempt {attempt_number}/{VIDEO_INFO_RETRY_COUNT} failed.")
            log_subprocess_failure_summary(logger, error)

            if attempt_number < VIDEO_INFO_RETRY_COUNT:
                logger.log(
                    "Retrying video information lookup after "
                    f"{VIDEO_INFO_RETRY_DELAY_SECONDS} seconds..."
                )
                time.sleep(VIDEO_INFO_RETRY_DELAY_SECONDS)
    else:
        assert last_error is not None
        raise last_error

    video_data = json.loads(result.stdout)

    logger.log("Video information loaded successfully.")
    logger.log("")

    return {
        "title": video_data.get("title", "youtube_video"),
        "duration": int(video_data["duration"]),
    }


def log_subprocess_failure_summary(
    logger: RunLogger,
    error: subprocess.CalledProcessError | subprocess.TimeoutExpired,
) -> None:
    """Writes the useful captured part of a failed subprocess to the run log."""
    stdout_text = getattr(error, "stdout", None) or getattr(error, "output", None)
    stderr_text = getattr(error, "stderr", None)

    if stdout_text:
        logger.log("Captured stdout tail:")
        logger.log(tail_text(str(stdout_text), max_lines=20))

    if stderr_text:
        logger.log("Captured stderr tail:")
        logger.log(tail_text(str(stderr_text), max_lines=20))


def tail_text(text: str, max_lines: int) -> str:
    """Returns the last few non-empty lines from a large command output blob."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


# -----------------------------
# Segment selection
# -----------------------------

def make_random_segments(
    video_duration: int,
    total_seconds_to_download: int,
    segment_length_seconds: int,
    no_go_segments: list[TimeSegment],
) -> list[dict[str, int]]:
    """
    Randomly creates segments that add up to total_seconds_to_download.

    Old no-go ranges block where new clips can be selected, but do not reduce
    the total target. For example, if the video is 1000 seconds and the target
    is 10%, this still tries to take 100 new seconds even if old no-go ranges
    exist.
    """
    segments: list[dict[str, int]] = []
    blocked = clamp_and_merge_segments(no_go_segments, video_duration)
    remaining_seconds = total_seconds_to_download

    available_seconds = sum(interval.length for interval in invert_blocked_segments(blocked, video_duration))
    if available_seconds < total_seconds_to_download:
        raise ValueError(
            "Not enough unblocked footage remains to take the requested sample. "
            f"Need {total_seconds_to_download}s, but only {available_seconds}s is available."
        )

    while remaining_seconds > 0:
        allowed_intervals = invert_blocked_segments(blocked, video_duration)
        longest_interval = longest_allowed_interval_length(allowed_intervals)
        if longest_interval <= 0:
            raise ValueError("No allowed footage remains for the next clip.")

        # A heavily fragmented timeline can have enough total seconds left but
        # no single gap that fits the requested segment length. In that case we
        # take the largest available gap instead of crashing the whole batch.
        clip_length = min(segment_length_seconds, remaining_seconds, longest_interval)

        start_time = choose_start_from_allowed_intervals(allowed_intervals, clip_length)
        end_time = start_time + clip_length

        segments.append({
            "start": start_time,
            "end": end_time,
            "length": clip_length,
        })

        # Prevent overlap with both old no-go ranges and clips chosen earlier
        # in this same run.
        blocked = clamp_and_merge_segments(blocked + [TimeSegment(start_time, end_time)], video_duration)
        remaining_seconds -= clip_length

    return segments


def segment_dict_to_time_segment(segment: dict[str, int]) -> TimeSegment:
    """Converts a selected segment dictionary into the shared range object."""
    return TimeSegment(start=int(segment["start"]), end=int(segment["end"]))


def choose_replacement_segment(
    video_duration: int,
    clip_length_seconds: int,
    blocked_segments: list[TimeSegment],
) -> dict[str, int]:
    """Chooses one replacement segment that does not overlap blocked ranges."""
    allowed_intervals = invert_blocked_segments(blocked_segments, video_duration)
    start_time = choose_start_from_allowed_intervals(allowed_intervals, clip_length_seconds)
    end_time = start_time + clip_length_seconds
    return {
        "start": start_time,
        "end": end_time,
        "length": clip_length_seconds,
    }


# -----------------------------
# Downloading
# -----------------------------

def build_yt_dlp_segment_command(
    url: str,
    start_timestamp: str,
    end_timestamp: str,
    output_path_template: Path,
    format_selector: str,
    max_height: int,
) -> list[str]:
    """Builds the yt-dlp command for one segment."""
    canonical_url = normalise_youtube_url(url)
    if canonical_url is None:
        raise ValueError("A valid YouTube URL with an exact 11-character video ID is required.")
    command = build_yt_dlp_command(
        [
        "--no-playlist",
        "--newline",
        "--max-filesize",
        str(DEFAULT_MAX_DOWNLOAD_BYTES),
        "--socket-timeout",
        "30",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--download-sections",
        f"*{start_timestamp}-{end_timestamp}",
        "-f",
        format_selector,
        "-S",
        f"res:{max_height},vcodec:avc1,acodec:m4a",
        "--merge-output-format",
        "mp4",
        # This avoids yt-dlp doing direct download+merge in one ffmpeg command
        # when possible. It is sometimes slower, but safer for batch work.
        "--compat-options",
        "no-direct-merge",
        "-o",
        str(output_path_template),
        ],
        ffmpeg_binary=resolve_media_binary(
            "ffmpeg",
            excluded_roots=(output_path_template.parent,),
        ),
    )
    command.extend(yt_dlp_auth_args())
    command.append(canonical_url)
    return command


def yt_dlp_auth_args() -> list[str]:
    """Return optional local auth args for yt-dlp without hard-coding secrets.

    The launcher sets YT_DLP_COOKIES_FROM_BROWSER when the user opts into using
    a browser session. A cookie file can also be supplied by advanced users via
    YT_DLP_COOKIES_FILE without exposing it in command builders or tests.
    """

    args: list[str] = []
    browser = os.getenv(YT_DLP_COOKIES_BROWSER_ENV, "").strip()
    if browser:
        args.extend(["--cookies-from-browser", browser])

    cookies_file = os.getenv(YT_DLP_COOKIES_FILE_ENV, "").strip().strip('"').strip("'")
    if cookies_file:
        args.extend(["--cookies", cookies_file])

    return args


def build_hls_fallback_format_selector(max_height: int) -> str:
    """Builds the HLS-first selector used after a standard section download fails."""
    return HLS_FALLBACK_FORMAT_SELECTOR_TEMPLATE.format(max_height=max_height)


def find_downloaded_segment_file(raw_clip_folder: Path, prefix: str) -> Path:
    """Finds the completed file created by yt-dlp for a segment prefix."""
    candidates = []

    for path in raw_clip_folder.glob(f"{prefix}.*"):
        if (
            path.is_file()
            and path.suffix.lower() in VIDEO_EXTENSIONS
            and not path.name.endswith(".part")
            and path.stat().st_size > 0
        ):
            candidates.append(path)

    if not candidates:
        raise FileNotFoundError(f"No completed downloaded file found for segment prefix: {prefix}")

    return max(candidates, key=lambda item: item.stat().st_mtime)


def run_segment_download_attempts(
    command: list[str],
    segment_number: int,
    raw_clip_folder: Path,
    segment_prefix: str,
    logger: RunLogger,
    retries: int,
    overall_timeout_seconds: int,
    stall_timeout_seconds: int,
    attempt_label: str = "Segment",
) -> Path:
    """Runs one yt-dlp segment command with retries and returns the completed clip."""
    last_error: Exception | None = None
    display_label = f"{attempt_label} {segment_number:03d}"

    for attempt in range(1, retries + 1):
        try:
            if retries > 1:
                logger.log(f"{display_label} attempt {attempt}/{retries}")

            logger.run_command_live(
                command,
                overall_timeout_seconds=overall_timeout_seconds,
                stall_timeout_seconds=stall_timeout_seconds,
            )

            downloaded_file = find_downloaded_segment_file(raw_clip_folder, segment_prefix)
            logger.log(f"Downloaded raw clip: {downloaded_file}")
            logger.log("")
            return downloaded_file

        except Exception as error:
            last_error = error
            logger.log(f"{display_label} attempt {attempt} failed: {type(error).__name__}: {error}")
            remove_partial_files(raw_clip_folder)

            if attempt < retries:
                logger.log("Retrying this segment...")
                logger.log("")
                time.sleep(2)

    raise RuntimeError(f"{display_label} failed after {retries} attempt(s).") from last_error


def download_segment(
    url: str,
    segment: dict[str, int],
    segment_number: int,
    raw_clip_folder: Path,
    logger: RunLogger,
    format_selector: str,
    max_height: int,
    retries: int,
    overall_timeout_seconds: int,
    stall_timeout_seconds: int,
) -> Path:
    """Downloads one chosen segment using yt-dlp and returns the downloaded file."""
    start_time = segment["start"]
    end_time = segment["end"]

    start_for_filename = seconds_to_filename_time(start_time)
    end_for_filename = seconds_to_filename_time(end_time)

    start_for_ytdlp = seconds_to_ytdlp_timestamp(start_time)
    end_for_ytdlp = seconds_to_ytdlp_timestamp(end_time)

    segment_prefix = f"{segment_number:03d}_{start_for_filename}_{end_for_filename}"
    output_filename = f"{segment_prefix}.%(ext)s"
    output_path_template = raw_clip_folder / output_filename

    logger.log(
        f"Downloading segment {segment_number:03d}: "
        f"{start_for_ytdlp} to {end_for_ytdlp}"
    )

    command = build_yt_dlp_segment_command(
        url=url,
        start_timestamp=start_for_ytdlp,
        end_timestamp=end_for_ytdlp,
        output_path_template=output_path_template,
        format_selector=format_selector,
        max_height=max_height,
    )

    try:
        return run_segment_download_attempts(
            command=command,
            segment_number=segment_number,
            raw_clip_folder=raw_clip_folder,
            segment_prefix=segment_prefix,
            logger=logger,
            retries=retries,
            overall_timeout_seconds=overall_timeout_seconds,
            stall_timeout_seconds=stall_timeout_seconds,
            attempt_label="Segment",
        )
    except Exception:
        logger.log(
            "Standard segment download failed; retrying with an HLS fallback "
            "for this segment before failing the video."
        )
        logger.log("")

        hls_command = build_yt_dlp_segment_command(
            url=url,
            start_timestamp=start_for_ytdlp,
            end_timestamp=end_for_ytdlp,
            output_path_template=output_path_template,
            format_selector=build_hls_fallback_format_selector(max_height),
            max_height=max_height,
        )

        try:
            return run_segment_download_attempts(
                command=hls_command,
                segment_number=segment_number,
                raw_clip_folder=raw_clip_folder,
                segment_prefix=segment_prefix,
                logger=logger,
                retries=retries,
                overall_timeout_seconds=overall_timeout_seconds,
                stall_timeout_seconds=stall_timeout_seconds,
                attempt_label="HLS fallback",
            )
        except Exception as hls_error:
            raise RuntimeError(
                f"Segment {segment_number:03d} failed after the standard downloader "
                "and HLS fallback both failed."
            ) from hls_error


def download_segments_with_replacements(
    url: str,
    selected_segments: list[dict[str, int]],
    video_duration: int,
    no_go_segments: list[TimeSegment],
    raw_clip_folder: Path,
    logger: RunLogger,
    format_selector: str,
    max_height: int,
    retries: int,
    overall_timeout_seconds: int,
    stall_timeout_seconds: int,
    max_segment_replacements: int,
    timecode_log_path: Path,
    title: str,
    video_id: str,
    total_seconds_to_download: int,
    seed: int,
    seed_source: str,
    metadata: dict[str, object] | None,
) -> tuple[list[Path], list[dict[str, int]], list[dict[str, object]]]:
    """
    Downloads selected clips, replacing individual bad segments when possible.

    YouTube can transiently reject a single random time range while accepting
    the same video moments later. Treating that as a whole-video failure makes
    batch procurement fragile, so this loop records the bad segment and pulls
    another non-overlapping segment of the same length.
    """
    raw_clips: list[Path] = []
    failed_segments: list[dict[str, object]] = []
    segments_to_download = list(selected_segments)
    blocked_segments = clamp_and_merge_segments(
        no_go_segments + [segment_dict_to_time_segment(segment) for segment in segments_to_download],
        video_duration,
    )

    segment_index = 0
    replacement_count = 0

    while segment_index < len(segments_to_download):
        segment = segments_to_download[segment_index]
        segment_number = segment_index + 1

        try:
            raw_clip = download_segment(
                url=url,
                segment=segment,
                segment_number=segment_number,
                raw_clip_folder=raw_clip_folder,
                logger=logger,
                format_selector=format_selector,
                max_height=max_height,
                retries=retries,
                overall_timeout_seconds=overall_timeout_seconds,
                stall_timeout_seconds=stall_timeout_seconds,
            )
            raw_clips.append(raw_clip)
            segment_index += 1
            continue

        except Exception as error:
            failed_segments.append({
                "start": segment["start"],
                "end": segment["end"],
                "length": segment["length"],
                "segment_number": segment_number,
                "error": f"{type(error).__name__}: {error}",
            })
            if metadata is not None:
                metadata["failed_segments"] = failed_segments

            logger.log(
                f"Segment {segment_number:03d} could not be downloaded. "
                "Choosing a replacement segment so the video can continue."
            )
            logger.log(f"Failure reason: {type(error).__name__}: {error}")

            if replacement_count >= max_segment_replacements:
                raise RuntimeError(
                    "Too many random segments failed while trying to download this video. "
                    f"Limit: {max_segment_replacements} replacement segment(s)."
                ) from error

            blocked_segments = clamp_and_merge_segments(
                blocked_segments + [segment_dict_to_time_segment(segment)],
                video_duration,
            )
            replacement_segment = choose_replacement_segment(
                video_duration=video_duration,
                clip_length_seconds=segment["length"],
                blocked_segments=blocked_segments,
            )
            replacement_count += 1
            segments_to_download.append(replacement_segment)
            blocked_segments = clamp_and_merge_segments(
                blocked_segments + [segment_dict_to_time_segment(replacement_segment)],
                video_duration,
            )

            logger.log(
                "Replacement segment "
                f"{len(segments_to_download):03d}: "
                f"{seconds_to_ytdlp_timestamp(replacement_segment['start'])} to "
                f"{seconds_to_ytdlp_timestamp(replacement_segment['end'])} "
                f"({replacement_segment['length']} seconds)"
            )
            logger.log("")

            if metadata is not None:
                metadata["selected_segments"] = segments_to_download
                metadata["failed_segments"] = failed_segments

            write_timecode_log(
                log_path=timecode_log_path,
                url=url,
                title=title,
                video_id=video_id,
                video_duration=video_duration,
                total_seconds_to_download=total_seconds_to_download,
                segments=segments_to_download,
                no_go_segments=no_go_segments,
                seed=seed,
                seed_source=seed_source,
            )
            segment_index += 1

    return raw_clips, segments_to_download, failed_segments


# -----------------------------
# iMotions conversion and stitching
# -----------------------------

def ffprobe_media_info(path: Path, logger: RunLogger, timeout_seconds: int) -> dict:
    """Returns ffprobe JSON for one media file."""
    result = logger.run_command_capture(
        [
            str(resolve_media_binary("ffprobe", excluded_roots=(path.parent,))),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        timeout_seconds=timeout_seconds,
    )
    return json.loads(result.stdout or "{}")


def media_has_audio(path: Path, logger: RunLogger, timeout_seconds: int) -> bool:
    """Returns True if the file appears to contain at least one audio stream."""
    try:
        info = ffprobe_media_info(path, logger, timeout_seconds)
    except Exception:
        # If probing fails, let ffmpeg try the normal audio map with '?' later.
        return True

    for stream in info.get("streams", []):
        if stream.get("codec_type") == "audio":
            return True

    return False


def build_imotions_video_filter(fps: int) -> str:
    """
    Builds the video filter used for each iMotions clip.

    The scale expression keeps the existing resolution but ensures both width
    and height are even numbers, which H.264 encoders expect. fps forces a
    constant frame rate. format=yuv420p avoids high-bit-depth / unusual pixel
    formats that Windows Media Foundation and iMotions may reject.
    """
    return f"scale=trunc(iw/2)*2:trunc(ih/2)*2,fps={fps},format=yuv420p"


def build_imotions_conversion_command(
    input_path: Path,
    output_path: Path,
    has_audio: bool,
    fps: int,
    crf: int,
    audio_bitrate: str,
    audio_rate: int,
) -> list[str]:
    """Builds the ffmpeg command that normalises one clip for iMotions."""
    vf = build_imotions_video_filter(fps)

    ffmpeg = resolve_media_binary(
        "ffmpeg",
        excluded_roots=(input_path.parent, output_path.parent),
    )
    base = [str(ffmpeg), "-y", "-hide_banner", "-i", str(input_path)]

    if has_audio:
        return [
            *base,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(crf),
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-ar",
            str(audio_rate),
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

    # If the source has no audio, create silent stereo AAC audio. This gives
    # every converted clip the same basic stream layout, which makes stitching
    # and some media software happier.
    return [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-i",
        str(input_path),
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=channel_layout=stereo:sample_rate={audio_rate}",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-shortest",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(crf),
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-ar",
        str(audio_rate),
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def write_concat_list(path: Path, clips: list[Path]) -> None:
    """Writes an ffmpeg concat-demuxer file list."""
    with open(path, "w", encoding="utf-8") as file:
        for clip in clips:
            # ffmpeg concat files use forward slashes cleanly on Windows too.
            escaped = str(clip.resolve()).replace("\\", "/").replace("'", "'\\''")
            file.write(f"file '{escaped}'\n")


def build_stream_copy_stitch_command(concat_list_path: Path, output_path: Path) -> list[str]:
    """
    Builds the fast ffmpeg command that stitches raw clips without re-encoding.

    Because all clips come from the same source video and format selector, this
    usually works and avoids quality loss before the final iMotions conversion.
    """
    return [
        str(resolve_media_binary(
            "ffmpeg",
            excluded_roots=(concat_list_path.parent, output_path.parent),
        )),
        "-y",
        "-hide_banner",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def build_raw_stitch_fallback_reencode_command(
    concat_list_path: Path,
    output_path: Path,
    fps: int,
    crf: int,
    audio_bitrate: str,
    audio_rate: int,
) -> list[str]:
    """
    Fallback stitching command if stream-copy stitching fails.

    This is slower because it re-encodes, but it is more forgiving if ffmpeg
    refuses to copy-concat the downloaded segment files.
    """
    return [
        str(resolve_media_binary(
            "ffmpeg",
            excluded_roots=(concat_list_path.parent, output_path.parent),
        )),
        "-y",
        "-hide_banner",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-vf",
        build_imotions_video_filter(fps),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(crf),
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-ar",
        str(audio_rate),
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def stitch_raw_clips(
    raw_clips: list[Path],
    output_folder: Path,
    logger: RunLogger,
    fps: int,
    crf: int,
    audio_bitrate: str,
    audio_rate: int,
    command_timeout_seconds: int,
    stall_timeout_seconds: int,
) -> tuple[Path, Path]:
    """
    Stitches the downloaded raw clips into one temporary intermediate video.

    The final iMotions conversion is done after this, so this step tries to be
    quick and lossless first. If that fails, it re-encodes the intermediate as a
    fallback so the run can continue.
    """
    if not raw_clips:
        raise ValueError("No raw clips were supplied for stitching.")

    raw_stitched_path = output_folder / RAW_STITCHED_VIDEO_NAME
    concat_list_path = output_folder / CONCAT_RAW_LIST_NAME
    write_concat_list(concat_list_path, raw_clips)

    logger.log(f"Stitching {len(raw_clips)} raw clip(s) into temporary video: {raw_stitched_path.name}")

    try:
        logger.run_command_live(
            build_stream_copy_stitch_command(concat_list_path, raw_stitched_path),
            overall_timeout_seconds=command_timeout_seconds,
            stall_timeout_seconds=stall_timeout_seconds,
        )
    except Exception as error:
        logger.log(f"Fast raw stitch failed: {type(error).__name__}: {error}")
        logger.log("Retrying raw stitch with a re-encoding fallback...")
        logger.run_command_live(
            build_raw_stitch_fallback_reencode_command(
                concat_list_path=concat_list_path,
                output_path=raw_stitched_path,
                fps=fps,
                crf=crf,
                audio_bitrate=audio_bitrate,
                audio_rate=audio_rate,
            ),
            overall_timeout_seconds=command_timeout_seconds,
            stall_timeout_seconds=stall_timeout_seconds,
        )

    if not raw_stitched_path.exists() or raw_stitched_path.stat().st_size == 0:
        raise RuntimeError(f"Temporary stitched video was not created: {raw_stitched_path}")

    logger.log(f"Temporary stitched raw video written: {raw_stitched_path}")
    logger.log("")
    return raw_stitched_path, concat_list_path


def convert_stitched_video_for_imotions(
    stitched_input: Path,
    output_folder: Path,
    logger: RunLogger,
    fps: int,
    crf: int,
    audio_bitrate: str,
    audio_rate: int,
    command_timeout_seconds: int,
    stall_timeout_seconds: int,
    probe_timeout_seconds: int,
) -> Path:
    """Converts the one stitched video into the final iMotions-friendly MP4."""
    output_path = output_folder / STITCHED_VIDEO_NAME

    logger.log(f"Converting stitched video for iMotions: {stitched_input.name} -> {output_path.name}")
    has_audio = media_has_audio(stitched_input, logger, probe_timeout_seconds)

    if has_audio:
        logger.log("Audio stream detected; converting audio to AAC stereo.")
    else:
        logger.log("No audio stream detected; adding silent AAC stereo audio.")

    command = build_imotions_conversion_command(
        input_path=stitched_input,
        output_path=output_path,
        has_audio=has_audio,
        fps=fps,
        crf=crf,
        audio_bitrate=audio_bitrate,
        audio_rate=audio_rate,
    )

    logger.run_command_live(
        command,
        overall_timeout_seconds=command_timeout_seconds,
        stall_timeout_seconds=stall_timeout_seconds,
    )

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"iMotions conversion did not create a valid file: {output_path}")

    logger.log(f"Final iMotions video written: {output_path}")
    logger.log("")
    return output_path


def remove_file_if_exists(path: Path, logger: RunLogger) -> None:
    """Deletes a temporary file if it exists, without failing the whole run."""
    try:
        if path.exists() and path.is_file():
            path.unlink()
            logger.log(f"Removed temporary file: {path}")
    except OSError as error:
        logger.log(f"Could not remove temporary file {path}: {error}")


def delete_raw_clips_after_success(raw_clips: list[Path], raw_clip_folder: Path, logger: RunLogger) -> None:
    """
    Deletes raw segment clips after the final stitched iMotions video is made.

    This is optional because raw clips are useful for auditing and debugging.
    """
    logger.log("Deleting raw segment clips after successful final conversion...")

    for clip in raw_clips:
        try:
            if clip.exists() and clip.is_file():
                clip.unlink()
                logger.log(f"Deleted raw clip: {clip.name}")
        except OSError as error:
            logger.log(f"Could not delete raw clip {clip}: {error}")

    try:
        if raw_clip_folder.exists() and not any(raw_clip_folder.iterdir()):
            raw_clip_folder.rmdir()
            logger.log(f"Removed empty raw clips folder: {raw_clip_folder}")
    except OSError as error:
        logger.log(f"Could not remove raw clips folder {raw_clip_folder}: {error}")

    logger.log("")


# -----------------------------
# Timecode logging
# -----------------------------

def write_timecode_log(
    log_path: Path,
    url: str,
    title: str,
    video_id: str,
    video_duration: int,
    total_seconds_to_download: int,
    segments: list[dict[str, int]],
    no_go_segments: list[TimeSegment],
    seed: int,
    seed_source: str,
    raw_stitched_video: Path | None = None,
    stitched_video: Path | None = None,
) -> None:
    """Writes a clean timecode log showing which parts were selected."""
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"Title: {title}\n")
        log_file.write(f"Video ID: {video_id}\n")
        log_file.write(f"URL: {url}\n")
        log_file.write("\n")
        log_file.write(f"Video length: {video_duration} seconds\n")
        log_file.write(f"Maximum downloadable footage: {total_seconds_to_download} seconds\n")
        log_file.write(f"Random seed: {seed}\n")
        log_file.write(f"Random seed source: {seed_source}\n")
        log_file.write("\nDownloaded segments:\n")

        for index, segment in enumerate(segments, start=1):
            start = seconds_to_ytdlp_timestamp(segment["start"])
            end = seconds_to_ytdlp_timestamp(segment["end"])
            length = segment["length"]
            log_file.write(f"{index:03d}: {start} to {end} ({length} seconds)\n")

        if no_go_segments:
            log_file.write("\nNo-go segments from previous runs:\n")
            for index, segment in enumerate(no_go_segments, start=1):
                start = seconds_to_ytdlp_timestamp(segment.start)
                end = seconds_to_ytdlp_timestamp(segment.end)
                log_file.write(f"{index:03d}: {start} to {end} ({segment.length} seconds)\n")

        if raw_stitched_video:
            log_file.write("\nTemporary stitched raw video:\n")
            log_file.write(f"- {raw_stitched_video.as_posix()}\n")

        if stitched_video:
            log_file.write("\nFinal stitched iMotions video:\n")
            log_file.write(f"- {stitched_video.as_posix()}\n")

def folder_contains_finished_video(output_folder: Path) -> bool:
    """Returns True if the folder appears to contain a completed useful output."""
    stitched_path = output_folder / STITCHED_VIDEO_NAME
    if stitched_path.exists() and stitched_path.stat().st_size > 0:
        return True

    if not output_folder.exists():
        return False

    for file_path in output_folder.rglob("*.mp4"):
        if file_path.is_file() and not file_path.name.endswith(".part") and file_path.stat().st_size > 0:
            return True

    return False


def now_iso() -> str:
    """Return a timezone-aware timestamp for metadata files."""

    return datetime.now().astimezone().isoformat(timespec="seconds")


def segment_to_metadata(segment: TimeSegment) -> dict[str, int]:
    """Serialize a no-go segment for JSON metadata."""

    return {"start": segment.start, "end": segment.end, "length": segment.length}


def path_is_non_empty_file(path: Path) -> bool:
    """Return True when a path is an existing non-empty file."""

    return path.exists() and path.is_file() and path.stat().st_size > 0


def non_empty_raw_clips(output_folder: Path) -> list[Path]:
    """Return completed raw clip files in the standard raw clip folder."""

    raw_clip_folder = output_folder / RAW_CLIP_FOLDER_NAME
    if not raw_clip_folder.exists():
        return []
    return [
        path
        for path in sorted(raw_clip_folder.rglob("*.mp4"))
        if path_is_non_empty_file(path) and not path.name.endswith(".part")
    ]


def expected_outputs_exist(output_folder: Path, metadata: dict[str, object]) -> bool:
    """Validate the outputs required for this run mode."""

    if bool(metadata.get("skip_stitch")) or bool(metadata.get("skip_imotions_conversion")):
        return bool(non_empty_raw_clips(output_folder))
    return path_is_non_empty_file(output_folder / STITCHED_VIDEO_NAME)


def write_extraction_metadata(output_folder: Path, metadata: dict[str, object]) -> Path:
    """Write the machine-readable extraction metadata JSON."""

    metadata_path = output_folder / METADATA_FILE_NAME
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metadata_path


def finalize_extraction_metadata(output_folder: Path, metadata: dict[str, object]) -> tuple[Path, Path]:
    """Write final metadata and a completion marker after required outputs exist."""

    final_metadata = dict(metadata)
    final_metadata["run_finished_at"] = final_metadata.get("run_finished_at") or now_iso()
    final_metadata["status"] = "success"

    if not expected_outputs_exist(output_folder, final_metadata):
        raise RuntimeError("The run finished, but the expected extraction outputs were not created.")

    output_files = list(final_metadata.get("output_files_created") or [])
    for clip in non_empty_raw_clips(output_folder):
        clip_text = str(clip)
        if clip_text not in output_files:
            output_files.append(clip_text)
    stitched_path = output_folder / STITCHED_VIDEO_NAME
    if path_is_non_empty_file(stitched_path) and str(stitched_path) not in output_files:
        output_files.append(str(stitched_path))
    final_metadata["output_files_created"] = output_files

    metadata_path = write_extraction_metadata(output_folder, final_metadata)
    completion_path = output_folder / COMPLETION_FILE_NAME
    completion_payload = {
        key: final_metadata.get(key)
        for key in [
            "url",
            "video_id",
            "title",
            "seed",
            "seed_source",
            "percentage",
            "segment_length_seconds",
            "selected_segments",
            "skip_stitch",
            "skip_imotions_conversion",
            "output_files_created",
            "run_started_at",
            "run_finished_at",
            "status",
        ]
    }
    completion_path.write_text(json.dumps(completion_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metadata_path, completion_path


# -----------------------------
# Main script
# -----------------------------

def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Download random YouTube segments, stitch them, then create one iMotions-friendly MP4."
    )

    parser.add_argument("url", help="The YouTube video URL")
    parser.add_argument("--seed", type=int, default=None, help="Optional random seed for repeatable segments.")

    parser.add_argument(
        "--segment-length",
        type=int,
        default=DEFAULT_SEGMENT_LENGTH_SECONDS,
        help=f"Normal segment length in seconds. Default: {DEFAULT_SEGMENT_LENGTH_SECONDS}",
    )

    parser.add_argument(
        "--percentage",
        type=float,
        default=DEFAULT_DOWNLOAD_PERCENTAGE,
        help=f"Fraction of video to download. Default: {DEFAULT_DOWNLOAD_PERCENTAGE} for 10%%.",
    )

    parser.add_argument(
        "--max-height",
        type=int,
        default=DEFAULT_MAX_HEIGHT,
        help=f"Preferred maximum download height. Default: {DEFAULT_MAX_HEIGHT}",
    )

    parser.add_argument(
        "--format",
        dest="format_selector",
        default=None,
        help="Optional custom yt-dlp format selector.",
    )

    parser.add_argument(
        "--exclude-segment",
        action="append",
        default=[],
        help=(
            "No-go range to avoid when selecting new clips, START-END. "
            "Can be used multiple times, e.g. --exclude-segment 00:01:21-00:01:51"
        ),
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="How many times to try each segment before failing. Default: 2",
    )

    parser.add_argument(
        "--max-segment-replacements",
        type=int,
        default=DEFAULT_MAX_SEGMENT_REPLACEMENTS,
        help=(
            "How many failed random segments can be replaced before the video fails. "
            f"Default: {DEFAULT_MAX_SEGMENT_REPLACEMENTS}"
        ),
    )

    parser.add_argument(
        "--stall-timeout",
        type=int,
        default=90,
        help="Kill ffmpeg if media time does not advance for this many seconds. Default: 90",
    )

    parser.add_argument(
        "--command-timeout",
        type=int,
        default=900,
        help="Maximum seconds allowed for one download/convert/stitch command. Default: 900",
    )

    parser.add_argument(
        "--info-timeout",
        type=int,
        default=180,
        help="Maximum seconds allowed for reading video info. Default: 180",
    )

    parser.add_argument(
        "--probe-timeout",
        type=int,
        default=60,
        help="Maximum seconds allowed for ffprobe. Default: 60",
    )

    parser.add_argument(
        "--imotions-fps",
        type=int,
        default=DEFAULT_IMOTIONS_FPS,
        help=f"Frame rate for iMotions outputs. Default: {DEFAULT_IMOTIONS_FPS}",
    )

    parser.add_argument(
        "--imotions-crf",
        type=int,
        default=DEFAULT_IMOTIONS_CRF,
        help=f"H.264 quality CRF for converted clips. Lower is bigger/better. Default: {DEFAULT_IMOTIONS_CRF}",
    )

    parser.add_argument(
        "--skip-imotions-conversion",
        action="store_true",
        help="Download raw clips only. Do not create the stitched iMotions output.",
    )

    parser.add_argument(
        "--skip-stitch",
        "--no-stitch",
        dest="skip_stitch",
        action="store_true",
        help="Download raw clips only into the raw_clips subfolder; do not stitch or create the final iMotions MP4.",
    )

    parser.add_argument(
        "--keep-intermediate-stitched",
        action="store_true",
        help="Keep the temporary stitched raw video used before iMotions conversion.",
    )

    parser.add_argument(
        "--delete-raw-clips-after-success",
        action="store_true",
        help="After the final stitched iMotions video is created, delete the raw segment clips.",
    )

    args = parser.parse_args()

    logger = RunLogger()
    video_id = None
    output_folder: Path | None = None
    metadata: dict[str, object] | None = None
    run_started_at = now_iso()

    try:
        seed, seed_source = resolve_seed(args.seed)

        if args.percentage <= 0 or args.percentage > 1:
            raise ValueError("--percentage must be greater than 0 and no more than 1.")

        if args.segment_length <= 0:
            raise ValueError("--segment-length must be greater than 0.")

        if args.max_segment_replacements < 0:
            raise ValueError("--max-segment-replacements cannot be negative.")

        if args.imotions_fps <= 0:
            raise ValueError("--imotions-fps must be greater than 0.")

        format_selector = args.format_selector or DEFAULT_FORMAT_SELECTOR_TEMPLATE.format(max_height=args.max_height)
        raw_no_go_segments = [parse_exclude_segment(value) for value in args.exclude_segment]

        logger.log("Script settings:")
        logger.log(f"Segment length: {args.segment_length} seconds")
        logger.log(f"Download percentage: {args.percentage * 100:.2f}%")
        logger.log(f"Preferred maximum download height: {args.max_height}p")
        logger.log(f"Format selector: {format_selector}")
        logger.log(f"Retries per segment: {args.retries}")
        logger.log(f"Maximum segment replacements: {args.max_segment_replacements}")
        logger.log(f"Stall timeout: {args.stall_timeout} seconds")
        logger.log(f"Command timeout: {args.command_timeout} seconds")
        logger.log(f"iMotions conversion enabled: {not args.skip_imotions_conversion}")
        logger.log(f"Stitch-then-convert enabled: {not args.skip_imotions_conversion and not args.skip_stitch}")
        logger.log(f"iMotions FPS: {args.imotions_fps}")
        logger.log(f"iMotions CRF: {args.imotions_crf}")
        logger.log(f"Keep temporary stitched raw video: {args.keep_intermediate_stitched}")
        logger.log(f"Delete raw clips after success: {args.delete_raw_clips_after_success}")
        logger.log(f"Random seed: {seed}")
        logger.log(f"Random seed source: {seed_source}")
        logger.log("")

        video_info = get_video_info(args.url, logger, args.info_timeout)

        video_title = str(video_info["title"])
        video_duration = int(video_info["duration"])
        video_id = get_youtube_video_id(args.url)

        no_go_segments = clamp_and_merge_segments(raw_no_go_segments, video_duration)
        total_seconds_to_download = math.floor(video_duration * args.percentage)

        if total_seconds_to_download <= 0:
            raise ValueError("This video is too short to download a useful sample.")

        output_folder_name = make_video_output_folder_name(video_title, video_id)
        output_folder = Path(output_folder_name)
        raw_clip_folder = output_folder / RAW_CLIP_FOLDER_NAME

        output_folder.mkdir(exist_ok=True)
        raw_clip_folder.mkdir(exist_ok=True)

        timecode_log_folder = Path(TIMECODE_LOG_FOLDER_NAME)
        timecode_log_folder.mkdir(exist_ok=True)
        timecode_log_path = timecode_log_folder / f"{output_folder_name}.txt"

        segments = make_random_segments(
            video_duration=video_duration,
            total_seconds_to_download=total_seconds_to_download,
            segment_length_seconds=args.segment_length,
            no_go_segments=no_go_segments,
        )

        metadata = {
            "url": args.url,
            "video_id": video_id,
            "title": video_title,
            "video_duration_seconds": video_duration,
            "percentage": args.percentage,
            "total_seconds_to_download": total_seconds_to_download,
            "segment_length_seconds": args.segment_length,
            "seed": seed,
            "seed_source": seed_source,
            "no_go_segments": [segment_to_metadata(segment) for segment in no_go_segments],
            "selected_segments": segments,
            "failed_segments": [],
            "max_segment_replacements": args.max_segment_replacements,
            "skip_stitch": bool(args.skip_stitch),
            "skip_imotions_conversion": bool(args.skip_imotions_conversion),
            "imotions_fps": args.imotions_fps,
            "imotions_crf": args.imotions_crf,
            "output_files_created": [],
            "run_started_at": run_started_at,
            "run_finished_at": None,
            "status": "running",
        }
        write_extraction_metadata(output_folder, metadata)

        logger.log("Video found:")
        logger.log(f"Title: {video_title}")
        logger.log(f"Video ID: {video_id}")
        logger.log(f"Length: {video_duration} seconds")
        logger.log(f"Downloading: {total_seconds_to_download} seconds total")
        logger.log(f"Output folder: {output_folder}")
        logger.log(f"Raw clips folder: {raw_clip_folder}")
        logger.log(f"Final iMotions video: {output_folder / STITCHED_VIDEO_NAME if not args.skip_imotions_conversion else 'disabled'}")
        logger.log(f"Timecode log: {timecode_log_path}")
        logger.log(f"Full console log while running: {Path(FULL_LOG_FOLDER_NAME) / LATEST_LOG_NAME}")
        logger.log("")

        if no_go_segments:
            logger.log("No-go segments from previous runs:")
            for index, segment in enumerate(no_go_segments, start=1):
                logger.log(
                    f"{index:03d}: "
                    f"{seconds_to_ytdlp_timestamp(segment.start)} to "
                    f"{seconds_to_ytdlp_timestamp(segment.end)} "
                    f"({segment.length} seconds)"
                )
            logger.log("")

        logger.log("Chosen new segments:")
        for index, segment in enumerate(segments, start=1):
            logger.log(
                f"{index:03d}: "
                f"{seconds_to_ytdlp_timestamp(segment['start'])} to "
                f"{seconds_to_ytdlp_timestamp(segment['end'])} "
                f"({segment['length']} seconds)"
            )
        logger.log("")

        # Write the initial log before downloading. If a later segment fails,
        # the router can still use these chosen timecodes as no-go ranges next time.
        write_timecode_log(
            log_path=timecode_log_path,
            url=args.url,
            title=video_title,
            video_id=video_id,
            video_duration=video_duration,
            total_seconds_to_download=total_seconds_to_download,
            segments=segments,
            no_go_segments=no_go_segments,
            seed=seed,
            seed_source=seed_source,
        )

        logger.log("Initial timecode log written.")
        logger.log("")

        raw_clips, segments, failed_segments = download_segments_with_replacements(
            url=args.url,
            selected_segments=segments,
            video_duration=video_duration,
            no_go_segments=no_go_segments,
            raw_clip_folder=raw_clip_folder,
            logger=logger,
            format_selector=format_selector,
            max_height=args.max_height,
            retries=args.retries,
            overall_timeout_seconds=args.command_timeout,
            stall_timeout_seconds=args.stall_timeout,
            max_segment_replacements=args.max_segment_replacements,
            timecode_log_path=timecode_log_path,
            title=video_title,
            video_id=video_id,
            total_seconds_to_download=total_seconds_to_download,
            seed=seed,
            seed_source=seed_source,
            metadata=metadata,
        )

        if metadata is not None:
            metadata["selected_segments"] = segments
            metadata["failed_segments"] = failed_segments

        if metadata is not None:
            metadata["output_files_created"] = [str(path) for path in raw_clips if path_is_non_empty_file(path)]

        raw_stitched_video: Path | None = None
        concat_list_path: Path | None = None
        stitched_video: Path | None = None

        if args.skip_imotions_conversion or args.skip_stitch:
            logger.log("Stitch/iMotions step skipped. Raw clips only were created.")
            logger.log("")
        else:
            logger.log("Starting stitch-then-iMotions conversion pipeline.")
            logger.log("")

            raw_stitched_video, concat_list_path = stitch_raw_clips(
                raw_clips=raw_clips,
                output_folder=output_folder,
                logger=logger,
                fps=args.imotions_fps,
                crf=args.imotions_crf,
                audio_bitrate=DEFAULT_IMOTIONS_AUDIO_BITRATE,
                audio_rate=DEFAULT_IMOTIONS_AUDIO_RATE,
                command_timeout_seconds=args.command_timeout,
                stall_timeout_seconds=args.stall_timeout,
            )

            stitched_video = convert_stitched_video_for_imotions(
                stitched_input=raw_stitched_video,
                output_folder=output_folder,
                logger=logger,
                fps=args.imotions_fps,
                crf=args.imotions_crf,
                audio_bitrate=DEFAULT_IMOTIONS_AUDIO_BITRATE,
                audio_rate=DEFAULT_IMOTIONS_AUDIO_RATE,
                command_timeout_seconds=args.command_timeout,
                stall_timeout_seconds=args.stall_timeout,
                probe_timeout_seconds=args.probe_timeout,
            )

            if not args.keep_intermediate_stitched:
                remove_file_if_exists(raw_stitched_video, logger)
                raw_stitched_video = None

            if concat_list_path is not None:
                remove_file_if_exists(concat_list_path, logger)

            if args.delete_raw_clips_after_success:
                delete_raw_clips_after_success(raw_clips, raw_clip_folder, logger)

        if metadata is not None:
            output_files = [str(path) for path in raw_clips if path_is_non_empty_file(path)]
            if raw_stitched_video and path_is_non_empty_file(raw_stitched_video):
                output_files.append(str(raw_stitched_video))
            if stitched_video and path_is_non_empty_file(stitched_video):
                output_files.append(str(stitched_video))
            output_files.append(str(timecode_log_path))
            metadata["output_files_created"] = output_files

        # Rewrite the timecode log now that we know the output file paths.
        write_timecode_log(
            log_path=timecode_log_path,
            url=args.url,
            title=video_title,
            video_id=video_id,
            video_duration=video_duration,
            total_seconds_to_download=total_seconds_to_download,
            segments=segments,
            no_go_segments=no_go_segments,
            seed=seed,
            seed_source=seed_source,
            raw_stitched_video=raw_stitched_video,
            stitched_video=stitched_video,
        )

        metadata_path, completion_path = finalize_extraction_metadata(output_folder, metadata)

        logger.log("Done.")
        logger.log(f"Output folder: {output_folder}")
        logger.log(f"Metadata saved in: {metadata_path}")
        logger.log(f"Completion marker saved in: {completion_path}")
        if raw_clip_folder.exists():
            logger.log(f"Raw clips saved in: {raw_clip_folder}")
        else:
            logger.log("Raw clips were deleted after successful final conversion.")

        if raw_stitched_video:
            logger.log(f"Temporary stitched raw video kept: {raw_stitched_video}")

        if stitched_video:
            logger.log(f"Final stitched iMotions video: {stitched_video}")

        logger.log(f"Timecodes saved in: {timecode_log_path}")

    except Exception:
        failure_traceback = traceback.format_exc()
        if output_folder is not None and metadata is not None:
            failure_metadata = dict(metadata)
            failure_metadata["status"] = "failed"
            failure_metadata["run_finished_at"] = now_iso()
            failure_metadata["error"] = failure_traceback
            write_extraction_metadata(output_folder, failure_metadata)
        logger.log("")
        logger.log("ERROR: The script failed.")
        logger.log("")
        logger.log(failure_traceback)
        raise

    finally:
        finished_log_path = logger.finish(suffix=video_id)
        print()
        print(f"Full console log saved as: {finished_log_path}")


if __name__ == "__main__":
    main()
