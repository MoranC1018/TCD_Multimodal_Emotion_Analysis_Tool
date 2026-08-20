from __future__ import annotations

from dataclasses import asdict, dataclass

from procurement.procurement_beta.intervals import (
    Interval,
    filter_min_duration,
    intersect_intervals,
    merge_nearby_intervals,
    select_percentage_segments,
    split_segments,
)


MIN_CLEAN_DURATION_TOLERANCE_SECONDS = 0.5
MAX_CLEAN_OVERLAP_BRIDGE_GAP_SECONDS = 5.0


@dataclass(frozen=True)
class ProcurementBetaOptions:
    """User-controlled settings for the clean speaker segment experiment."""

    output_mode: str
    percentage: float
    min_clean_seconds: float
    max_segment_seconds: float
    gap_seconds: float
    identity_stills: int
    scan_fps: float
    face_confidence: float
    speaker_confidence: float
    worker_count: int
    device: str
    keep_debug: bool
    validation_fps: float = 4.0
    resource_guard_percent: float = 15.0
    resource_poll_seconds: float = 15.0
    resource_guard_timeout_seconds: float = 900.0
    parallel_detector_streams: bool = False
    skip_final_output_validation: bool = True
    face_reference_dir: str = ""


@dataclass(frozen=True)
class PlannedSegment:
    """A clean or rejected segment with the reason preserved for audit."""

    interval: Interval
    reason: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self.interval)
        payload["duration"] = self.interval.duration
        payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class SegmentPlan:
    """The full overlap decision record for one video."""

    overlap_segments: list[PlannedSegment]
    clean_segments: list[PlannedSegment]
    rejected_segments: list[PlannedSegment]
    selected_segments: list[PlannedSegment]

    def to_dict(self) -> dict[str, object]:
        return {
            "overlap_segments": [segment.to_dict() for segment in self.overlap_segments],
            "clean_segments": [segment.to_dict() for segment in self.clean_segments],
            "rejected_segments": [segment.to_dict() for segment in self.rejected_segments],
            "selected_segments": [segment.to_dict() for segment in self.selected_segments],
        }


def build_segment_plan(
    *,
    face_intervals: list[Interval],
    voice_intervals: list[Interval],
    video_duration_seconds: float,
    options: ProcurementBetaOptions,
) -> SegmentPlan:
    """Combine model outputs into the final clip plan for one video."""

    overlaps = merge_nearby_intervals(
        intersect_intervals(face_intervals, voice_intervals),
        gap_seconds=clean_overlap_bridge_gap(options),
    )
    confidence_threshold = min(options.face_confidence, options.speaker_confidence)
    duration_ready = filter_min_duration(overlaps, minimum_seconds=effective_min_clean_seconds(options))
    clean_intervals = [item for item in duration_ready if item.confidence >= confidence_threshold]
    clean_lookup = {(item.start, item.end) for item in clean_intervals}
    rejected_intervals = [item for item in overlaps if (item.start, item.end) not in clean_lookup]

    if options.output_mode == "percentage":
        selected = select_percentage_segments(
            clean_intervals,
            video_duration_seconds=video_duration_seconds,
            target_percentage=options.percentage,
            max_segment_seconds=options.max_segment_seconds,
            minimum_seconds=effective_min_clean_seconds(options),
        )
    else:
        selected = clean_intervals

    return SegmentPlan(
        overlap_segments=[PlannedSegment(item, "face_visible_and_voice_active") for item in overlaps],
        clean_segments=[PlannedSegment(item, "meets_minimum_clean_duration") for item in clean_intervals],
        rejected_segments=[PlannedSegment(item, rejection_reason(item, options, confidence_threshold)) for item in rejected_intervals],
        selected_segments=[PlannedSegment(item, selected_reason(options.output_mode)) for item in selected],
    )


def selected_reason(output_mode: str) -> str:
    if output_mode == "percentage":
        return "selected_for_target_percentage"
    return "selected_for_clean_compilation"


def clean_overlap_bridge_gap(options: ProcurementBetaOptions) -> float:
    """Bridge brief detector chatter without joining genuinely separate sections."""

    half_minimum = float(options.min_clean_seconds) / 2.0
    return min(MAX_CLEAN_OVERLAP_BRIDGE_GAP_SECONDS, max(1.5, half_minimum))


def effective_min_clean_seconds(options: ProcurementBetaOptions) -> float:
    """Allow one validation frame of tolerance around the user-facing minimum."""

    return max(0.0, float(options.min_clean_seconds) - MIN_CLEAN_DURATION_TOLERANCE_SECONDS)


def rejection_reason(interval: Interval, options: ProcurementBetaOptions, confidence_threshold: float) -> str:
    if interval.duration < effective_min_clean_seconds(options):
        return f"shorter_than_{options.min_clean_seconds:g}_seconds"
    if interval.confidence < confidence_threshold:
        return "below_confidence_threshold"
    return "not_selected"
