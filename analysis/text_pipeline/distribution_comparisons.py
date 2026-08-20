"""Permutation tests for weighted text means across videos within speakers."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Mapping, Sequence

from spreadsheet_safety import SpreadsheetSafeWriter


MEAN_COMPARISON_ROOT = "video_mean_comparisons"
DEFAULT_PERMUTATIONS = 9_999
DEFAULT_RANDOM_SEED = 20_260_811
PERMUTATION_BATCH_SIZE = 128


@dataclass(frozen=True)
class TextSegmentObservation:
    country: str
    speaker: str
    video: str
    segment_id: str
    terms: float
    category_counts: Mapping[str, float | None]
    positive_count: float | None
    negative_count: float | None


@dataclass(frozen=True)
class _MetricSeries:
    key: str
    label: str
    metric_type: str
    observations: tuple[TextSegmentObservation, ...]
    numerators: np.ndarray
    denominators: np.ndarray


def write_text_mean_comparisons(
    output_dir: Path,
    observations: Sequence[TextSegmentObservation],
    category_labels: Mapping[str, str],
    *,
    permutations: int = DEFAULT_PERMUTATIONS,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> list[Path]:
    """Write video means and segment-label permutation tests for each speaker."""

    if permutations < 1:
        raise ValueError("permutations must be at least 1")

    grouped: dict[tuple[str, str], list[TextSegmentObservation]] = defaultdict(list)
    for observation in observations:
        _validate_observation(observation)
        grouped[(observation.country, observation.speaker)].append(observation)

    written: list[Path] = []
    root = output_dir / MEAN_COMPARISON_ROOT
    for (country, speaker), speaker_observations in sorted(grouped.items()):
        combined = (
            root / country / speaker / "combined"
            if country
            else root / speaker / "combined"
        )
        combined.mkdir(parents=True, exist_ok=True)
        ordered = sorted(
            speaker_observations,
            key=lambda item: (item.video, _segment_sort_key(item.segment_id)),
        )
        metric_series = _build_metric_series(ordered, category_labels)

        means_path = combined / "video_means.csv"
        _write_video_means(means_path, ordered, category_labels)
        permutation_path = combined / "permutation_test_results.csv"
        _write_permutation_results(
            permutation_path,
            country,
            speaker,
            metric_series,
            permutations=permutations,
            random_seed=random_seed,
        )
        written.extend((means_path, permutation_path))
    return written


def write_text_mean_comparisons_from_existing_output(
    output_dir: Path,
    *,
    permutations: int = DEFAULT_PERMUTATIONS,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> list[Path]:
    """Backfill permutation reports from existing enriched segment CSV files."""

    labels = _category_labels_from_manifest(output_dir / "output_manifest.json")
    segment_paths = sorted(
        (output_dir / "segment_level").rglob("*_segments_enriched.csv")
    )
    if not labels and segment_paths:
        with segment_paths[0].open("r", encoding="utf-8", newline="") as handle:
            fieldnames = csv.DictReader(handle).fieldnames or []
        keys = [
            name[: -len("_count")]
            for name in fieldnames
            if name.endswith("_count")
            and f"{name[: -len('_count')]}_available" in fieldnames
        ]
        labels = {key: key.replace("_", " ").title() for key in keys}
    observations: list[TextSegmentObservation] = []
    for path in segment_paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if _finite_number(row.get("valid_segment")) != 1:
                    continue
                terms = _finite_number(row.get("rocksteady_terms"))
                if terms is None or terms <= 0:
                    continue
                counts = {
                    key: _available_category_count(row, key)
                    for key in labels
                }
                observations.append(
                    TextSegmentObservation(
                        country=str(row.get("country", "")),
                        speaker=str(row.get("speaker", "")),
                        video=str(row.get("video", "")),
                        segment_id=str(row.get("segment_id", "")),
                        terms=terms,
                        category_counts=counts,
                        positive_count=counts.get("positive"),
                        negative_count=counts.get("negative"),
                    )
                )
    return write_text_mean_comparisons(
        output_dir,
        observations,
        labels,
        permutations=permutations,
        random_seed=random_seed,
    )


def _build_metric_series(
    observations: Sequence[TextSegmentObservation],
    category_labels: Mapping[str, str],
) -> list[_MetricSeries]:
    import numpy as np

    series: list[_MetricSeries] = []
    for key, label in category_labels.items():
        eligible = tuple(
            observation
            for observation in observations
            if observation.category_counts.get(key) is not None
        )
        if not eligible:
            continue
        series.append(
            _MetricSeries(
                key=key,
                label=label,
                metric_type="category_proportion",
                observations=eligible,
                numerators=np.asarray(
                    [float(observation.category_counts[key]) for observation in eligible],
                    dtype=float,
                ),
                denominators=np.asarray(
                    [observation.terms for observation in eligible], dtype=float
                ),
            )
        )

    valence = tuple(
        observation
        for observation in observations
        if observation.positive_count is not None
        and observation.negative_count is not None
        and observation.positive_count + observation.negative_count > 0
    )
    if valence:
        series.append(
            _MetricSeries(
                key="valence",
                label="Text Valence",
                metric_type="positive_negative_balance",
                observations=valence,
                numerators=np.asarray(
                    [
                        float(observation.positive_count - observation.negative_count)
                        for observation in valence
                    ],
                    dtype=float,
                ),
                denominators=np.asarray(
                    [
                        float(observation.positive_count + observation.negative_count)
                        for observation in valence
                    ],
                    dtype=float,
                ),
            )
        )
    return series


def _write_video_means(
    path: Path,
    observations: Sequence[TextSegmentObservation],
    category_labels: Mapping[str, str],
) -> None:
    fields = (
        "country",
        "speaker",
        "video",
        "metric",
        "metric_type",
        "eligible_segments",
        "category_hits",
        "other_terms",
        "total_terms",
        "positive_count",
        "negative_count",
        "positive_negative_total",
        "mean_value",
    )
    videos: dict[str, list[TextSegmentObservation]] = defaultdict(list)
    for observation in observations:
        videos[observation.video].append(observation)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = SpreadsheetSafeWriter(
            csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        )
        writer.writeheader()
        for video, video_observations in sorted(videos.items()):
            first = video_observations[0]
            for key, label in category_labels.items():
                eligible = [
                    observation
                    for observation in video_observations
                    if observation.category_counts.get(key) is not None
                ]
                if not eligible:
                    continue
                hits = sum(float(item.category_counts[key]) for item in eligible)
                terms = sum(item.terms for item in eligible)
                writer.writerow(
                    {
                        "country": first.country,
                        "speaker": first.speaker,
                        "video": video,
                        "metric": label,
                        "metric_type": "category_proportion",
                        "eligible_segments": len(eligible),
                        "category_hits": _number(hits),
                        "other_terms": _number(terms - hits),
                        "total_terms": _number(terms),
                        "positive_count": "",
                        "negative_count": "",
                        "positive_negative_total": "",
                        "mean_value": _number(hits / terms),
                    }
                )

            valence = [
                observation
                for observation in video_observations
                if observation.positive_count is not None
                and observation.negative_count is not None
                and observation.positive_count + observation.negative_count > 0
            ]
            if valence:
                positive = sum(float(item.positive_count) for item in valence)
                negative = sum(float(item.negative_count) for item in valence)
                evidence = positive + negative
                writer.writerow(
                    {
                        "country": first.country,
                        "speaker": first.speaker,
                        "video": video,
                        "metric": "Text Valence",
                        "metric_type": "positive_negative_balance",
                        "eligible_segments": len(valence),
                        "category_hits": "",
                        "other_terms": "",
                        "total_terms": "",
                        "positive_count": _number(positive),
                        "negative_count": _number(negative),
                        "positive_negative_total": _number(evidence),
                        "mean_value": _number((positive - negative) / evidence),
                    }
                )


def _write_permutation_results(
    path: Path,
    country: str,
    speaker: str,
    metric_series: Sequence[_MetricSeries],
    *,
    permutations: int,
    random_seed: int,
) -> None:
    rows = _permutation_rows(
        country,
        speaker,
        metric_series,
        permutations=permutations,
        random_seed=random_seed,
    )
    _apply_holm_adjustments(rows)
    fields = (
        "country",
        "speaker",
        "metric",
        "metric_type",
        "test_scope",
        "video_a",
        "video_b",
        "video_count",
        "eligible_segments",
        "segments_a",
        "segments_b",
        "mean_a",
        "mean_b",
        "statistic_name",
        "observed_statistic",
        "permutations",
        "p_value_resolution",
        "raw_p_value",
        "holm_adjusted_p_value",
        "holm_family",
        "test_status",
        "random_seed",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = SpreadsheetSafeWriter(
            csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        )
        writer.writeheader()
        for row in rows:
            output = dict(row)
            for field in (
                "mean_a",
                "mean_b",
                "observed_statistic",
                "p_value_resolution",
                "raw_p_value",
                "holm_adjusted_p_value",
            ):
                if isinstance(output.get(field), float):
                    output[field] = _number(output[field])
            writer.writerow(output)


def _permutation_rows(
    country: str,
    speaker: str,
    metric_series: Sequence[_MetricSeries],
    *,
    permutations: int,
    random_seed: int,
) -> list[dict[str, object]]:
    grouped: dict[tuple[tuple[str, str], ...], list[_MetricSeries]] = defaultdict(list)
    for series in metric_series:
        signature = tuple(
            (observation.video, observation.segment_id)
            for observation in series.observations
        )
        grouped[signature].append(series)

    rows: list[dict[str, object]] = []
    for signature, series_group in grouped.items():
        rows.extend(
            _permutation_rows_for_shared_observations(
                country,
                speaker,
                signature,
                series_group,
                permutations=permutations,
                random_seed=random_seed,
            )
        )
    return sorted(
        rows,
        key=lambda row: (
            str(row["metric"]),
            0 if row["test_scope"] == "overall" else 1,
            str(row["video_a"]),
            str(row["video_b"]),
        ),
    )


def _permutation_rows_for_shared_observations(
    country: str,
    speaker: str,
    signature: tuple[tuple[str, str], ...],
    series_group: Sequence[_MetricSeries],
    *,
    permutations: int,
    random_seed: int,
) -> list[dict[str, object]]:
    import numpy as np

    observations = series_group[0].observations
    videos = sorted({observation.video for observation in observations})
    if len(videos) < 2:
        return []
    labels = np.asarray([observation.video for observation in observations])
    numerators = np.column_stack([series.numerators for series in series_group])
    denominators = np.column_stack([series.denominators for series in series_group])
    constant = np.asarray(
        [
            bool(
                np.allclose(
                    series.numerators / series.denominators,
                    (series.numerators / series.denominators)[0],
                    rtol=0,
                    atol=1e-15,
                )
            )
            for series in series_group
        ]
    )
    resolution = 1 / (permutations + 1)
    rows: list[dict[str, object]] = []

    group_indices = [np.flatnonzero(labels == video) for video in videos]
    observed_numerator = np.vstack(
        [numerators[indexes].sum(axis=0) for indexes in group_indices]
    )
    observed_denominator = np.vstack(
        [denominators[indexes].sum(axis=0) for indexes in group_indices]
    )
    observed_means = observed_numerator / observed_denominator
    pooled_means = numerators.sum(axis=0) / denominators.sum(axis=0)
    observed_overall = np.sum(
        observed_denominator * (observed_means - pooled_means) ** 2,
        axis=0,
    )
    overall_seed = _derived_seed(
        random_seed,
        country,
        speaker,
        "overall",
        _signature_digest(signature),
    )
    overall_extreme = _overall_extreme_counts(
        numerators,
        denominators,
        [len(indexes) for indexes in group_indices],
        observed_overall,
        permutations,
        overall_seed,
    )
    overall_p = (overall_extreme + 1) / (permutations + 1)
    for metric_index, series in enumerate(series_group):
        rows.append(
            {
                "country": country,
                "speaker": speaker,
                "metric": series.label,
                "metric_type": series.metric_type,
                "test_scope": "overall",
                "video_a": "",
                "video_b": "",
                "video_count": len(videos),
                "eligible_segments": len(observations),
                "segments_a": "",
                "segments_b": "",
                "mean_a": "",
                "mean_b": "",
                "statistic_name": "weighted_between_video_variation",
                "observed_statistic": float(observed_overall[metric_index]),
                "permutations": permutations,
                "p_value_resolution": resolution,
                "raw_p_value": float(overall_p[metric_index]),
                "holm_adjusted_p_value": "",
                "holm_family": "overall_metrics_within_speaker",
                "test_status": "constant_segment_values" if constant[metric_index] else "ok",
                "random_seed": _seed_text(overall_seed),
                "_metric_key": series.key,
            }
        )

    for left_video, right_video in combinations(videos, 2):
        left_indexes = np.flatnonzero(labels == left_video)
        right_indexes = np.flatnonzero(labels == right_video)
        pair_indexes = np.concatenate((left_indexes, right_indexes))
        pair_numerators = numerators[pair_indexes]
        pair_denominators = denominators[pair_indexes]
        left_numerator = numerators[left_indexes].sum(axis=0)
        left_denominator = denominators[left_indexes].sum(axis=0)
        right_numerator = numerators[right_indexes].sum(axis=0)
        right_denominator = denominators[right_indexes].sum(axis=0)
        left_means = left_numerator / left_denominator
        right_means = right_numerator / right_denominator
        observed_pairwise = np.abs(left_means - right_means)
        pair_seed = _derived_seed(
            random_seed,
            country,
            speaker,
            "pairwise",
            left_video,
            right_video,
            _signature_digest(signature),
        )
        pair_extreme = _pairwise_extreme_counts(
            pair_numerators,
            pair_denominators,
            len(left_indexes),
            observed_pairwise,
            permutations,
            pair_seed,
        )
        pair_p = (pair_extreme + 1) / (permutations + 1)
        for metric_index, series in enumerate(series_group):
            rows.append(
                {
                    "country": country,
                    "speaker": speaker,
                    "metric": series.label,
                    "metric_type": series.metric_type,
                    "test_scope": "pairwise",
                    "video_a": left_video,
                    "video_b": right_video,
                    "video_count": 2,
                    "eligible_segments": len(pair_indexes),
                    "segments_a": len(left_indexes),
                    "segments_b": len(right_indexes),
                    "mean_a": float(left_means[metric_index]),
                    "mean_b": float(right_means[metric_index]),
                    "statistic_name": "absolute_weighted_mean_difference",
                    "observed_statistic": float(observed_pairwise[metric_index]),
                    "permutations": permutations,
                    "p_value_resolution": resolution,
                    "raw_p_value": float(pair_p[metric_index]),
                    "holm_adjusted_p_value": "",
                    "holm_family": "pairwise_videos_within_metric",
                    "test_status": "constant_segment_values" if constant[metric_index] else "ok",
                    "random_seed": _seed_text(pair_seed),
                    "_metric_key": series.key,
                }
            )
    return rows


def _overall_extreme_counts(
    numerators: np.ndarray,
    denominators: np.ndarray,
    group_sizes: Sequence[int],
    observed: np.ndarray,
    permutations: int,
    random_seed: int,
) -> np.ndarray:
    import numpy as np

    rng = np.random.default_rng(random_seed)
    extreme = np.zeros(observed.shape, dtype=np.int64)
    base = np.arange(numerators.shape[0])
    offsets = np.cumsum((0, *group_sizes))
    pooled_means = numerators.sum(axis=0) / denominators.sum(axis=0)
    completed = 0
    while completed < permutations:
        batch = min(PERMUTATION_BATCH_SIZE, permutations - completed)
        order = rng.permuted(np.broadcast_to(base, (batch, len(base))), axis=1)
        statistic = np.zeros((batch, numerators.shape[1]), dtype=float)
        for start, stop in zip(offsets[:-1], offsets[1:]):
            indexes = order[:, start:stop]
            group_numerator = numerators[indexes].sum(axis=1)
            group_denominator = denominators[indexes].sum(axis=1)
            group_mean = group_numerator / group_denominator
            statistic += group_denominator * (group_mean - pooled_means) ** 2
        extreme += np.count_nonzero(
            statistic >= _comparison_floor(observed), axis=0
        )
        completed += batch
    return extreme


def _pairwise_extreme_counts(
    numerators: np.ndarray,
    denominators: np.ndarray,
    left_size: int,
    observed: np.ndarray,
    permutations: int,
    random_seed: int,
) -> np.ndarray:
    import numpy as np

    rng = np.random.default_rng(random_seed)
    extreme = np.zeros(observed.shape, dtype=np.int64)
    base = np.arange(numerators.shape[0])
    total_numerator = numerators.sum(axis=0)
    total_denominator = denominators.sum(axis=0)
    completed = 0
    while completed < permutations:
        batch = min(PERMUTATION_BATCH_SIZE, permutations - completed)
        order = rng.permuted(np.broadcast_to(base, (batch, len(base))), axis=1)
        left_indexes = order[:, :left_size]
        left_numerator = numerators[left_indexes].sum(axis=1)
        left_denominator = denominators[left_indexes].sum(axis=1)
        right_numerator = total_numerator - left_numerator
        right_denominator = total_denominator - left_denominator
        statistic = np.abs(
            left_numerator / left_denominator
            - right_numerator / right_denominator
        )
        extreme += np.count_nonzero(
            statistic >= _comparison_floor(observed), axis=0
        )
        completed += batch
    return extreme


def _comparison_floor(observed: np.ndarray) -> np.ndarray:
    import numpy as np

    return observed - np.maximum(1e-15, np.abs(observed) * 1e-12)


def _apply_holm_adjustments(rows: list[dict[str, object]]) -> None:
    overall = [row for row in rows if row["test_scope"] == "overall"]
    adjusted = holm_adjusted_p_values(
        [float(row["raw_p_value"]) for row in overall]
    )
    for row, value in zip(overall, adjusted):
        row["holm_adjusted_p_value"] = value

    metric_keys = sorted({str(row["_metric_key"]) for row in rows})
    for metric_key in metric_keys:
        pairwise = [
            row
            for row in rows
            if row["test_scope"] == "pairwise"
            and row["_metric_key"] == metric_key
        ]
        adjusted = holm_adjusted_p_values(
            [float(row["raw_p_value"]) for row in pairwise]
        )
        for row, value in zip(pairwise, adjusted):
            row["holm_adjusted_p_value"] = value

    for row in rows:
        row.pop("_metric_key", None)


def holm_adjusted_p_values(p_values: Sequence[float]) -> list[float]:
    """Return step-down Holm adjusted p-values in original order."""

    if not p_values:
        return []
    order = sorted(range(len(p_values)), key=lambda index: p_values[index])
    adjusted = [0.0] * len(p_values)
    running = 0.0
    total = len(p_values)
    for rank, index in enumerate(order):
        candidate = min(1.0, (total - rank) * p_values[index])
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def _validate_observation(observation: TextSegmentObservation) -> None:
    if not math.isfinite(observation.terms) or observation.terms <= 0:
        raise ValueError(
            f"Invalid Terms for {observation.country}/{observation.speaker}/"
            f"{observation.video}/{observation.segment_id}: {observation.terms}"
        )
    for key, value in observation.category_counts.items():
        if value is None:
            continue
        if not math.isfinite(value) or value < 0 or value > observation.terms:
            raise ValueError(
                f"Invalid {key} count for {observation.country}/{observation.speaker}/"
                f"{observation.video}/{observation.segment_id}: "
                f"count={value}, Terms={observation.terms}"
            )
    for label, value in (
        ("positive", observation.positive_count),
        ("negative", observation.negative_count),
    ):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError(
                f"Invalid {label} count for {observation.country}/{observation.speaker}/"
                f"{observation.video}/{observation.segment_id}: count={value}"
            )


def _available_category_count(row: Mapping[str, object], key: str) -> float | None:
    available = _finite_number(row.get(f"{key}_available"))
    if available == 0:
        return None
    return _finite_number(row.get(f"{key}_count"))


def _category_labels_from_manifest(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    categories = payload.get("categories")
    if not isinstance(categories, list):
        return {}
    return {
        str(item["key"]): str(item.get("display") or item["key"])
        for item in categories
        if isinstance(item, dict) and item.get("key")
    }


def _derived_seed(base: int, *parts: object) -> int:
    payload = "\x1f".join((str(base), *(str(part) for part in parts)))
    return int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big"
    )


def _signature_digest(signature: Sequence[tuple[str, str]]) -> str:
    payload = "\x1e".join(f"{video}\x1f{segment}" for video, segment in signature)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _seed_text(value: int) -> str:
    return f"0x{value:016x}"


def _segment_sort_key(value: str) -> tuple[int, object]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, value)


def _finite_number(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _number(value: float) -> str:
    return format(value, ".12g")
