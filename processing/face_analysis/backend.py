"""Backend boundary and the production Py-Feat implementation."""

from __future__ import annotations

import os
from collections.abc import Callable
from importlib.util import find_spec
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Mapping, Protocol

from .config import FaceProcessingConfig
from .media import VideoMetadata
from .model_provenance import (
    model_weights_ready,
    resolve_detector_v2_weights,
    unavailable_model_components,
)
from processing.ffmpeg_runtime import configure_ffmpeg_shared_libraries


class FaceBackend(Protocol):
    name: str
    version: str

    def analyse(self, video: Path, metadata: VideoMetadata, config: FaceProcessingConfig) -> pd.DataFrame:
        """Return one row per detected face."""

    def provenance(self, config: FaceProcessingConfig) -> dict[str, object]:
        """Describe the resolved backend used for reproducibility and reuse."""


class Detector(Protocol):
    """Small seam around Py-Feat's detector, primarily for deterministic tests."""

    info: dict[str, object]

    def detect(self, inputs: str, **kwargs: object) -> object:
        """Analyse one input video."""


DetectorFactory = Callable[[str], Detector]


_DEFAULT_MODEL_COMPONENTS: dict[str, object] = {
    "face_model": "retinaface",
    "multitask_model": "face_multitask_v2",
    "identity_model": "arcface",
    "facepose_model": "multitask",
    "gaze_model": "multitask",
}

_PROVENANCE_PACKAGES = (
    "py-feat",
    "torch",
    "torchvision",
    "torchaudio",
    "torchcodec",
)


class PyFeatBackend:
    """Lazy Py-Feat v2 adapter; importing the package is deferred until use."""

    name = "py-feat-detector-v2"

    def __init__(
        self,
        *,
        detector_factory: DetectorFactory | None = None,
        model_components: Mapping[str, object] | None = None,
    ) -> None:
        self.version = _package_version("py-feat")
        self._detector_factory = detector_factory
        self._model_components = dict(model_components or _DEFAULT_MODEL_COMPONENTS)
        self._weight_provenance = resolve_detector_v2_weights(
            _pyfeat_resource_cache_dir()
        )
        self._detectors: dict[str, Detector] = {}
        self._shared_ffmpeg_directory: str | None = None

    def analyse(self, video: Path, metadata: VideoMetadata, config: FaceProcessingConfig) -> pd.DataFrame:
        import pandas as pd

        shared_ffmpeg = configure_ffmpeg_shared_libraries()
        if shared_ffmpeg is not None:
            self._shared_ffmpeg_directory = str(shared_ffmpeg)
        device = choose_device(config.device)
        detector = self._detectors.get(device)
        if detector is None:
            detector = self._create_detector(device)
            self._detectors[device] = detector
        result = detector.detect(
            str(video),
            data_type="video",
            batch_size=config.batch_size,
            skip_frames=max(1, round(metadata.fps / config.sample_fps)),
            face_detection_threshold=config.face_detection_threshold,
            pin_memory=device == "cuda",
            progress_bar=False,
        )
        return pd.DataFrame(result).copy()

    def provenance(self, config: FaceProcessingConfig) -> dict[str, object]:
        """Return stable model/runtime facts without forcing model construction."""

        device = choose_device(config.device)
        return {
            "name": self.name,
            "version": self.version,
            "resolved_device": device,
            "models": dict(self._model_components),
            "weights": dict(self._weight_provenance),
            "package_versions": {
                package: _package_version(package) for package in _PROVENANCE_PACKAGES
            },
            "shared_ffmpeg_directory": self._shared_ffmpeg_directory,
        }

    def ensure_ready(self, config: FaceProcessingConfig) -> dict[str, object]:
        """Construct the configured Detectorv2 and return its final provenance."""

        device = choose_device(config.device)
        if device not in self._detectors:
            self._detectors[device] = self._create_detector(device)
        return self.provenance(config)

    def _create_detector(self, device: str) -> Detector:
        if self._detector_factory is not None:
            detector = self._detector_factory(device)
        else:
            approved_weights = resolve_detector_v2_weights(
                _pyfeat_resource_cache_dir()
            )
            if not model_weights_ready(approved_weights):
                unavailable = ", ".join(
                    unavailable_model_components(approved_weights)
                )
                raise RuntimeError(
                    "Approved Detectorv2 checkpoints are not ready; run the explicit "
                    f"Face model preparation first. Unavailable: {unavailable}"
                )
            try:
                import feat
                from feat import Detectorv2
                from feat import utils as feat_utils
            except ImportError as exc:
                raise RuntimeError(
                    "Py-Feat is not installed. Run `scripts/setup.ps1` from the "
                    "repository, then use `.venv\\Scripts\\python`."
                ) from exc

            module_version = str(getattr(feat, "__version__", "unknown"))
            if (
                self.version != "unavailable"
                and module_version != "unknown"
                and module_version != self.version
            ):
                raise RuntimeError(
                    "Py-Feat package metadata and imported module versions disagree: "
                    f"{self.version!r} != {module_version!r}"
                )
            components = approved_weights["components"]
            retina_path = str(components["retinaface_r34"]["local_path"])
            arcface_path = str(components["arcface_r50"]["local_path"])
            multitask_path = str(components["face_multitask_v2"]["local_path"])
            original_fallback = feat_utils.hf_hub_download_with_fallback
            previous_arcface = os.environ.get("FEAT_ARCFACE_R50_PATH")

            def approved_fallback(repo_id, filename, fallback_filename, cache_dir):
                if repo_id == "py-feat/retinaface_r34" and filename == "model.safetensors":
                    return retina_path
                return original_fallback(repo_id, filename, fallback_filename, cache_dir)

            feat_utils.hf_hub_download_with_fallback = approved_fallback
            os.environ["FEAT_ARCFACE_R50_PATH"] = arcface_path
            try:
                detector = Detectorv2(
                    device=device,
                    multitask_weights=multitask_path,
                )
            finally:
                feat_utils.hf_hub_download_with_fallback = original_fallback
                if previous_arcface is None:
                    os.environ.pop("FEAT_ARCFACE_R50_PATH", None)
                else:
                    os.environ["FEAT_ARCFACE_R50_PATH"] = previous_arcface
            self._weight_provenance = approved_weights
        self._validate_detector_info(detector)
        # Detectorv2 may have downloaded the default weights while it was being
        # constructed. Re-inspect the local cache so the completed video
        # manifest fingerprints the bytes that were actually available.
        self._weight_provenance = resolve_detector_v2_weights(
            _pyfeat_resource_cache_dir()
        )
        if self._detector_factory is None and not model_weights_ready(
            self._weight_provenance
        ):
            unavailable = ", ".join(
                unavailable_model_components(self._weight_provenance)
            )
            raise RuntimeError(
                "Detectorv2 was constructed but its checkpoint provenance is "
                f"incomplete: {unavailable}"
            )
        return detector

    def _validate_detector_info(self, detector: Detector) -> None:
        detector_info = getattr(detector, "info", None)
        if not isinstance(detector_info, dict):
            return
        mismatches = {
            key: (expected, detector_info.get(key))
            for key, expected in self._model_components.items()
            if key in detector_info and detector_info.get(key) != expected
        }
        if mismatches:
            raise RuntimeError(
                "Loaded Py-Feat detector does not match its declared model provenance: "
                + ", ".join(
                    f"{key} expected {expected!r}, got {actual!r}"
                    for key, (expected, actual) in mismatches.items()
                )
            )


def choose_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unavailable"


def _pyfeat_resource_cache_dir() -> Path | None:
    """Locate Py-Feat's Hugging Face cache without importing Py-Feat/Torch."""

    try:
        spec = find_spec("feat")
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    locations = spec.submodule_search_locations if spec is not None else None
    if not locations:
        return None
    return Path(next(iter(locations))) / "resources"


def pyfeat_resource_cache_dir() -> Path | None:
    """Public internal hook used by explicit approved-weight preparation."""

    return _pyfeat_resource_cache_dir()
