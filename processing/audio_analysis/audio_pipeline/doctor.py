from __future__ import annotations

import io
import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from .config import resolve_ffmpeg_binary, resolve_ffprobe_binary, resolve_opensmile_binary, resolve_opensmile_config


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


DEPENDENCIES = [
    ("torch", "torch"),
    ("transformers", "transformers"),
    ("numpy", "numpy"),
    ("soundfile", "soundfile"),
    ("librosa", "librosa"),
]

OPTIONAL_DEPENDENCIES = [
    ("torchaudio", "torchaudio"),
]


def run_doctor(progress: ProgressCallback = print) -> bool:
    """Print a concise dependency check for the current Python environment."""

    progress(f"Python executable: {sys.executable}")
    progress(f"Python version: {sys.version.split()[0]}")
    progress("")

    checks = collect_diagnostics()
    for check in checks:
        status = "OK" if check.ok else ("MISSING" if check.required else "WARNING")
        progress(f"{status}: {check.name} - {check.detail}")

    ok = required_checks_pass(checks)
    progress("")
    if ok:
        progress("Doctor result: emotion-model dependencies and local tools look available.")
    else:
        progress("Doctor result: one or more required pieces are unavailable in this Python environment.")
    return ok


def required_checks_pass(checks: list[DiagnosticCheck]) -> bool:
    return all(check.ok for check in checks if check.required)


def collect_diagnostics() -> list[DiagnosticCheck]:
    checks = [dependency_check(distribution, module) for distribution, module in DEPENDENCIES]
    checks.extend(optional_dependency_check(distribution, module) for distribution, module in OPTIONAL_DEPENDENCIES)
    checks.append(audio_io_check())
    checks.append(torchaudio_runtime_check())
    checks.append(torch_device_check())
    checks.append(local_tool_check("ffmpeg", resolve_ffmpeg_binary))
    checks.append(local_tool_check("ffprobe", resolve_ffprobe_binary))
    checks.append(local_tool_check("OpenSMILE binary", resolve_opensmile_binary))
    checks.append(local_tool_check("OpenSMILE eGeMAPS config", resolve_opensmile_config))
    return checks


def dependency_check(distribution: str, module_name: str) -> DiagnosticCheck:
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        return DiagnosticCheck(distribution, False, compact_error(exc))

    try:
        package_version = version(distribution)
    except PackageNotFoundError:
        package_version = "installed"
    return DiagnosticCheck(distribution, True, package_version)


def optional_dependency_check(distribution: str, module_name: str) -> DiagnosticCheck:
    """Report a third-party compatibility layer without making it a launch blocker."""

    check = dependency_check(distribution, module_name)
    return DiagnosticCheck(check.name, check.ok, check.detail, required=False)


def audio_io_check() -> DiagnosticCheck:
    """Exercise the SoundFile path used by the production emotion models."""

    try:
        import numpy as np
        import soundfile as sf

        buffer = io.BytesIO()
        sf.write(buffer, np.zeros(1600, dtype="float32"), 16000, format="WAV", subtype="PCM_16")
        buffer.seek(0)
        samples, sample_rate = sf.read(buffer, dtype="float32")
        if sample_rate != 16000 or len(samples) != 1600:
            raise RuntimeError(f"unexpected round-trip result: {len(samples)} samples at {sample_rate} Hz")
    except Exception as exc:
        return DiagnosticCheck("production audio I/O", False, compact_error(exc))
    return DiagnosticCheck("production audio I/O", True, "SoundFile WAV round trip")


def torchaudio_runtime_check() -> DiagnosticCheck:
    """Probe optional TorchAudio codec APIs that external model packages may call."""

    try:
        import torch
        import torchaudio

        torch_version = str(torch.__version__).split("+", 1)[0]
        torchaudio_version = str(torchaudio.__version__).split("+", 1)[0]
        torch_family = ".".join(torch_version.split(".")[:2])
        torchaudio_family = ".".join(torchaudio_version.split(".")[:2])
        if torch_family != torchaudio_family:
            raise RuntimeError(
                f"version mismatch: torch {torch_version}, torchaudio {torchaudio_version}; "
                "install matching major/minor releases"
            )

        buffer = io.BytesIO()
        torchaudio.save(buffer, torch.zeros((1, 1600), dtype=torch.float32), 16000, format="wav")
        buffer.seek(0)
        samples, sample_rate = torchaudio.load(buffer, format="wav")
        if sample_rate != 16000 or samples.shape[-1] != 1600:
            raise RuntimeError(f"unexpected round-trip result: {tuple(samples.shape)} at {sample_rate} Hz")
    except Exception as exc:
        return DiagnosticCheck("optional TorchAudio codec runtime", False, compact_error(exc), required=False)
    return DiagnosticCheck("optional TorchAudio codec runtime", True, "WAV round trip", required=False)


def torch_device_check() -> DiagnosticCheck:
    try:
        import torch
    except Exception as exc:
        return DiagnosticCheck("torch device", False, compact_error(exc))

    cuda_available = bool(torch.cuda.is_available())
    device = "cuda available" if cuda_available else "cpu only"
    return DiagnosticCheck("torch device", True, device)


def local_tool_check(name: str, resolver) -> DiagnosticCheck:
    try:
        path = resolver()
    except Exception as exc:
        return DiagnosticCheck(name, False, compact_error(exc))
    return DiagnosticCheck(name, True, str(path))


def compact_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return text if len(text) <= 300 else f"{text[:300]}..."
