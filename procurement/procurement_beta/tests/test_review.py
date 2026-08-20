from __future__ import annotations

from pathlib import Path

from procurement.procurement_beta.intervals import Interval
from procurement.procurement_beta.pipeline import PlannedSegment, SegmentPlan
from procurement.procurement_beta.review import rejection_counts, write_review_html


def test_rejection_counts_groups_reasons_for_ui_review() -> None:
    plan = SegmentPlan(
        overlap_segments=[],
        clean_segments=[],
        rejected_segments=[
            PlannedSegment(Interval(0, 4), "shorter_than_10_seconds"),
            PlannedSegment(Interval(8, 20), "below_confidence_threshold"),
            PlannedSegment(Interval(30, 31), "shorter_than_10_seconds"),
        ],
        selected_segments=[],
    )

    assert rejection_counts(plan) == {
        "shorter_than_10_seconds": 2,
        "below_confidence_threshold": 1,
    }


def test_write_review_html_surfaces_selected_and_rejected_segments(tmp_path: Path) -> None:
    plan = SegmentPlan(
        overlap_segments=[PlannedSegment(Interval(0, 20, 0.9), "face_visible_and_voice_active")],
        clean_segments=[PlannedSegment(Interval(0, 20, 0.9), "meets_minimum_clean_duration")],
        rejected_segments=[PlannedSegment(Interval(30, 35, 0.4), "below_confidence_threshold")],
        selected_segments=[PlannedSegment(Interval(0, 20, 0.9), "selected_for_clean_compilation")],
    )

    path = write_review_html(tmp_path, title="Video title", duration_seconds=40, plan=plan)

    text = path.read_text(encoding="utf-8")
    assert "Video title" in text
    assert "selected_for_clean_compilation" in text
    assert "below_confidence_threshold" in text
    assert "timeline-row" in text
