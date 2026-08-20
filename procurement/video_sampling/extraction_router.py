#!/usr/bin/env python3
"""
extraction_router.py

This is the middle script used by run_docx_extractions.py.

Flow:

    run_docx_extractions.py
        -> extraction_router.py
            -> extractor.py

Why this exists
---------------
Sometimes a batch run fails after extractor.py has already chosen and
logged a full 10% set of timecodes for a YouTube video. If the same video is
run again, we usually do not want to randomly select the same footage again.

This router checks previous timecode logs for the same YouTube video ID. If it
finds previous 10% timecode selections, it passes those ranges to
extractor.py as no-go / excluded segments.

extractor.py still calculates the new sample size from the full video
length. The previous no-go timestamps only block where new clips can be chosen;
they do not reduce the video length or reduce the new 10% target.

Expected files in the same folder:

    run_docx_extractions.py
    extraction_router.py
    extractor.py
    source_catalog.docx

Normal use:

    python extraction_router.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

The DOCX runner calls this automatically, so you usually do not run it yourself.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__ in {None, ""}:  # pragma: no cover - supports direct script execution.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from procurement.console import configure_utf8_stdio
from procurement.external_tools import credential_free_media_environment


TIMECODE_LOG_FOLDER_NAME = "video_timecodes"
TIMECODE_HISTORY_FOLDER_NAME = "video_timecodes_previous_runs"
DEFAULT_EXTRACTOR_NAME = "extractor.py"


# -----------------------------
# Small data objects
# -----------------------------

@dataclass(frozen=True)
class TimecodeSegment:
    """One previously selected time range."""

    start_seconds: int
    end_seconds: int

    @property
    def length_seconds(self) -> int:
        return max(0, self.end_seconds - self.start_seconds)


@dataclass
class ParsedTimecodeLog:
    """The useful information parsed from one timecode log file."""

    path: Path
    video_id: str | None
    maximum_downloadable_seconds: int | None
    downloaded_segments: list[TimecodeSegment]

    @property
    def downloaded_total_seconds(self) -> int:
        return sum(segment.length_seconds for segment in self.downloaded_segments)

    def looks_like_full_selection(self) -> bool:
        """
        Returns True if this log appears to contain a full previous sample.

        In normal 10% logs, the sum of segment lengths should match the
        'Maximum downloadable footage' line. We allow a tiny tolerance because
        old logs may have formatting differences.
        """
        if not self.downloaded_segments:
            return False

        if self.maximum_downloadable_seconds is None:
            # Older or hand-edited logs might not have this line. If segments
            # are present and the video ID matches, still treat them as useful.
            return True

        return self.downloaded_total_seconds >= max(0, self.maximum_downloadable_seconds - 1)


# -----------------------------
# YouTube helpers
# -----------------------------

def clean_possible_url(url: str) -> str:
    """Removes punctuation that can accidentally stick to a URL."""
    return url.strip().rstrip(".,;:)]}")


def get_youtube_video_id(url: str) -> str:
    """Extracts the YouTube video ID from common YouTube URL formats."""
    parsed_url = urlparse(clean_possible_url(url))
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


# -----------------------------
# Time parsing helpers
# -----------------------------

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


def seconds_to_ytdlp_timestamp(seconds: int) -> str:
    """Converts seconds to HH:MM:SS for extractor.py."""
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


# -----------------------------
# Timecode log parsing
# -----------------------------

SEGMENT_LINE_RE = re.compile(
    r"^\s*\d{1,4}\s*:\s*"
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\s+"
    r"to\s+"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)",
    re.IGNORECASE,
)

MAXIMUM_LINE_RE = re.compile(
    r"maximum\s+(?:downloadable\s+)?(?:footage\s*)?(?:,\s*10%\s*)?:?\s*(\d+)",
    re.IGNORECASE,
)

VIDEO_ID_LINE_RE = re.compile(r"^\s*Video\s+ID\s*:\s*(.+?)\s*$", re.IGNORECASE)


def parse_timecode_log(path: Path) -> ParsedTimecodeLog:
    """
    Parses one timecode log written by extractor.py.

    Only lines under the 'Downloaded segments:' section are treated as previous
    footage. Any 'No-go' / excluded section is ignored here because it was not
    newly downloaded by that log.
    """
    video_id: str | None = None
    maximum_downloadable_seconds: int | None = None
    downloaded_segments: list[TimecodeSegment] = []
    in_downloaded_section = False

    with open(path, "r", encoding="utf-8", errors="replace") as file:
        for raw_line in file:
            line = raw_line.strip()

            video_id_match = VIDEO_ID_LINE_RE.match(line)
            if video_id_match:
                video_id = video_id_match.group(1).strip()
                continue

            maximum_match = MAXIMUM_LINE_RE.search(line)
            if maximum_match:
                maximum_downloadable_seconds = int(maximum_match.group(1))
                continue

            lower_line = line.lower()

            if lower_line.startswith("downloaded segments"):
                in_downloaded_section = True
                continue

            if in_downloaded_section and (
                lower_line.startswith("no-go")
                or lower_line.startswith("excluded")
                or lower_line.startswith("previous")
                or lower_line.endswith("segments:") and not lower_line.startswith("downloaded")
            ):
                in_downloaded_section = False
                continue

            if not in_downloaded_section:
                continue

            segment_match = SEGMENT_LINE_RE.match(line)
            if not segment_match:
                continue

            start_seconds = timestamp_to_seconds(segment_match.group("start"))
            end_seconds = timestamp_to_seconds(segment_match.group("end"))

            if end_seconds > start_seconds:
                downloaded_segments.append(TimecodeSegment(start_seconds, end_seconds))

    return ParsedTimecodeLog(
        path=path,
        video_id=video_id,
        maximum_downloadable_seconds=maximum_downloadable_seconds,
        downloaded_segments=downloaded_segments,
    )


def find_candidate_timecode_logs(
    video_id: str,
    timecode_folder: Path,
    history_folder: Path,
) -> list[Path]:
    """
    Finds current and archived timecode logs that might belong to this video.
    """
    candidates: list[Path] = []

    search_folders = [timecode_folder, history_folder]

    for folder in search_folders:
        if not folder.exists():
            continue

        for path in folder.rglob("*.txt"):
            # File names normally contain [videoID], so use that as a fast path.
            # We still parse the file afterwards to confirm the Video ID line.
            if video_id in path.name:
                candidates.append(path)

    return sorted(set(candidates), key=lambda item: item.stat().st_mtime)


def collect_previous_no_go_segments(
    video_id: str,
    timecode_folder: Path,
    history_folder: Path,
) -> list[TimecodeSegment]:
    """
    Returns previous downloaded segments for this video ID.
    """
    no_go_segments: list[TimecodeSegment] = []
    logs = find_candidate_timecode_logs(video_id, timecode_folder, history_folder)

    if not logs:
        print("No previous timecode logs found for this video.")
        return []

    print(f"Previous timecode logs found for {video_id}: {len(logs)}")

    for log_path in logs:
        try:
            parsed_log = parse_timecode_log(log_path)
        except Exception as error:
            print(f"  Skipping unreadable log: {log_path} ({type(error).__name__}: {error})")
            continue

        if parsed_log.video_id and parsed_log.video_id != video_id:
            print(f"  Skipping log for different video ID: {log_path}")
            continue

        if not parsed_log.looks_like_full_selection():
            print(f"  Skipping log without a full previous selection: {log_path.name}")
            continue

        print(
            f"  Using {log_path.name}: "
            f"{len(parsed_log.downloaded_segments)} previous segment(s), "
            f"{parsed_log.downloaded_total_seconds} second(s) total"
        )
        no_go_segments.extend(parsed_log.downloaded_segments)

    return merge_segments(no_go_segments)


def merge_segments(segments: list[TimecodeSegment]) -> list[TimecodeSegment]:
    """
    Merges overlapping or touching no-go segments.
    """
    if not segments:
        return []

    sorted_segments = sorted(segments, key=lambda segment: (segment.start_seconds, segment.end_seconds))
    merged: list[TimecodeSegment] = []

    current_start = sorted_segments[0].start_seconds
    current_end = sorted_segments[0].end_seconds

    for segment in sorted_segments[1:]:
        if segment.start_seconds <= current_end:
            current_end = max(current_end, segment.end_seconds)
        else:
            merged.append(TimecodeSegment(current_start, current_end))
            current_start = segment.start_seconds
            current_end = segment.end_seconds

    merged.append(TimecodeSegment(current_start, current_end))
    return merged


# -----------------------------
# History archiving
# -----------------------------

def archive_matching_timecode_logs(
    video_id: str,
    timecode_folder: Path,
    history_folder: Path,
    label: str,
) -> None:
    """
    Copies current timecode logs into a history folder.

    This protects older timecode choices before extractor.py overwrites
    the normal timecode log for a new attempt.
    """
    if not timecode_folder.exists():
        return

    history_folder.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    for path in timecode_folder.glob(f"*{video_id}*.txt"):
        destination = history_folder / f"{path.stem}__{label}_{timestamp}{path.suffix}"

        counter = 2
        while destination.exists():
            destination = history_folder / f"{path.stem}__{label}_{timestamp}_{counter:03d}{path.suffix}"
            counter += 1

        try:
            shutil.copy2(path, destination)
            print(f"Archived timecode log: {destination}")
        except OSError as error:
            print(f"Could not archive {path}: {error}")


# -----------------------------
# Running the real extractor
# -----------------------------

def build_extractor_command(
    extractor_script: Path,
    url: str,
    passthrough_args: list[str],
    no_go_segments: list[TimecodeSegment],
) -> list[str]:
    """
    Builds the command that calls extractor.py.
    """
    command = [sys.executable, str(extractor_script), url]
    command.extend(passthrough_args)

    for segment in no_go_segments:
        command.append("--exclude-segment")
        command.append(
            f"{seconds_to_ytdlp_timestamp(segment.start_seconds)}-"
            f"{seconds_to_ytdlp_timestamp(segment.end_seconds)}"
        )

    return command


def command_to_display(command: list[str]) -> str:
    """Creates a readable command string for console output."""
    return " ".join(f'"{part}"' if " " in str(part) else str(part) for part in command)


# -----------------------------
# Main script
# -----------------------------

def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description=(
            "Middle script that checks previous timecode logs, then calls extractor.py "
            "with old timestamps marked as no-go ranges."
        )
    )

    parser.add_argument("url", help="The YouTube video URL.")

    parser.add_argument(
        "--extractor",
        default=DEFAULT_EXTRACTOR_NAME,
        help="Path to extractor.py. Default: extractor.py beside this router.",
    )

    parser.add_argument(
        "--timecode-folder",
        default=TIMECODE_LOG_FOLDER_NAME,
        help="Folder containing current timecode logs. Default: video_timecodes",
    )

    parser.add_argument(
        "--history-folder",
        default=TIMECODE_HISTORY_FOLDER_NAME,
        help="Folder used for archived previous timecode logs. Default: video_timecodes_previous_runs",
    )

    parser.add_argument(
        "--output-root",
        default=None,
        help=(
            "Folder where extractor.py should create outputs and logs. "
            "Defaults to this router's folder for backwards compatibility."
        ),
    )

    parser.add_argument(
        "--ignore-previous",
        action="store_true",
        help="Do not use old timecode logs as no-go ranges.",
    )

    # parse_known_args is important: any normal extractor.py arguments
    # such as --max-height 480 are left in passthrough_args.
    args, passthrough_args = parser.parse_known_args()

    script_folder = Path(__file__).resolve().parent
    output_root = Path(args.output_root).resolve() if args.output_root else script_folder
    output_root.mkdir(parents=True, exist_ok=True)

    extractor_script = Path(args.extractor)
    if not extractor_script.is_absolute():
        extractor_script = script_folder / extractor_script

    if not extractor_script.exists():
        raise FileNotFoundError(f"Could not find extractor.py at: {extractor_script}")

    timecode_folder = Path(args.timecode_folder)
    if not timecode_folder.is_absolute():
        timecode_folder = output_root / timecode_folder

    history_folder = Path(args.history_folder)
    if not history_folder.is_absolute():
        history_folder = output_root / history_folder

    video_id = get_youtube_video_id(args.url)

    print("\n" + "=" * 70)
    print("Video extraction router")
    print(f"Video ID: {video_id}")
    print(f"URL: {args.url}")
    print(f"Output root: {output_root}")
    print("=" * 70)

    if args.ignore_previous:
        no_go_segments: list[TimecodeSegment] = []
        print("Previous timecode logs ignored because --ignore-previous was supplied.")
    else:
        no_go_segments = collect_previous_no_go_segments(
            video_id=video_id,
            timecode_folder=timecode_folder,
            history_folder=history_folder,
        )

    if no_go_segments:
        print("\nNo-go segments that will be passed to extractor.py:")
        for index, segment in enumerate(no_go_segments, start=1):
            print(
                f"  {index:03d}: "
                f"{seconds_to_ytdlp_timestamp(segment.start_seconds)} to "
                f"{seconds_to_ytdlp_timestamp(segment.end_seconds)} "
                f"({segment.length_seconds} seconds)"
            )
    else:
        print("\nNo no-go segments will be used for this video.")

    # Protect the current log before extractor.py possibly overwrites it.
    if not args.ignore_previous:
        archive_matching_timecode_logs(
            video_id=video_id,
            timecode_folder=timecode_folder,
            history_folder=history_folder,
            label="before_new_attempt",
        )

    command = build_extractor_command(
        extractor_script=extractor_script,
        url=args.url,
        passthrough_args=passthrough_args,
        no_go_segments=no_go_segments,
    )

    print("\nCalling real extractor:")
    print(command_to_display(command))
    print("=" * 70 + "\n")

    try:
        subprocess.run(
            command,
            cwd=output_root,
            check=True,
            env=credential_free_media_environment(),
        )
    finally:
        # Keep a copy of the latest timecode log too. If this run fails after
        # choosing timecodes, those new timecodes can still be used as no-go
        # ranges on the next attempt.
        if not args.ignore_previous:
            archive_matching_timecode_logs(
                video_id=video_id,
                timecode_folder=timecode_folder,
                history_folder=history_folder,
                label="after_attempt",
            )


if __name__ == "__main__":
    main()
