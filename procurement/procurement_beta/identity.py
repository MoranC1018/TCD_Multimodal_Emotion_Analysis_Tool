from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from procurement.procurement_beta.speaker_profile import cosine_similarity


def assign_identity_clusters(embeddings: Sequence[Sequence[float]], *, similarity_threshold: float) -> list[int]:
    """Cluster face embeddings with a small deterministic online strategy."""

    centroids: list[list[float]] = []
    counts: list[int] = []
    assignments: list[int] = []
    for embedding in embeddings:
        vector = [float(value) for value in embedding]
        best_index = best_centroid(vector, centroids)
        if best_index is None or cosine_similarity(vector, centroids[best_index]) < similarity_threshold:
            centroids.append(vector)
            counts.append(1)
            assignments.append(len(centroids) - 1)
            continue
        assignments.append(best_index)
        counts[best_index] += 1
        centroids[best_index] = update_centroid(centroids[best_index], vector, counts[best_index])
    return assignments


def select_main_identity(assignments: Sequence[int]) -> int | None:
    """Return the most common identity cluster id."""

    if not assignments:
        return None
    return Counter(assignments).most_common(1)[0][0]


def best_centroid(vector: Sequence[float], centroids: Sequence[Sequence[float]]) -> int | None:
    if not centroids:
        return None
    scored = [(cosine_similarity(vector, centroid), index) for index, centroid in enumerate(centroids)]
    return max(scored)[1]


def update_centroid(current: Sequence[float], vector: Sequence[float], count: int) -> list[float]:
    previous_weight = max(0, count - 1)
    return [((float(left) * previous_weight) + float(right)) / count for left, right in zip(current, vector)]
