"""Reproducible Whisper runtime, checkpoint, and decoding identities.

The public model nickname (for example ``small``) is not enough to decide
whether an existing transcript was produced by the same implementation.  This
module builds the complete, JSON-serialisable identity used by both writers and
resume validation.
"""

from __future__ import annotations

import importlib.metadata
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from procurement.external_tools import (
    credential_free_media_environment,
    resolve_media_binary,
)


WHISPER_PROVENANCE_SCHEMA_VERSION = "1.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FFMPEG_VERSION_RE = re.compile(r"^ffmpeg version\s+(\S+)", re.IGNORECASE)

# These are the effective defaults that this project intentionally supplies to
# openai-whisper.  Supplying them explicitly keeps a future library default
# change from silently changing this pipeline's decoding behaviour.
_DECODE_DEFAULTS: dict[str, Any] = {
    "verbose": False,
    "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
    "compression_ratio_threshold": 2.4,
    "logprob_threshold": -1.0,
    "no_speech_threshold": 0.6,
    "condition_on_previous_text": True,
    "initial_prompt": None,
    "carry_initial_prompt": False,
    "word_timestamps": False,
    "clip_timestamps": "0",
    "hallucination_silence_threshold": None,
}


def whisper_decode_options(
    *, device: str, requested_language: str | None, task: str
) -> dict[str, Any]:
    """Return the exact keyword arguments passed to ``model.transcribe``."""

    if task not in {"transcribe", "translate"}:
        raise ValueError(f"Unsupported Whisper decoding task: {task!r}")
    return {
        "language": requested_language,
        "task": task,
        "fp16": device == "cuda",
        **_DECODE_DEFAULTS,
    }


def _json_decoding_identity(options: Mapping[str, Any]) -> dict[str, Any]:
    """Convert decode options to their stable JSON representation."""

    identity = dict(options)
    temperature = identity.get("temperature")
    if isinstance(temperature, tuple):
        identity["temperature"] = list(temperature)
    return identity


def _distribution_version() -> str:
    try:
        version = importlib.metadata.version("openai-whisper")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "Cannot identify the installed openai-whisper package version."
        ) from exc
    if not version:
        raise RuntimeError("The installed openai-whisper version is empty.")
    return version


def _checkpoint_identity(model_name: str) -> dict[str, str]:
    """Read the official expected checkpoint SHA-256 from Whisper's registry.

    ``whisper.load_model`` uses the same registry URL and verifies the downloaded
    checkpoint against the SHA-256 directory component before loading it.  The
    expected digest therefore remains useful even when the local cache lives at
    a different absolute path on another computer.
    """

    import whisper

    registry = getattr(whisper, "_MODELS", None)
    url = registry.get(model_name) if isinstance(registry, Mapping) else None
    if not isinstance(url, str):
        raise ValueError(
            f"Whisper model {model_name!r} is absent from the installed official model registry."
        )
    path_parts = PurePosixPath(urlparse(url).path).parts
    if len(path_parts) < 2:
        raise RuntimeError(f"Unexpected Whisper checkpoint URL for {model_name!r}: {url}")
    expected_sha256 = path_parts[-2].lower()
    filename = path_parts[-1]
    if not _SHA256_RE.fullmatch(expected_sha256) or not filename.endswith(".pt"):
        raise RuntimeError(
            f"Whisper checkpoint URL does not contain a reliable SHA-256 for {model_name!r}."
        )
    return {
        "requested_name": model_name,
        "filename": filename,
        "expected_sha256": expected_sha256,
        "hash_source": "openai_whisper_model_registry",
    }


def _ffmpeg_version() -> str:
    try:
        executable = resolve_media_binary("ffmpeg")
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg is not available; its version cannot be recorded.") from exc
    try:
        completed = subprocess.run(
            [str(executable), "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            shell=False,
            env=credential_free_media_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Cannot query FFmpeg version from {executable}: {exc}") from exc
    first_line = next(
        (line.strip() for line in completed.stdout.splitlines() if line.strip()), ""
    )
    match = _FFMPEG_VERSION_RE.match(first_line)
    if completed.returncode != 0 or match is None:
        raise RuntimeError(
            f"Cannot parse FFmpeg version (exit={completed.returncode}): {first_line or '<empty>'}"
        )
    return match.group(1)


def collect_whisper_execution_identity(model_name: str) -> dict[str, Any]:
    """Collect the environment/checkpoint identity shared by every pass in a run."""

    import torch

    return {
        "engine": {
            "distribution": "openai-whisper",
            "version": _distribution_version(),
        },
        "checkpoint": _checkpoint_identity(model_name),
        "runtime": {
            "torch_version": str(torch.__version__),
            "ffmpeg_version": _ffmpeg_version(),
        },
    }


def build_whisper_provenance(
    execution_identity: Mapping[str, Any],
    *,
    device: str,
    requested_language: str | None,
    pass_tasks: Sequence[str],
) -> dict[str, Any]:
    """Build one output's complete provenance from one or more Whisper passes."""

    if not pass_tasks:
        raise ValueError("Whisper provenance requires at least one decoding pass.")
    return {
        "schema_version": WHISPER_PROVENANCE_SCHEMA_VERSION,
        "engine": dict(execution_identity["engine"]),
        "checkpoint": dict(execution_identity["checkpoint"]),
        "runtime": dict(execution_identity["runtime"]),
        "device": device,
        "decoding_passes": [
            _json_decoding_identity(
                whisper_decode_options(
                    device=device,
                    requested_language=requested_language,
                    task=task,
                )
            )
            for task in pass_tasks
        ],
    }


def build_output_provenance(
    execution_identity: Mapping[str, Any],
    *,
    requested_task: str,
    device: str,
    requested_language: str | None,
) -> dict[str, dict[str, Any]]:
    """Return the expected provenance for every output kind in an invocation."""

    if requested_task != "bilingual":
        return {
            requested_task: build_whisper_provenance(
                execution_identity,
                device=device,
                requested_language=requested_language,
                pass_tasks=(requested_task,),
            )
        }
    return {
        "original": build_whisper_provenance(
            execution_identity,
            device=device,
            requested_language=requested_language,
            pass_tasks=("transcribe",),
        ),
        "eng": build_whisper_provenance(
            execution_identity,
            device=device,
            requested_language=requested_language,
            pass_tasks=("translate",),
        ),
        "bilingual": build_whisper_provenance(
            execution_identity,
            device=device,
            requested_language=requested_language,
            pass_tasks=("transcribe", "translate"),
        ),
    }


def whisper_provenance_is_complete(value: object) -> bool:
    """Return whether a value satisfies the strict current provenance schema."""

    if not isinstance(value, dict):
        return False
    if value.get("schema_version") != WHISPER_PROVENANCE_SCHEMA_VERSION:
        return False
    engine = value.get("engine")
    checkpoint = value.get("checkpoint")
    runtime = value.get("runtime")
    decoding_passes = value.get("decoding_passes")
    if not isinstance(engine, dict) or set(engine) != {"distribution", "version"}:
        return False
    if engine.get("distribution") != "openai-whisper" or not isinstance(
        engine.get("version"), str
    ) or not engine["version"]:
        return False
    if not isinstance(checkpoint, dict) or set(checkpoint) != {
        "requested_name",
        "filename",
        "expected_sha256",
        "hash_source",
    }:
        return False
    if not isinstance(checkpoint.get("requested_name"), str) or not checkpoint[
        "requested_name"
    ]:
        return False
    if not isinstance(checkpoint.get("filename"), str) or not checkpoint[
        "filename"
    ].endswith(".pt"):
        return False
    if not isinstance(checkpoint.get("expected_sha256"), str) or not _SHA256_RE.fullmatch(
        checkpoint["expected_sha256"]
    ):
        return False
    if checkpoint.get("hash_source") != "openai_whisper_model_registry":
        return False
    if not isinstance(runtime, dict) or set(runtime) != {
        "torch_version",
        "ffmpeg_version",
    }:
        return False
    if any(not isinstance(runtime.get(key), str) or not runtime[key] for key in runtime):
        return False
    if value.get("device") not in {"cpu", "cuda"}:
        return False
    if not isinstance(decoding_passes, list) or not decoding_passes:
        return False
    required_decode_keys = {
        "language",
        "task",
        "fp16",
        *_DECODE_DEFAULTS,
    }
    for decoding in decoding_passes:
        if not isinstance(decoding, dict) or set(decoding) != required_decode_keys:
            return False
        if decoding.get("task") not in {"transcribe", "translate"}:
            return False
        if decoding.get("language") is not None and not isinstance(
            decoding.get("language"), str
        ):
            return False
        if not isinstance(decoding.get("fp16"), bool):
            return False
        if decoding.get("fp16") != (value.get("device") == "cuda"):
            return False
        temperature = decoding.get("temperature")
        if not isinstance(temperature, list) or not temperature:
            return False
    return True


def whisper_provenance_matches(saved: object, expected: object) -> bool:
    """Compare only complete current-schema values; incomplete data never matches."""

    return (
        whisper_provenance_is_complete(saved)
        and whisper_provenance_is_complete(expected)
        and saved == expected
    )
