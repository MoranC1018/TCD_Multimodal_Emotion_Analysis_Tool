import pytest

from processing.face_analysis.config import FaceProcessingConfig


def test_face_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="sample_fps"):
        FaceProcessingConfig(sample_fps=0).validate()
    with pytest.raises(ValueError, match="batch_size"):
        FaceProcessingConfig(batch_size=0).validate()
    with pytest.raises(ValueError, match="face_detection_threshold"):
        FaceProcessingConfig(face_detection_threshold=1.1).validate()
