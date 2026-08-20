"""Configuration objects for facial processing."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FaceProcessingConfig:
    """Validated, serialisable settings for one facial-processing run."""

    sample_fps: float = 5.0
    batch_size: int = 8
    face_detection_threshold: float = 0.90
    device: str = "auto"
    recursive: bool = True
    overwrite: bool = False

    def validate(self) -> "FaceProcessingConfig":
        if not 0 < self.sample_fps <= 120:
            raise ValueError("sample_fps must be greater than 0 and no more than 120")
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if not 0 < self.face_detection_threshold <= 1:
            raise ValueError("face_detection_threshold must be in (0, 1]")
        if self.device not in {"auto", "cpu", "cuda", "mps"}:
            raise ValueError("device must be one of: auto, cpu, cuda, mps")
        return self

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
