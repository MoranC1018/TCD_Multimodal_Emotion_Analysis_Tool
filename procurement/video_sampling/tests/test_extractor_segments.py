import random

from procurement.video_sampling import extractor


def test_random_segments_use_shorter_gaps_when_timeline_is_fragmented():
    """Sampling should keep going when only shorter legal gaps remain."""

    random.seed(123)

    segments = extractor.make_random_segments(
        video_duration=15,
        total_seconds_to_download=10,
        segment_length_seconds=30,
        no_go_segments=[extractor.TimeSegment(5, 10)],
    )

    assert sum(segment["length"] for segment in segments) == 10
    assert sorted(segment["length"] for segment in segments) == [5, 5]
    assert {segment["start"] for segment in segments} == {0, 10}
