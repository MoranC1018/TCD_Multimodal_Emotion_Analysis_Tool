from __future__ import annotations

import math
from collections.abc import Sequence


def choose_profiled_speaker(
    reference_embedding: Sequence[float] | None,
    speaker_embeddings: dict[str, Sequence[float]],
    speaker_durations: dict[str, float],
) -> str | None:
    """Pick a speaker by profile match, falling back to longest duration."""

    if not speaker_embeddings:
        return None
    if reference_embedding:
        scored = [
            (cosine_similarity(reference_embedding, embedding), speaker)
            for speaker, embedding in speaker_embeddings.items()
        ]
        return max(scored)[1]
    if not speaker_durations:
        return next(iter(speaker_embeddings))
    return max(speaker_durations.items(), key=lambda item: item[1])[0]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    left_values = [float(value) for value in left]
    right_values = [float(value) for value in right]
    numerator = sum(a * b for a, b in zip(left_values, right_values))
    left_norm = math.sqrt(sum(value * value for value in left_values))
    right_norm = math.sqrt(sum(value * value for value in right_values))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return round(max(-1.0, min(1.0, numerator / (left_norm * right_norm))), 6)
