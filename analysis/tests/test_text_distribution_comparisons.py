from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from analysis.text_pipeline.distribution_comparisons import (
    TextSegmentObservation,
    holm_adjusted_p_values,
    write_text_mean_comparisons,
)


def observation(
    video: str,
    segment_id: int,
    *,
    terms: float = 10,
    positive: float = 0,
    negative: float = 0,
) -> TextSegmentObservation:
    return TextSegmentObservation(
        country="France",
        speaker="Test Speaker",
        video=video,
        segment_id=str(segment_id),
        terms=terms,
        category_counts={"positive": positive},
        positive_count=positive,
        negative_count=negative,
    )


class TextMeanPermutationTests(unittest.TestCase):
    def test_weighted_video_means_and_permutation_p_values_are_written(self) -> None:
        observations = [
            *[
                observation("video_001", index, positive=0, negative=2)
                for index in range(6)
            ],
            *[
                observation("video_002", index, positive=2, negative=0)
                for index in range(6)
            ],
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            write_text_mean_comparisons(
                output,
                observations,
                {"positive": "Positive"},
                permutations=999,
                random_seed=1234,
            )
            combined = (
                output
                / "video_mean_comparisons"
                / "France"
                / "Test Speaker"
                / "combined"
            )
            with (combined / "video_means.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                means = list(csv.DictReader(handle))
            with (combined / "permutation_test_results.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                tests = list(csv.DictReader(handle))

        positive_means = [row for row in means if row["metric"] == "Positive"]
        self.assertEqual(positive_means[0]["eligible_segments"], "6")
        self.assertEqual(positive_means[0]["category_hits"], "0")
        self.assertEqual(positive_means[0]["total_terms"], "60")
        self.assertEqual(positive_means[0]["mean_value"], "0")
        self.assertEqual(positive_means[1]["category_hits"], "12")
        self.assertEqual(positive_means[1]["mean_value"], "0.2")

        pairwise = next(
            row
            for row in tests
            if row["metric"] == "Positive" and row["test_scope"] == "pairwise"
        )
        self.assertEqual(pairwise["statistic_name"], "absolute_weighted_mean_difference")
        self.assertEqual(pairwise["mean_a"], "0")
        self.assertEqual(pairwise["mean_b"], "0.2")
        self.assertEqual(pairwise["observed_statistic"], "0.2")
        self.assertEqual(pairwise["permutations"], "999")
        self.assertEqual(pairwise["p_value_resolution"], "0.001")
        self.assertLess(float(pairwise["raw_p_value"]), 0.05)
        self.assertGreaterEqual(
            float(pairwise["holm_adjusted_p_value"]),
            float(pairwise["raw_p_value"]),
        )
        self.assertNotIn("df", pairwise)
        self.assertEqual(len(tests), 4)

    def test_same_seed_and_data_produce_identical_output(self) -> None:
        observations = [
            observation("video_001", index, positive=index % 2, negative=1)
            for index in range(5)
        ] + [
            observation("video_002", index, positive=2, negative=index % 2)
            for index in range(5)
        ]
        with tempfile.TemporaryDirectory() as left_dir, tempfile.TemporaryDirectory() as right_dir:
            for output in (Path(left_dir), Path(right_dir)):
                write_text_mean_comparisons(
                    output,
                    list(reversed(observations)),
                    {"positive": "Positive"},
                    permutations=199,
                    random_seed=9876,
                )
            left = next(Path(left_dir).rglob("permutation_test_results.csv")).read_text(
                encoding="utf-8"
            )
            right = next(Path(right_dir).rglob("permutation_test_results.csv")).read_text(
                encoding="utf-8"
            )
        self.assertEqual(left, right)

    def test_count_above_terms_is_rejected(self) -> None:
        invalid = observation("video_001", 1, terms=10, positive=11)
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "count=11"):
                write_text_mean_comparisons(
                    Path(temp_dir),
                    [invalid],
                    {"positive": "Positive"},
                    permutations=9,
                )

    def test_constant_values_return_p_one_with_explicit_status(self) -> None:
        observations = [
            observation(video, index, positive=0, negative=0)
            for video in ("video_001", "video_002")
            for index in range(3)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            write_text_mean_comparisons(
                output,
                observations,
                {"positive": "Positive"},
                permutations=99,
            )
            with next(output.rglob("permutation_test_results.csv")).open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["raw_p_value"] == "1" for row in rows))
        self.assertTrue(
            all(row["test_status"] == "constant_segment_values" for row in rows)
        )

    def test_holm_adjustment_is_step_down_and_monotonic(self) -> None:
        adjusted = holm_adjusted_p_values([0.01, 0.04, 0.03])
        self.assertEqual(adjusted, [0.03, 0.06, 0.06])


if __name__ == "__main__":
    unittest.main()
