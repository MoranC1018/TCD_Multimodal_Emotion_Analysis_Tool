#!/usr/bin/env python3
"""Download a complete YouTube video only when the metadata says it is CC licensed.

This script is intentionally separate from the DOCX wrapper and the 10 percent
sampling pipeline. It is for the narrower case where a full-video download is
allowed because the video metadata exposes a Creative Commons style license.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
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


DEFAULT_MAX_HEIGHT = 720
DEFAULT_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_FORMAT_SELECTOR_TEMPLATE = (
    "b[height<={max_height}][ext=mp4]/"
    "bv*[height<={max_height}][ext=mp4][vcodec^=avc1]+ba[ext=m4a]/"
    "bv*[height<={max_height}][vcodec^=avc1]+ba[acodec^=mp4a]/"
    "best[height<={max_height}]/best"
)
YT_DLP_COOKIES_BROWSER_ENV = "YT_DLP_COOKIES_FROM_BROWSER"
YT_DLP_COOKIES_FILE_ENV = "YT_DLP_COOKIES_FILE"


def make_filename_safe(text: str, max_length: int = 120) -> str:
    """Create a Windows-friendly path segment from a title or speaker name."""
    cleaned = str(text or "").strip().replace(" ", "_")
    cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._ ")
    return (cleaned or "youtube_video")[:max_length]


def get_youtube_video_id(url: str) -> str:
    """Extract the YouTube video ID from common URL shapes."""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.").removeprefix("music.")
    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0] or "unknown_id"
    if host in {"youtube.com", "youtube-nocookie.com"}:
        query_values = parse_qs(parsed.query)
        if query_values.get("v"):
            return query_values["v"][0]
        path_parts = [part for part in parsed.path.split("/") if part]
        for marker in ("shorts", "embed", "live", "v"):
            if marker in path_parts:
                marker_index = path_parts.index(marker)
                if marker_index + 1 < len(path_parts):
                    return path_parts[marker_index + 1]
    return "unknown_id"


def command_to_text(command: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def read_video_info(url: str, timeout_seconds: int) -> dict[str, object]:
    """Read YouTube metadata without downloading the video."""
    canonical_url = normalise_youtube_url(url)
    if canonical_url is None:
        raise ValueError("A valid YouTube URL with an exact 11-character video ID is required.")
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
    result = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        env=credential_free_media_environment(),
    )
    return json.loads(result.stdout)


def looks_like_creative_commons(license_text: object) -> bool:
    """Return True for common yt-dlp Creative Commons license strings."""
    text = str(license_text or "").strip().lower()
    if not text:
        return False
    patterns = [
        r"creative\s+commons",
        r"\bcc[- ]?by\b",
        r"attribution.*reuse",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def build_download_command(url: str, output_folder: Path, format_selector: str) -> list[str]:
    """Build the full-video yt-dlp command."""
    canonical_url = normalise_youtube_url(url)
    if canonical_url is None:
        raise ValueError("A valid YouTube URL with an exact 11-character video ID is required.")
    output_template = output_folder / "%(title).120s_[%(id)s].%(ext)s"
    command = build_yt_dlp_command(
        [
        "--no-playlist",
        "--newline",
        "--max-filesize",
        str(DEFAULT_MAX_DOWNLOAD_BYTES),
        "--format",
        format_selector,
        "--merge-output-format",
        "mp4",
        "--output",
        str(output_template),
        ],
        ffmpeg_binary=resolve_media_binary(
            "ffmpeg",
            excluded_roots=(output_folder,),
        ),
    )
    command.extend(yt_dlp_auth_args())
    command.append(canonical_url)
    return command


def yt_dlp_auth_args() -> list[str]:
    """Return optional local browser/cookie-file auth args for yt-dlp."""

    args: list[str] = []
    browser = os.getenv(YT_DLP_COOKIES_BROWSER_ENV, "").strip()
    if browser:
        args.extend(["--cookies-from-browser", browser])

    cookies_file = os.getenv(YT_DLP_COOKIES_FILE_ENV, "").strip().strip('"').strip("'")
    if cookies_file:
        args.extend(["--cookies", cookies_file])

    return args


def write_log(log_path: Path, lines: list[str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a full YouTube video only when it is Creative Commons licensed.")
    parser.add_argument("url", help="YouTube video URL.")
    parser.add_argument("--output-root", type=Path, default=Path.cwd(), help="Folder where the full-video folder is created.")
    parser.add_argument("--max-height", type=int, default=DEFAULT_MAX_HEIGHT, help=f"Preferred maximum height. Default: {DEFAULT_MAX_HEIGHT}.")
    parser.add_argument("--format", dest="format_selector", default=None, help="Optional yt-dlp format selector.")
    parser.add_argument("--info-timeout", type=int, default=180, help="Maximum seconds for reading metadata.")
    parser.add_argument("--command-timeout", type=int, default=3600, help="Maximum seconds for the download command.")
    parser.add_argument("--allow-non-cc", action="store_true", help="Override the CC license check after manual review.")
    parser.add_argument("--dry-run", action="store_true", help="Check license metadata and print the command without downloading.")
    return parser.parse_args()


def main() -> None:
    configure_utf8_stdio()
    args = parse_args()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    log_lines = [
        f"Run started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"URL: {args.url}",
        f"Output root: {output_root}",
    ]

    info = read_video_info(args.url, args.info_timeout)
    title = str(info.get("title") or "youtube_video")
    video_id = str(info.get("id") or get_youtube_video_id(args.url))
    license_text = str(info.get("license") or "")
    is_cc = looks_like_creative_commons(license_text)

    output_folder = output_root / make_video_output_folder_name(title, video_id, suffix="_full_video")
    output_folder.mkdir(parents=True, exist_ok=True)
    log_path = output_folder / "full_video_download.log"

    log_lines.extend(
        [
            f"Title: {title}",
            f"Video ID: {video_id}",
            f"License: {license_text or '(missing)'}",
            f"Creative Commons detected: {is_cc}",
        ]
    )

    if not is_cc and not args.allow_non_cc:
        log_lines.append("Stopped: license metadata did not look Creative Commons.")
        write_log(log_path, log_lines)
        raise PermissionError(
            "The video metadata did not look Creative Commons licensed. "
            "Use --allow-non-cc only after manual license review."
        )

    format_selector = args.format_selector or DEFAULT_FORMAT_SELECTOR_TEMPLATE.format(max_height=args.max_height)
    command = build_download_command(args.url, output_folder, format_selector)
    log_lines.append(f"Command: {command_to_text(command)}")

    if args.dry_run:
        log_lines.append("Dry run complete. No video downloaded.")
        write_log(log_path, log_lines)
        print("\n".join(log_lines))
        return

    subprocess.run(
        command,
        check=True,
        cwd=output_folder,
        timeout=args.command_timeout,
        env=credential_free_media_environment(),
    )
    completed_files = [path for path in output_folder.iterdir() if path.is_file() and path != log_path]
    if not completed_files:
        raise FileNotFoundError("yt-dlp did not create a completed full-video file.")
    if any(path.stat().st_size > DEFAULT_MAX_DOWNLOAD_BYTES for path in completed_files):
        raise ValueError(
            f"Downloaded video exceeds the {DEFAULT_MAX_DOWNLOAD_BYTES} byte limit."
        )
    log_lines.append("Download complete.")
    write_log(log_path, log_lines)
    print(f"Full video downloaded to: {output_folder}")
    print(f"Log saved as: {log_path}")


if __name__ == "__main__":
    main()
