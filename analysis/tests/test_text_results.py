"""Contract tests for imported transcript construct summaries."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from analysis.text_results import TextResultsError, discover_text_results


IDENTITY_HEADERS = (
    "Country",
    "Speaker",
    "Speaker ID",
    "Videos",
    "Valid segments",
    "RockSteady terms",
)
CANONICAL_HEADERS = (
    *IDENTITY_HEADERS,
    "Positive Sentiment",
    "Negative Sentiment",
    "Arousal / Activation",
    "Dominance / Power",
    "Affiliation / Social orientation",
)
LEGACY_HEADERS = (
    *IDENTITY_HEADERS,
    "Positive valence",
    "Negative valence",
    "Arousal / Activation",
    "Dominance / Power",
    "Affiliation / Social orientation",
)


def write_text_summary(
    path: Path,
    rows: list[tuple[object, ...]],
    headers: tuple[str, ...] = LEGACY_HEADERS,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


class TextResultsTests(unittest.TestCase):
    def test_discovers_multimodal_summary_and_normalizes_speakers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary_path = root / "text_output" / "multimodal" / "speaker_level_summary.csv"
            write_text_summary(
                summary_path,
                [
                    ("UK", "Andy Burnham", "UK/Andy Burnham", 5, 20, 100, 0.2, 0.1, 0.3, 0.4, 0.5),
                    ("France", "Marine Le Pen", "France/Marine Le Pen", 5, 20, 100, 0.3, 0.2, "", 0.5, 0.6),
                ],
            )

            result = discover_text_results(root)

            self.assertEqual(result.summary_path, summary_path.resolve())
            self.assertEqual(
                [summary.speaker_id for summary in result.summaries],
                ["andyburnham", "marinelepen"],
            )
            self.assertEqual(result.summaries[0].constructs["Positive Sentiment"], 0.2)
            self.assertIsNone(result.summaries[1].constructs["Arousal / Activation"])

    def test_canonical_sentiment_headers_are_normalized_and_keep_declared_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_text_summary(
                root / "multimodal" / "speaker_level_summary.csv",
                [("UK", "Andy Burnham", "UK/Andy Burnham", 5, 20, 100, 1, 0, -1, 0, 1)],
                CANONICAL_HEADERS,
            )

            summary = discover_text_results(root).summaries[0]

        self.assertEqual(
            summary.constructs,
            {
                "Positive Sentiment": 1.0,
                "Negative Sentiment": 0.0,
                "Arousal / Activation": -1.0,
                "Dominance / Power": 0.0,
                "Affiliation / Social orientation": 1.0,
            },
        )

    def test_canonical_sentiment_headers_take_precedence_over_legacy_aliases(self) -> None:
        headers = (
            *IDENTITY_HEADERS,
            "Positive valence",
            "Negative valence",
            "Positive Sentiment",
            "Negative Sentiment",
            "Arousal / Activation",
            "Dominance / Power",
            "Affiliation / Social orientation",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_text_summary(
                root / "multimodal" / "speaker_level_summary.csv",
                [("UK", "Andy Burnham", "UK/Andy Burnham", 5, 20, 100, 0.9, 0.8, 0.2, 0.1, 0, 0, 0)],
                headers,
            )

            constructs = discover_text_results(root).summaries[0].constructs

        self.assertEqual(constructs["Positive Sentiment"], 0.2)
        self.assertEqual(constructs["Negative Sentiment"], 0.1)

    def test_arbitrary_speaker_and_country_labels_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_text_summary(
                root / "multimodal" / "speaker_level_summary.csv",
                [("Lab cohort", "Researcher Alpha", "lab/researcher-alpha", 1, 2, 3, 0.2, 0.1, 0, 0, 0)],
                CANONICAL_HEADERS,
            )

            summary = discover_text_results(root).summaries[0]

        self.assertEqual(summary.speaker_id, "researcheralpha")
        self.assertEqual(summary.display_name, "Researcher Alpha")
        self.assertEqual(summary.country, "Lab cohort")

    def test_rejects_duplicate_speakers_and_values_outside_contract_range(self) -> None:
        scenarios = (
            (
                "duplicate",
                [
                    ("UK", "Andy Burnham", "UK/Andy Burnham", 5, 20, 100, 0.2, 0.1, 0.3, 0.4, 0.5),
                    ("UK", "Andy Burnham", "UK/Andy Burnham", 5, 20, 100, 0.2, 0.1, 0.3, 0.4, 0.5),
                ],
            ),
            (
                "range",
                [("UK", "Andy Burnham", "UK/Andy Burnham", 5, 20, 100, 1.2, 0.1, 0.3, 0.4, 0.5)],
            ),
        )
        for label, rows in scenarios:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                write_text_summary(root / "multimodal" / "speaker_level_summary.csv", rows)
                with self.assertRaises(TextResultsError):
                    discover_text_results(root)

    def test_sentiment_and_dimension_ranges_are_validated_independently(self) -> None:
        scenarios = (
            ("sentiment", (1.01, 0, 0, 0, 0)),
            ("dimension", (1, 0, -1.01, 0, 0)),
        )
        for label, values in scenarios:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                write_text_summary(
                    root / "multimodal" / "speaker_level_summary.csv",
                    [("UK", "Andy Burnham", "UK/Andy Burnham", 5, 20, 100, *values)],
                    CANONICAL_HEADERS,
                )
                with self.assertRaises(TextResultsError):
                    discover_text_results(root)


if __name__ == "__main__":
    unittest.main()
