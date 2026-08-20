from __future__ import annotations

from procurement.procurement_beta.intervals import Interval
from procurement.procurement_beta.pipeline import ProcurementBetaOptions, build_segment_plan


def test_build_segment_plan_records_clean_rejected_and_selected_segments() -> None:
    options = ProcurementBetaOptions(
        output_mode="percentage",
        percentage=0.25,
        min_clean_seconds=10,
        max_segment_seconds=30,
        gap_seconds=0,
        identity_stills=20,
        scan_fps=1,
        face_confidence=0.65,
        speaker_confidence=0.65,
        worker_count=2,
        device="cpu",
        keep_debug=False,
    )

    plan = build_segment_plan(
        face_intervals=[Interval(0, 9), Interval(20, 80), Interval(100, 140)],
        voice_intervals=[Interval(0, 12), Interval(25, 75), Interval(105, 125)],
        video_duration_seconds=200,
        options=options,
    )

    assert [segment.interval for segment in plan.clean_segments] == [Interval(25, 75), Interval(105, 125)]
    assert [segment.interval for segment in plan.rejected_segments] == [Interval(0, 9)]
    assert [segment.interval for segment in plan.selected_segments] == [
        Interval(25, 55),
        Interval(55, 75),
    ]


def test_build_segment_plan_rejects_low_confidence_fallback_overlaps() -> None:
    options = ProcurementBetaOptions(
        output_mode="clean",
        percentage=0.10,
        min_clean_seconds=10,
        max_segment_seconds=30,
        gap_seconds=0,
        identity_stills=20,
        scan_fps=1,
        face_confidence=0.65,
        speaker_confidence=0.65,
        worker_count=2,
        device="cpu",
        keep_debug=False,
    )

    plan = build_segment_plan(
        face_intervals=[Interval(0, 100, 0.25)],
        voice_intervals=[Interval(0, 100, 0.25)],
        video_duration_seconds=100,
        options=options,
    )

    assert plan.clean_segments == []
    assert plan.selected_segments == []
    assert [segment.reason for segment in plan.rejected_segments] == ["below_confidence_threshold"]


def test_build_segment_plan_rejects_high_face_low_voice_overlap() -> None:
    options = ProcurementBetaOptions(
        output_mode="clean",
        percentage=0.10,
        min_clean_seconds=10,
        max_segment_seconds=30,
        gap_seconds=0,
        identity_stills=20,
        scan_fps=1,
        face_confidence=0.65,
        speaker_confidence=0.65,
        worker_count=2,
        device="cpu",
        keep_debug=False,
    )

    plan = build_segment_plan(
        face_intervals=[Interval(0, 100, 0.95)],
        voice_intervals=[Interval(0, 100, 0.40)],
        video_duration_seconds=100,
        options=options,
    )

    assert plan.clean_segments == []
    assert plan.selected_segments == []
    assert [segment.reason for segment in plan.rejected_segments] == ["below_confidence_threshold"]


def test_clean_compilation_keeps_full_clean_overlaps_without_max_clip_splitting() -> None:
    options = ProcurementBetaOptions(
        output_mode="clean",
        percentage=0.10,
        min_clean_seconds=10,
        max_segment_seconds=30,
        gap_seconds=0.5,
        identity_stills=20,
        scan_fps=1,
        face_confidence=0.65,
        speaker_confidence=0.65,
        worker_count=1,
        device="cpu",
        keep_debug=False,
    )

    plan = build_segment_plan(
        face_intervals=[Interval(0, 100, 0.9)],
        voice_intervals=[Interval(10, 90, 0.9)],
        video_duration_seconds=100,
        options=options,
    )

    assert [segment.interval for segment in plan.selected_segments] == [Interval(10, 90, 0.9)]

def test_clean_compilation_bridges_short_speech_gaps_before_minimum_filter() -> None:
    """Short diarization pauses should not make a usable visible speech run vanish."""

    options = ProcurementBetaOptions(
        output_mode="clean",
        percentage=0.10,
        min_clean_seconds=10,
        max_segment_seconds=30,
        gap_seconds=0.5,
        identity_stills=20,
        scan_fps=1,
        face_confidence=0.65,
        speaker_confidence=0.65,
        worker_count=1,
        device="cpu",
        keep_debug=False,
    )

    plan = build_segment_plan(
        face_intervals=[Interval(0, 30, 0.9)],
        voice_intervals=[Interval(0, 4, 0.9), Interval(6, 10, 0.9), Interval(12, 20, 0.9)],
        video_duration_seconds=30,
        options=options,
    )

    assert [segment.interval for segment in plan.selected_segments] == [Interval(0, 20, 0.9)]

def test_clean_compilation_keeps_near_minimum_frame_quantized_overlap() -> None:
    """Detector intervals within one frame step of the cutoff should not be skipped."""

    options = ProcurementBetaOptions(
        output_mode="clean",
        percentage=0.10,
        min_clean_seconds=10,
        max_segment_seconds=30,
        gap_seconds=0.5,
        identity_stills=20,
        scan_fps=1,
        face_confidence=0.65,
        speaker_confidence=0.65,
        worker_count=1,
        device="cpu",
        keep_debug=False,
    )

    plan = build_segment_plan(
        face_intervals=[Interval(0, 9.75, 0.9)],
        voice_intervals=[Interval(0, 9.75, 0.9)],
        video_duration_seconds=60,
        options=options,
    )

    assert [segment.interval for segment in plan.selected_segments] == [Interval(0, 9.75, 0.9)]
