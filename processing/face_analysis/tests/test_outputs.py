from __future__ import annotations

import importlib.util
import pandas as pd
import pytest

from processing.face_analysis.media import VideoMetadata
from processing.face_analysis.outputs import (
    AU_NAMES,
    EMOTION_NAMES,
    artifact_metadata,
    build_output_tables,
    write_video_outputs,
)
from processing.face_analysis.tests.helpers import complete_detection_row


PYARROW_AVAILABLE = importlib.util.find_spec("pyarrow") is not None


def test_core_output_keeps_multiple_faces_and_explicit_missing_frames() -> None:
    detections = pd.DataFrame(
        [
            complete_detection_row(frame=0, FaceScore=0.8, AU01=0.1, Happy=0.2),
            complete_detection_row(frame=0, FaceScore=0.9, AU01=0.3, Happy=0.4),
            complete_detection_row(frame=4, FaceScore=0.95, AU01=0.5, Happy=0.6),
        ]
    )
    metadata = VideoMetadata("video.mp4", "abc", 1, 3.0, 4.0, 12, 640, 360)
    raw, core, quality = build_output_tables(detections, metadata, sample_fps=1.0, media_id="video__abc")

    assert len(raw) == 3
    assert list(core["frame_index"]) == [0, 0, 4, 8]
    assert str(core["frame_index"].dtype) == "int64"
    assert str(core["face_index"].dtype) == "Int64"
    assert list(core["face_detected"]) == [True, True, True, False]
    assert list(core.loc[core["frame_index"] == 0, "face_count"]) == [2, 2]
    assert core.loc[core["frame_index"] == 0, "is_primary_face"].tolist() == [False, True]
    assert pd.isna(core.loc[core["frame_index"] == 8, "AU01"]).all()
    assert quality == {
        "sampled_frames": 3,
        "frames_with_face": 2,
        "frames_without_face": 1,
        "face_coverage": 2 / 3,
        "detected_face_rows": 3,
        "rejected_placeholder_or_low_score_rows": 0,
        "multiple_face_frames": 1,
        "frame_step": 4,
        "effective_sample_fps": 1.0,
    }


def test_detector_placeholder_rows_become_explicit_no_face_rows() -> None:
    detections = pd.DataFrame(
        [
            complete_detection_row(frame=0, FaceScore=0.0, AU01=0.7, Happy=0.1),
            complete_detection_row(frame=5, FaceScore=float("nan"), AU01=0.8, Happy=0.2),
        ]
    )
    metadata = VideoMetadata("blank.mp4", "def", 1, 1.0, 10.0, 10, 320, 240)

    raw, core, quality = build_output_tables(
        detections,
        metadata,
        sample_fps=2.0,
        media_id="blank__def",
        minimum_face_score=0.9,
    )

    assert raw.empty
    assert list(core["frame_index"]) == [0, 5]
    assert core["face_detected"].tolist() == [False, False]
    assert core["AU01"].isna().all()
    assert quality["frames_with_face"] == 0
    assert quality["frames_without_face"] == 2
    assert quality["rejected_placeholder_or_low_score_rows"] == 2


def test_output_contract_requires_face_score() -> None:
    row = complete_detection_row()
    del row["FaceScore"]
    detections = pd.DataFrame([row])
    metadata = VideoMetadata("video.mp4", "abc", 1, 1.0, 10.0, 10, 320, 240)

    with pytest.raises(RuntimeError, match="FaceScore"):
        build_output_tables(
            detections,
            metadata,
            sample_fps=2.0,
            media_id="video__abc",
            minimum_face_score=0.9,
        )


def test_output_contract_rejects_non_numeric_face_scores() -> None:
    detections = pd.DataFrame(
        [complete_detection_row(FaceScore="not-a-score")]
    )
    metadata = VideoMetadata("video.mp4", "abc", 1, 1.0, 10.0, 10, 320, 240)

    with pytest.raises(RuntimeError, match="FaceScore values must be numeric"):
        build_output_tables(
            detections,
            metadata,
            sample_fps=2.0,
            media_id="video__abc",
            minimum_face_score=0.9,
        )


def test_output_contract_rejects_frames_off_the_sampling_grid() -> None:
    detections = pd.DataFrame(
        [complete_detection_row(frame=3)]
    )
    metadata = VideoMetadata("video.mp4", "abc", 1, 1.0, 10.0, 10, 320, 240)

    with pytest.raises(RuntimeError, match="sampling grid"):
        build_output_tables(
            detections,
            metadata,
            sample_fps=2.0,
            media_id="video__abc",
            minimum_face_score=0.9,
        )


@pytest.mark.parametrize("missing", ["Anger", "AU43", "valence", "FaceRectWidth"])
def test_output_contract_requires_complete_pyfeat_2_1_1_core_schema(
    missing: str,
) -> None:
    row = complete_detection_row()
    del row[missing]
    detections = pd.DataFrame([row])
    metadata = VideoMetadata("video.mp4", "abc", 1, 1.0, 10.0, 10, 320, 240)

    with pytest.raises(RuntimeError, match=rf"Py-Feat 2\.1\.1 core columns.*{missing}"):
        build_output_tables(
            detections,
            metadata,
            sample_fps=2.0,
            media_id="video__abc",
            minimum_face_score=0.9,
        )


@pytest.mark.skipif(not PYARROW_AVAILABLE, reason="PyArrow is an optional Face runtime dependency")
def test_artifact_checks_stream_instead_of_materialising_full_tables(
    monkeypatch,
    tmp_path,
) -> None:
    detections = pd.DataFrame(
        [complete_detection_row()]
    )
    metadata = VideoMetadata("video.mp4", "abc", 1, 1.0, 10.0, 10, 320, 240)
    raw, core, _quality = build_output_tables(
        detections,
        metadata,
        sample_fps=2.0,
        media_id="video__abc",
        minimum_face_score=0.9,
    )
    output = tmp_path / "video__abc"
    write_video_outputs(output, raw, core, {"status": "completed"})

    monkeypatch.setattr(
        pd,
        "read_parquet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("materialised parquet")),
    )
    monkeypatch.setattr(
        pd,
        "read_csv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("materialised csv")),
    )

    assert artifact_metadata(output / "face_features.parquet", "full")["rows"] == 1
    assert artifact_metadata(output / "face_core.csv", "core")["rows"] == 2


def test_complete_schema_constants_match_pyfeat_2_1_1_contract() -> None:
    assert len(AU_NAMES) == 20
    assert EMOTION_NAMES == (
        "Neutral", "Happy", "Sad", "Surprise", "Fear", "Disgust", "Anger"
    )
