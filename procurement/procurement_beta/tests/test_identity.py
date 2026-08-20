from __future__ import annotations

from procurement.procurement_beta.identity import assign_identity_clusters, select_main_identity


def test_assign_identity_clusters_groups_similar_embeddings() -> None:
    clusters = assign_identity_clusters(
        [
            [1.0, 0.0],
            [0.95, 0.05],
            [0.0, 1.0],
        ],
        similarity_threshold=0.90,
    )

    assert clusters == [0, 0, 1]
    assert select_main_identity(clusters) == 0
