"""Small complete Py-Feat 2.1.1 rows used by Face contract tests."""

from __future__ import annotations

from processing.face_analysis.outputs import AU_NAMES, EMOTION_NAMES


def complete_detection_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "frame": 0,
        "FaceRectX": 10.0,
        "FaceRectY": 20.0,
        "FaceRectWidth": 100.0,
        "FaceRectHeight": 120.0,
        "FaceScore": 0.99,
        "valence": 0.1,
        "arousal": 0.2,
    }
    row.update({name: 0.1 for name in AU_NAMES})
    row.update({name: 0.1 for name in EMOTION_NAMES})
    row["Neutral"] = 0.4
    row.update(overrides)
    return row
