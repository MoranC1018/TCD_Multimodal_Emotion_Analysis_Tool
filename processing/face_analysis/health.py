"""Actionable environment readiness checks for native face processing."""

from __future__ import annotations

import gc
import os
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

from .backend import PyFeatBackend, pyfeat_resource_cache_dir
from .config import FaceProcessingConfig
from .model_provenance import (
    model_weights_ready,
    prepare_approved_detector_v2_weights,
    unavailable_model_components,
)
from processing.ffmpeg_runtime import (
    SUPPORTED_FFMPEG_MAJOR,
    configure_ffmpeg_shared_libraries,
)
from procurement.external_tools import (
    credential_free_media_environment,
    resolve_media_binary,
)


@dataclass(frozen=True)
class Readiness:
    ready: bool
    ffprobe: bool
    pyfeat: bool
    torch: bool
    device: str
    detail: str
    pyarrow: bool = False
    torchcodec: bool = False
    ffmpeg_major: int | None = None
    detector: bool = False
    model_weights: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ModelPreparation:
    """Result of the explicit, network-enabled Detectorv2 preparation step."""

    ready: bool
    device: str
    detail: str
    model_weights: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": "prepare-models",
            "status": "ready" if self.ready else "failed",
            **asdict(self),
        }


class DetectorReadinessError(RuntimeError):
    """Detector construction failure with the inspected model evidence."""

    def __init__(self, message: str, model_weights: object) -> None:
        super().__init__(message)
        self.model_weights = (
            dict(model_weights) if isinstance(model_weights, dict) else {}
        )


def prepare_detector_models(requested_device: str = "auto") -> ModelPreparation:
    """Intentionally download/load Detectorv2 and verify all checkpoint bytes.

    This is the only readiness operation that permits Py-Feat/Hugging Face to
    contact the network.  Keeping it separate from :func:`check_readiness`
    makes downloads an explicit install action rather than a side effect of a
    routine health check.
    """

    engine: PyFeatBackend | None = None
    device = requested_device
    weights: dict[str, object] = {}
    try:
        shared_ffmpeg = configure_ffmpeg_shared_libraries()
        if os.name == "nt" and shared_ffmpeg is None:
            raise RuntimeError(
                "complete FFmpeg 8 full-shared DLLs were not found; run "
                "scripts/setup.ps1 before preparing Face models"
            )
        cache_dir = pyfeat_resource_cache_dir()
        if cache_dir is None:
            raise RuntimeError("Py-Feat is not installed; run scripts/setup.ps1 first")
        weights = prepare_approved_detector_v2_weights(cache_dir)
        if not model_weights_ready(weights):
            unavailable = ", ".join(unavailable_model_components(weights))
            raise DetectorReadinessError(
                f"Approved Detectorv2 checkpoints are incomplete: {unavailable}",
                weights,
            )
        engine = PyFeatBackend()
        config = FaceProcessingConfig(device=requested_device)
        initial = engine.provenance(config)
        device = str(initial.get("resolved_device") or requested_device)

        # Unlike _pyfeat_detector_smoke, this construction is deliberately not
        # wrapped in Hugging Face offline mode. Detectorv2 may populate its
        # cache here when any of the three required checkpoints is absent.
        provenance = engine.ensure_ready(config)
        candidate = provenance.get("weights")
        if isinstance(candidate, dict):
            weights = dict(candidate)
        if not model_weights_ready(weights):
            unavailable = ", ".join(unavailable_model_components(weights))
            raise DetectorReadinessError(
                "Detectorv2 construction completed but checkpoint provenance "
                f"is incomplete: {unavailable}",
                weights,
            )
        return ModelPreparation(
            ready=True,
            device=device,
            detail=(
                "Py-Feat Detectorv2 was constructed and all three checkpoint "
                "files passed provenance validation"
                + (f"; shared FFmpeg: {shared_ffmpeg}" if shared_ffmpeg else "")
            ),
            model_weights=weights,
        )
    except Exception as exc:
        if isinstance(exc, DetectorReadinessError):
            weights = exc.model_weights
        elif engine is not None:
            # Detector construction can fail after one or more files have
            # arrived. Return the newest local evidence without retrying the
            # network operation so setup failures remain diagnosable.
            try:
                current = engine.provenance(
                    FaceProcessingConfig(device=requested_device)
                ).get("weights")
                if isinstance(current, dict):
                    weights = dict(current)
            except Exception:
                pass
        return ModelPreparation(
            ready=False,
            device=device,
            detail=f"Detectorv2 model preparation failed: {type(exc).__name__}: {exc}",
            model_weights=weights,
        )
    finally:
        if engine is not None:
            del engine
        gc.collect()
        _release_cuda_cache()


def check_readiness(requested_device: str = "auto") -> Readiness:
    shared_ffmpeg = configure_ffmpeg_shared_libraries()
    try:
        resolve_media_binary("ffprobe")
        ffprobe = True
    except (FileNotFoundError, OSError, ValueError):
        ffprobe = False
    details: list[str] = []

    try:
        pyarrow_version = _pyarrow_version()
        pyarrow_ready = True
        details.append(f"PyArrow {pyarrow_version} is importable")
    except Exception as exc:
        pyarrow_ready = False
        details.append(f"PyArrow import failed: {type(exc).__name__}: {exc}")

    try:
        device = _torch_device(requested_device)
        torch_ready = True
        details.append(f"PyTorch is importable ({device})")
    except Exception as exc:
        return Readiness(
            ready=False,
            ffprobe=ffprobe,
            pyfeat=False,
            torch=False,
            device="unavailable",
            detail="; ".join(
                [*details, f"PyTorch import failed: {type(exc).__name__}: {exc}"]
            ),
            pyarrow=pyarrow_ready,
        )

    ffmpeg_major: int | None = None
    try:
        ffmpeg_major = _torchcodec_decode_smoke()
        torchcodec_ready = ffmpeg_major == SUPPORTED_FFMPEG_MAJOR
        if not torchcodec_ready:
            raise RuntimeError(
                f"TorchCodec loaded FFmpeg {ffmpeg_major}; expected {SUPPORTED_FFMPEG_MAJOR}"
            )
        details.append(f"TorchCodec decoded a local smoke frame with FFmpeg {ffmpeg_major}")
    except Exception as exc:
        torchcodec_ready = False
        details.append(f"TorchCodec smoke failed: {type(exc).__name__}: {exc}")

    model_weights: dict[str, object] = {}
    detector_ready = False
    try:
        pyfeat_version = _pyfeat_version()
        pyfeat = True
        details.append(f"Py-Feat {pyfeat_version} is importable")
        model_weights = _pyfeat_detector_smoke(device)
        detector_ready = True
        details.append(
            "Py-Feat Detectorv2 constructed from three locally verified checkpoints"
        )
    except Exception as exc:
        # Import success and model construction are deliberately separate:
        # installed Python code without loadable model bytes is not ready.
        pyfeat = "pyfeat_version" in locals()
        if isinstance(exc, DetectorReadinessError):
            model_weights = exc.model_weights
        details.append(
            f"Py-Feat Detectorv2 readiness failed: {type(exc).__name__}: {exc}"
        )

    shared_runtime_ready = os.name != "nt" or shared_ffmpeg is not None
    if shared_ffmpeg is not None:
        details.append(f"shared FFmpeg: {shared_ffmpeg}")
    elif not shared_runtime_ready:
        details.append(
            "complete FFmpeg 8 full-shared DLLs were not found (run scripts/setup.ps1)"
        )
    if not ffprobe:
        details.append("ffprobe was not found on PATH")

    return Readiness(
        ready=(
            ffprobe
            and torch_ready
            and pyarrow_ready
            and torchcodec_ready
            and pyfeat
            and detector_ready
            and shared_runtime_ready
        ),
        ffprobe=ffprobe,
        pyfeat=pyfeat,
        torch=torch_ready,
        device=device,
        detail="; ".join(details),
        pyarrow=pyarrow_ready,
        torchcodec=torchcodec_ready,
        ffmpeg_major=ffmpeg_major,
        detector=detector_ready,
        model_weights=model_weights,
    )


def _torch_device(requested_device: str = "auto") -> str:
    import torch

    requested = str(requested_device or "").casefold()
    if requested not in {"auto", "cpu", "cuda", "mps"}:
        raise ValueError("Face device must be one of: auto, cpu, cuda, mps")
    cuda_available = torch.cuda.is_available()
    mps = getattr(torch.backends, "mps", None)
    mps_available = bool(mps is not None and mps.is_available())
    if requested == "auto":
        return "cuda" if cuda_available else "mps" if mps_available else "cpu"
    if requested == "cuda" and not cuda_available:
        raise RuntimeError("CUDA was requested but the installed PyTorch runtime cannot use CUDA")
    if requested == "mps" and not mps_available:
        raise RuntimeError("MPS was requested but the installed PyTorch runtime cannot use MPS")
    return requested


def _pyfeat_version() -> str:
    import feat

    return str(getattr(feat, "__version__", "unknown"))


def _pyarrow_version() -> str:
    import pyarrow

    return str(getattr(pyarrow, "__version__", "unknown"))


def _pyfeat_detector_smoke(device: str) -> dict[str, object]:
    """Construct Detectorv2 using local cache only and return weight evidence."""

    engine = PyFeatBackend()
    config = FaceProcessingConfig(device=device)
    try:
        weights = engine.provenance(config).get("weights")
        if not model_weights_ready(weights):
            unavailable = ", ".join(unavailable_model_components(weights))
            raise DetectorReadinessError(
                "required Detectorv2 weights are not locally ready: "
                f"{unavailable}. Run Face once while online to populate the "
                "Py-Feat cache.",
                weights,
            )
        # Readiness must never make a surprise network request.  With all three
        # files proven above, offline construction verifies that Py-Feat can
        # deserialize the actual cached bytes and assemble the complete model.
        with _huggingface_cache_only():
            provenance = engine.ensure_ready(config)
        final_weights = provenance.get("weights")
        if not model_weights_ready(final_weights):
            unavailable = ", ".join(unavailable_model_components(final_weights))
            raise DetectorReadinessError(
                f"Detectorv2 loaded but weight verification failed: {unavailable}",
                final_weights,
            )
        return dict(final_weights)
    finally:
        del engine
        gc.collect()
        _release_cuda_cache()


@contextmanager
def _huggingface_cache_only() -> Iterator[None]:
    """Temporarily force Hugging Face Hub calls into local-cache-only mode."""

    variable = "HF_HUB_OFFLINE"
    previous_environment = os.environ.get(variable)
    os.environ[variable] = "1"
    constants = None
    previous_constant = None
    try:
        try:
            import huggingface_hub.constants as constants_module

            constants = constants_module
            previous_constant = constants.HF_HUB_OFFLINE
            constants.HF_HUB_OFFLINE = True
        except (ImportError, AttributeError):
            constants = None
        yield
    finally:
        if constants is not None:
            constants.HF_HUB_OFFLINE = previous_constant
        if previous_environment is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous_environment


def _release_cuda_cache() -> None:
    """Release memory allocated by the readiness-only model when possible."""

    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except (ImportError, RuntimeError):
        pass


def _torchcodec_decode_smoke() -> int:
    """Generate and decode one 16x16 local frame; never contacts the network."""

    with tempfile.TemporaryDirectory(prefix="multimodal_emotion_analysis_ffmpeg_smoke_") as temporary:
        video = Path(temporary) / "smoke.mp4"
        ffmpeg = resolve_media_binary("ffmpeg", excluded_roots=(Path(temporary),))
        completed = subprocess.run(
            [
                str(ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=16x16:r=1",
                "-frames:v",
                "1",
                "-c:v",
                "mpeg4",
                "-pix_fmt",
                "yuv420p",
                "-y",
                str(video),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            shell=False,
            env=credential_free_media_environment(),
        )
        if completed.returncode != 0 or not video.is_file():
            detail = (completed.stderr or completed.stdout or "unknown ffmpeg error").strip()
            raise RuntimeError(f"could not create local smoke video: {detail}")

        from torchcodec import _core
        from torchcodec.decoders import VideoDecoder

        major = int(_core.ffmpeg_major_version)
        if major != SUPPORTED_FFMPEG_MAJOR:
            raise RuntimeError(
                f"TorchCodec selected FFmpeg {major}; expected {SUPPORTED_FFMPEG_MAJOR}"
            )
        # Querying versions exercises the loaded FFmpeg symbols; indexing the
        # decoder proves a real encoded frame can cross the native boundary.
        versions = _core.get_ffmpeg_library_versions()
        if not versions:
            raise RuntimeError("TorchCodec returned no FFmpeg library versions")
        decoder = VideoDecoder(str(video), device="cpu", num_ffmpeg_threads=1)
        if len(decoder) < 1:
            raise RuntimeError("TorchCodec found no frames in the local smoke video")
        frame = decoder[0]
        if getattr(frame, "numel", lambda: 0)() <= 0:
            raise RuntimeError("TorchCodec returned an empty smoke frame")
        # VideoDecoder holds a native Windows file handle.  A return from
        # inside TemporaryDirectory would attempt cleanup while that local is
        # still alive and falsely turn a successful decode into WinError 32.
        del frame
        del decoder
        gc.collect()
        return major
