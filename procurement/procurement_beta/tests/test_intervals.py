from __future__ import annotations

from procurement.procurement_beta.intervals import (
    Interval,
    filter_min_duration,
    intersect_intervals,
    select_percentage_segments,
    split_segments,
)


def test_intersect_intervals_keeps_only_overlapping_time_ranges() -> None:
    face = [Interval(0, 12, 0.9), Interval(20, 40, 0.8)]
    voice = [Interval(5, 18, 0.7), Interval(22, 25, 0.6), Interval(30, 50, 0.9)]

    overlaps = intersect_intervals(face, voice)

    assert overlaps == [
        Interval(5, 12, 0.7),
        Interval(22, 25, 0.6),
        Interval(30, 40, 0.8),
    ]


def test_filter_min_duration_excludes_short_clean_segments() -> None:
    intervals = [Interval(0, 9.9), Interval(10, 20), Interval(30, 42)]

    assert filter_min_duration(intervals, minimum_seconds=10) == [
        Interval(10, 20),
        Interval(30, 42),
    ]


def test_split_segments_respects_max_length_and_keeps_final_remainder() -> None:
    segments = split_segments([Interval(0, 65, 0.75)], max_segment_seconds=30)

    assert segments == [
        Interval(0, 30, 0.75),
        Interval(30, 60, 0.75),
        Interval(60, 65, 0.75),
    ]


def test_select_percentage_segments_prioritises_longest_segments_and_trims_final() -> None:
    clean_segments = [
        Interval(0, 12, 0.8),
        Interval(20, 75, 0.9),
        Interval(90, 120, 0.7),
    ]

    selected = select_percentage_segments(
        clean_segments,
        video_duration_seconds=200,
        target_percentage=0.25,
        max_segment_seconds=30,
        minimum_seconds=10,
    )

    assert selected == [
        Interval(20, 50, 0.9),
        Interval(50, 70, 0.9),
    ]
