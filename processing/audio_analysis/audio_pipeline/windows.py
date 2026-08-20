from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioWindow:
    """A timestamped audio slice to pass through the emotion models."""

    row: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def timestamp_ms(self) -> int:
        return int(round(self.start * 1000))


def make_windows(duration_seconds: float, window_seconds: float, stride_seconds: float) -> list[AudioWindow]:
    """Create overlapping windows without overweighting a tiny final remainder."""

    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if stride_seconds <= 0:
        raise ValueError("stride_seconds must be positive")

    if duration_seconds <= window_seconds:
        return [AudioWindow(row=1, start=0.0, end=round(duration_seconds, 6))]

    starts: list[float] = []
    start = 0.0
    epsilon = 1e-9
    while start + window_seconds <= duration_seconds + epsilon:
        starts.append(round(start, 6))
        start += stride_seconds

    tail_start = round(max(0.0, duration_seconds - window_seconds), 6)
    # A tail-aligned full window keeps the end of the recording represented,
    # but it must add a meaningful new position. Without this threshold, a
    # 12.01-second recording analysed in 12-second windows produced 0-12 and
    # 0.01-12.01 rows, effectively counting the same audio twice.
    minimum_tail_shift = min(window_seconds, stride_seconds) / 2.0
    if not starts or tail_start - starts[-1] >= minimum_tail_shift - epsilon:
        starts.append(tail_start)

    windows: list[AudioWindow] = []
    for index, window_start in enumerate(starts, start=1):
        window_end = min(window_start + window_seconds, duration_seconds)
        windows.append(AudioWindow(row=index, start=window_start, end=round(window_end, 6)))
    return windows
