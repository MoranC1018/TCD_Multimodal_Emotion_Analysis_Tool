"""Shared identity and inventory contracts for Text processing stages."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path


TEXT_SCHEMA_VERSION = "2.0"
TEXT_MEDIA_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".m4v",
        ".ts",
        ".mts",
        ".m2ts",
        ".mp3",
        ".wav",
        ".flac",
        ".aac",
        ".ogg",
        ".m4a",
    }
)
CANONICAL_VIDEO_RE = re.compile(
    r"^(?P<order>\d{3})_(?P<country>[^_]+)_(?P<speaker>.+)_(?P<date>\d{4,8}(?:unknown)?)$"
)


def identity_key(value: object) -> str:
    """Return the accent-, punctuation-, and case-insensitive identity key."""

    ascii_value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


def canonical_video_relative(stem: str) -> Path:
    """Derive ``Country/Speaker/Video`` from a canonical video stem."""

    match = CANONICAL_VIDEO_RE.fullmatch(stem)
    if match is None:
        raise ValueError(
            f"Invalid video name {stem!r}. Expected NNN_Country_Speaker_YYYYMMDD "
            "(partial 4-8 digit dates with an optional 'unknown' suffix remain supported)."
        )
    return Path(match.group("country")) / match.group("speaker").replace("_", " ") / stem


def validate_canonical_relative(path: Path) -> Path:
    """Validate and normalise a canonical ``Country/Speaker/Video`` identity."""

    candidate = Path(path)
    if candidate.suffix:
        candidate = candidate.with_suffix("")
    if len(candidate.parts) != 3:
        raise ValueError(f"Expected Country/Speaker/Video identity, got: {path}")
    derived = canonical_video_relative(candidate.name)
    if identity_key(candidate.parts[0]) != identity_key(derived.parts[0]):
        raise ValueError(
            f"Country folder does not match video name: {candidate.parts[0]!r} vs {derived.parts[0]!r}"
        )
    if identity_key(candidate.parts[1]) != identity_key(derived.parts[1]):
        raise ValueError(
            f"Speaker folder does not match video name: {candidate.parts[1]!r} vs {derived.parts[1]!r}"
        )
    return Path(candidate.parts[0]) / candidate.parts[1] / candidate.name


def validate_text_identity(path: Path) -> Path:
    """Validate a Text video identity without requiring a comparison group.

    Current procurement outputs are organised as ``Speaker/Video`` and do
    not contain a country.  Historical project inputs use the stricter
    ``Country/Speaker/Video`` convention.  Both layouts are valid processing
    identities; country/group metadata is assigned later by postprocessing.
    """

    candidate = Path(path)
    if candidate.is_absolute():
        raise ValueError(f"Text video identity must be relative, got: {path}")
    if candidate.suffix:
        candidate = candidate.with_suffix("")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError(f"Text video identity contains an unsafe path component: {path}")
    if len(candidate.parts) == 2:
        return Path(candidate.parts[0]) / candidate.parts[1]
    if len(candidate.parts) == 3:
        return validate_canonical_relative(candidate)
    raise ValueError(
        f"Expected Speaker/Video or Country/Speaker/Video identity, got: {path}"
    )


def text_identity_parts(path: Path) -> tuple[str, str, str]:
    """Return ``(country, speaker, video)`` for either supported layout."""

    identity = validate_text_identity(path)
    if len(identity.parts) == 2:
        return "", identity.parts[0], identity.parts[1]
    return identity.parts[0], identity.parts[1], identity.parts[2]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_fingerprint(path: Path) -> dict[str, int]:
    stat = Path(path).stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def inventory_digest(items: Sequence[Mapping[str, object]]) -> str:
    """Hash a JSON-compatible inventory independently of formatting."""

    canonical = json.dumps(list(items), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def relative_posix(path: Path, root: Path) -> str:
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
