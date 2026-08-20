from __future__ import annotations

from procurement.procurement_beta.speaker_profile import choose_profiled_speaker, cosine_similarity


def test_choose_profiled_speaker_prefers_reference_embedding_over_longest_duration() -> None:
    speaker_embeddings = {
        "short_match": [1.0, 0.0],
        "long_wrong": [0.0, 1.0],
    }
    speaker_durations = {"short_match": 5.0, "long_wrong": 50.0}

    assert choose_profiled_speaker([0.9, 0.1], speaker_embeddings, speaker_durations) == "short_match"
    assert cosine_similarity([1, 0], [0, 1]) == 0.0
