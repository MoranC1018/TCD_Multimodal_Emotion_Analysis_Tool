"""Regression coverage for precision across generated reports and workbooks."""

import csv
import statistics
from pathlib import Path

import openpyxl
import pytest

from analysis.combined_summary import (
    VIDEO_METRICS,
    CombinedSource,
    SpeakerGroupDefinition,
    build_combined_workbook,
)
from analysis.histograms import (
    ColumnInfo,
    ParsedExport,
    analyse_grouped_parsed_exports,
    build_descriptor_rows,
    format_number,
    write_descriptive_statistics_csv,
)


def _export(root: Path, source: str, values: list[float]) -> ParsedExport:
    return ParsedExport(
        source=source,
        path=root / f"{source}.csv",
        header=list(VIDEO_METRICS),
        info={metric: ColumnInfo(metric, metric, category="FEA(Emotions)") for metric in VIDEO_METRICS},
        rows=[{metric: repr(value) for metric in VIDEO_METRICS} for value in values],
        speaker="Precision Researcher",
        video=source,
    )


def test_generated_report_preserves_precision_until_workbook_presentation(tmp_path: Path) -> None:
    """Rounding each video first changes the displayed pooled mean by 0.01."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    recordings = [[1.002, 1.006], [2.004]]
    analyse_grouped_parsed_exports(
        input_dir=inputs,
        output_dir=tmp_path / "reports",
        exports=[
            _export(inputs, f"{index:03d}_Recording", values)
            for index, values in enumerate(recordings, start=1)
        ],
        discovery_log=[],
        write_graphs=False,
    )
    report = next((tmp_path / "reports").glob("**/combined/other_findings/descriptive_statistics.csv"))
    result = build_combined_workbook(
        {"video": [CombinedSource("video", "precisionresearcher", "Precision Researcher", report)]},
        tmp_path / "combined.xlsx",
        speaker_groups=(SpeakerGroupDefinition("researchers", "Researchers", ("Precision Researcher",)),),
    )

    expected = statistics.mean(value for recording in recordings for value in recording)
    workbook = openpyxl.load_workbook(result.workbook_path)
    try:
        coordinate = result.source_cells["Video|Joy"].speaker_cells[0]
        headline = workbook["Video"][coordinate]
        assert headline.value == pytest.approx(expected, abs=1e-14)
        assert headline.number_format == "0.00"
        assert f"{headline.value:.2f}" == "1.34"
    finally:
        workbook.close()


def test_descriptor_csv_roundtrips_all_numeric_statistics(tmp_path: Path) -> None:
    values = [0.0, 0.0123456, 7.8901234, 34.5678912, 99.999991]
    mean = statistics.mean(values)
    variance = statistics.pvariance(values)
    expected = {
        "count": 5,
        "missing": 0,
        "mean": mean,
        "stddev": statistics.stdev(values),
        "min": values[0],
        "q1": values[1],
        "median": values[2],
        "q3": values[3],
        "max": values[4],
        "kurtosis": statistics.mean((value - mean) ** 4 for value in values) / variance**2 - 3,
        "nonzero_count": 4,
        "nonzero_percent": 80.0,
    }
    export = _export(tmp_path, "001_Recording", values)
    rows = build_descriptor_rows(export, {"Joy": values}, {"Joy": "emotion_0_to_100"})
    report = tmp_path / "descriptive_statistics.csv"
    write_descriptive_statistics_csv(report, [export.source], rows)
    with report.open(encoding="utf-8", newline="") as handle:
        actual = {row[0]: row[1] for row in csv.reader(handle) if row and row[0] in expected}

    assert actual.keys() == expected.keys()
    for metric, value in expected.items():
        assert float(actual[metric]) == pytest.approx(value, rel=1e-14, abs=1e-14), metric
    # Human-facing labels continue to use two decimal places.
    assert format_number(mean) == "28.49"
