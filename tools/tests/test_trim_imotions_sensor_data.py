"""Regression tests for mapping source timestamps onto stitched video time."""

import json

import pytest

from tools import trim_imotions_sensor_data as trim


def test_clean_speaker_manifest_reader_rejects_oversized_sidecar(tmp_path) -> None:
    manifest = tmp_path / "speaker" / "video" / "clean_speaker_beta_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"padding": "x" * (1024 * 1024)}), encoding="utf-8")

    records, errors = trim.load_latest_manifests(tmp_path, {"ok"})

    assert records == {}
    assert errors and "exceeds 1048576 bytes" in errors[0]


def test_selected_segments_reader_rejects_excessive_semantic_items(tmp_path) -> None:
    (tmp_path / "selected_segments.json").write_text(
        json.dumps({"selected_segments": [None] * 50_001}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="more than 50000 items"):
        trim.read_selected_segments({}, tmp_path)


def test_default_timeline_keeps_current_stitcher_intervals_unchanged() -> None:
    segments = [{"start": 10.0, "end": 25.0, "confidence": 0.8}]

    result = trim.trim_stitch_edges(
        segments,
        edge_trim_seconds=trim.DEFAULT_STITCH_EDGE_TRIM_SECONDS,
        minimum_segment_seconds=trim.DEFAULT_MIN_EDGE_TRIM_SEGMENT_SECONDS,
    )

    assert trim.DEFAULT_STITCH_EDGE_TRIM_SECONDS == 0.0
    assert result == segments


def test_explicit_legacy_edge_trim_remains_available() -> None:
    segments = [{"start": 10.0, "end": 25.0, "confidence": 0.8}]

    result = trim.trim_stitch_edges(
        segments,
        edge_trim_seconds=0.25,
        minimum_segment_seconds=10.5,
    )

    assert result == [{"start": 10.25, "end": 24.75, "confidence": 0.8}]
