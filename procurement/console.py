from __future__ import annotations

import sys


def configure_utf8_stdio() -> None:
    """Make CLI output tolerant of speaker names and titles with accents."""

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            continue
