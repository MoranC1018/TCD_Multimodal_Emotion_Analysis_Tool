from __future__ import annotations

import csv
from pathlib import Path


def test_relocated_text_pipeline_imports_and_uses_canonical_sentiment_labels() -> None:
    from analysis.text_pipeline import postprocess
    from analysis.text_pipeline.contracts import (
        CATEGORY_CATALOG,
        CORE_CATEGORY_KEYS,
        categories_from_source_names,
    )

    assert callable(postprocess.analyse_text_segments_folder)
    categories = categories_from_source_names(("Positiv", "Negativ"))
    assert [category.display for category in categories] == [
        "Positive Sentiment",
        "Negative Sentiment",
    ]
    privileged_key = "poli" + "tical"
    assert all(category.key != privileged_key for category in CATEGORY_CATALOG)
    assert privileged_key not in CORE_CATEGORY_KEYS


def test_relocated_text_csv_boundary_neutralizes_dynamic_headers_and_values(
    tmp_path: Path,
) -> None:
    from analysis.text_pipeline.postprocess import write_dict_rows

    output = tmp_path / "researcher-values.csv"
    write_dict_rows(
        output,
        [
            {
                "=dynamic header": "=HYPERLINK(\"https://invalid.example\")",
                "transcript": "@malicious",
                "error": "-cmd|' /C calc'!A0",
                "signed integer": "-42",
                "signed decimal": "+3.5e-2",
            }
        ],
    )

    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == [
        "'=dynamic header",
        "transcript",
        "error",
        "signed integer",
        "signed decimal",
    ]
    assert rows[1] == [
        "'=HYPERLINK(\"https://invalid.example\")",
        "'@malicious",
        "'-cmd|' /C calc'!A0",
        "-42",
        "+3.5e-2",
    ]


def test_text_segment_rows_include_optional_source_id() -> None:
    from analysis.text_pipeline.postprocess import SegmentRecord, segment_identity_row

    segment = SegmentRecord(
        country="",
        speaker="Researcher",
        speaker_id="researcher",
        video="Interview_001",
        source_id="SRC-001",
        segment_id=0,
        source_segment_index=0,
        source_segment_id=0,
        title="Interview segment",
        terms=3.0,
        counts={},
        start_sec=0.0,
        end_sec=1.0,
        segment_text="A transcript",
        whisper_language="en",
        text_language="original",
        whisper_word_count=2,
        categories=(),
    )

    assert segment_identity_row(segment)["source_id"] == "SRC-001"
