from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Interval:
    """A timestamp range with an optional confidence score."""

    start: float
    end: float
    confidence: float = 1.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def trim_to_duration(self, duration_seconds: float) -> "Interval":
        safe_duration = max(0.0, float(duration_seconds))
        return Interval(self.start, min(self.end, self.start + safe_duration), self.confidence)


def intersect_intervals(first: list[Interval], second: list[Interval]) -> list[Interval]:
    """Return ranges where both interval lists are active."""

    left = sorted(first)
    right = sorted(second)
    overlaps: list[Interval] = []
    i = 0
    j = 0
    while i < len(left) and j < len(right):
        start = max(left[i].start, right[j].start)
        end = min(left[i].end, right[j].end)
        if end > start:
            confidence = min(left[i].confidence, right[j].confidence)
            overlaps.append(Interval(round_seconds(start), round_seconds(end), round_confidence(confidence)))
        if left[i].end <= right[j].end:
            i += 1
        else:
            j += 1
    return overlaps


def filter_min_duration(intervals: list[Interval], *, minimum_seconds: float) -> list[Interval]:
    """Keep only intervals that are long enough for reliable downstream clips."""

    minimum = max(0.0, float(minimum_seconds))
    return [item for item in intervals if item.duration >= minimum]


def split_segments(intervals: list[Interval], *, max_segment_seconds: float) -> list[Interval]:
    """Split long intervals into clip-sized chunks while preserving remainders."""

    maximum = max(0.1, float(max_segment_seconds))
    segments: list[Interval] = []
    for interval in sorted(intervals):
        cursor = interval.start
        while cursor < interval.end:
            end = min(interval.end, cursor + maximum)
            segments.append(Interval(round_seconds(cursor), round_seconds(end), interval.confidence))
            cursor = end
    return segments


def select_percentage_segments(
    intervals: list[Interval],
    *,
    video_duration_seconds: float,
    target_percentage: float,
    max_segment_seconds: float,
    minimum_seconds: float,
) -> list[Interval]:
    """Choose clean clips for an x-percent sample, preferring long segments."""

    target_seconds = max(0.0, float(video_duration_seconds)) * max(0.0, float(target_percentage))
    if target_seconds <= 0:
        return []

    candidates = filter_min_duration(intervals, minimum_seconds=minimum_seconds)
    ranked = sorted(candidates, key=lambda item: (item.duration, item.confidence), reverse=True)
    selected: list[Interval] = []
    remaining = target_seconds

    for interval in ranked:
        if remaining <= 0:
            break
        for chunk in split_segments([interval], max_segment_seconds=max_segment_seconds):
            if remaining <= 0:
                break
            if chunk.duration <= remaining:
                selected.append(chunk)
                remaining -= chunk.duration
                continue
            if remaining > 0:
                selected.append(chunk.trim_to_duration(remaining))
                remaining = 0

    return sorted(selected)


def merge_nearby_intervals(intervals: list[Interval], *, gap_seconds: float) -> list[Interval]:
    """Smooth detector chatter by joining intervals separated by short gaps."""

    maximum_gap = max(0.0, float(gap_seconds))
    merged: list[Interval] = []
    for interval in sorted(intervals):
        if interval.end <= interval.start:
            continue
        if not merged or interval.start - merged[-1].end > maximum_gap:
            merged.append(interval)
            continue
        previous = merged[-1]
        merged[-1] = Interval(
            previous.start,
            max(previous.end, interval.end),
            round_confidence((previous.confidence + interval.confidence) / 2.0),
        )
    return merged


def round_seconds(value: float) -> float:
    return round(float(value), 3)


def round_confidence(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)
