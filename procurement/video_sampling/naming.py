from __future__ import annotations

import re


def compact_path_token(value: str, *, max_chars: int, fallback: str) -> str:
    """Create a compact Windows-safe token without whitespace."""

    cleaned = re.sub(r"\s+", "", str(value or "").strip())
    cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._- ")
    return (cleaned or fallback)[:max_chars]


def make_video_output_folder_name(title: str, video_id: str, *, suffix: str = "") -> str:
    """Use a short title token plus the YouTube ID to keep output paths short."""

    title_token = compact_path_token(title, max_chars=10, fallback="youtubevid")
    video_token = compact_path_token(video_id, max_chars=32, fallback="unknown_id")
    return f"{title_token}_[{video_token}]{suffix}"
