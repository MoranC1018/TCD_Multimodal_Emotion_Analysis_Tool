"""Immutable model provenance used by clean-speaker procurement."""

from __future__ import annotations


OPENCV_ZOO_REVISION = "47534e27c9851bb1128ccc0102f1145e27f23f98"
PYANNOTE_MODEL = "pyannote/speaker-diarization-3.1"
PYANNOTE_MODEL_REVISION = "84fd25912480287da0247647c3d2b4853cb3ee5d"
SPEECHBRAIN_ECAPA_MODEL = "speechbrain/spkrec-ecapa-voxceleb"
SPEECHBRAIN_ECAPA_REVISION = "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"

OPENCV_ZOO_MODELS = {
    "yunet": {
        "filename": "face_detection_yunet_2023mar.onnx",
        "url": (
            "https://raw.githubusercontent.com/opencv/opencv_zoo/"
            f"{OPENCV_ZOO_REVISION}/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
        ),
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    },
    "sface": {
        "filename": "face_recognition_sface_2021dec.onnx",
        "url": (
            "https://raw.githubusercontent.com/opencv/opencv_zoo/"
            f"{OPENCV_ZOO_REVISION}/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
        ),
        "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    },
}

MODEL_REVISIONS = {
    "opencv_zoo": OPENCV_ZOO_REVISION,
    PYANNOTE_MODEL: PYANNOTE_MODEL_REVISION,
    SPEECHBRAIN_ECAPA_MODEL: SPEECHBRAIN_ECAPA_REVISION,
}

MODEL_SHA256 = {
    str(metadata["filename"]): str(metadata["sha256"])
    for metadata in OPENCV_ZOO_MODELS.values()
}
