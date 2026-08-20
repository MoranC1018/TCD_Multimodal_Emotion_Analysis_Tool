from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from analysis.audio import (
    ConvertedAudioRowSequence,
    PlainCsvRowSequence,
    analyse_audio_folder,
    missing_audio_analysis_message,
    read_audio_analysis_export,
    read_opensmile_features_export,
)


def write_compact_audio_csv(path: Path, speaker: str, title: str, youtube_id: str, emotion: str = "Neutral") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["#INFO"])
        writer.writerow(["#SpeakerName", speaker])
        writer.writerow(["#VideoTitle", title])
        writer.writerow(["#YoutubeID", youtube_id])
        writer.writerow(["#DATA"])
        writer.writerow(
            [
                "WindowIndex",
                "StartSeconds",
                "EndSeconds",
                "PredictedEmotion",
                "EmotionConfidence",
                "Anger",
                "Contempt",
                "Disgust",
                "Fear",
                "Happiness",
                "Neutral",
                "Sadness",
                "Surprise",
                "Other",
                "Arousal",
                "Dominance",
                "Valence",
            ]
        )
        writer.writerow(["1", "0", "10", emotion, "0.7", "0.1", "0.02", "0.03", "0.04", "0.2", "0.7", "0.05", "0.06", "0.01", "0.55", "0.45", "0.75"])


def write_opensmile_features_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Row", "WindowStart", "WindowEnd", "loudness_sma3_amean", "F0semitoneFrom27.5Hz_sma3nz_amean"])
        writer.writerow(["1", "0", "10", "0.25", "31.2"])
        writer.writerow(["2", "10", "20", "0.75", "34.8"])


class AudioAnalysisTests(unittest.TestCase):
    def test_audio_analysis_csv_is_converted_to_imotions_shaped_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Speaker_A" / "Video_One_[abc123]" / "audio_analysis.csv"
            path.parent.mkdir(parents=True)
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "SourceFile",
                        "SpeakerName",
                        "VideoTitle",
                        "YoutubeID",
                        "WindowIndex",
                        "StartSeconds",
                        "EndSeconds",
                        "DurationSeconds",
                        "PredictedEmotion",
                        "EmotionConfidence",
                        "Anger",
                        "Contempt",
                        "Disgust",
                        "Fear",
                        "Happiness",
                        "Neutral",
                        "Sadness",
                        "Surprise",
                        "Other",
                        "Arousal",
                        "Dominance",
                        "Valence",
                        "ModelCategoricalName",
                        "ModelCategoricalVersion",
                        "ModelDimensionalName",
                        "ModelDimensionalVersion",
                        "OpenSMILEFeatureSet",
                        "WindowSeconds",
                        "StrideSeconds",
                    ]
                )
                writer.writerow(
                    [
                        "video.mp4",
                        "Speaker A",
                        "Video One",
                        "abc123",
                        "1",
                        "5",
                        "15",
                        "10",
                        "Neutral",
                        "0.7",
                        "0.1",
                        "0.02",
                        "0.03",
                        "0.04",
                        "0.2",
                        "0.7",
                        "0.05",
                        "0.06",
                        "0.01",
                        "0.55",
                        "0.45",
                        "0.75",
                        "categorical-model",
                        "main",
                        "dimensional-model",
                        "main",
                        "egemaps",
                        "10",
                        "5",
                    ]
                )

            export = read_audio_analysis_export(path)

            self.assertEqual(export.source, "Speaker_A__Video_One_[abc123]")
            self.assertEqual(export.header[:2], ["Row", "Timestamp"])
            self.assertEqual(export.rows[0]["Row"], "1")
            self.assertEqual(export.rows[0]["Timestamp"], "5000")
            self.assertEqual(export.rows[0]["Joy"], "20")
            self.assertEqual(export.rows[0]["Neutral"], "70")
            self.assertEqual(export.rows[0]["Valence"], "50")
            self.assertEqual(export.info["Joy"].category, "AUDIO(Categorical Emotion)")
            self.assertEqual(export.info["Valence"].category, "AUDIO(Dimensional Affect)")
            self.assertIsInstance(export.rows, ConvertedAudioRowSequence)
            self.assertIsInstance(export.rows.source_rows, PlainCsvRowSequence)

    def test_audio_dimensional_values_and_scale_contracts_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Speaker_A" / "Video_One_[abc123]" / "audio_analysis.csv"
            write_compact_audio_csv(path, "Speaker A", "Video One", "abc123")

            export = read_audio_analysis_export(path)

            self.assertEqual(export.rows[0]["Arousal"], "55")
            self.assertEqual(export.rows[0]["Dominance"], "45")
            self.assertEqual(export.rows[0]["Valence"], "50")
            self.assertEqual(export.info["Arousal"].scale_hint, "0_to_100")
            self.assertEqual(export.info["Dominance"].scale_hint, "0_to_100")
            self.assertEqual(export.info["Valence"].scale_hint, "minus100_to_100")
            self.assertEqual(
                export.info["Arousal"].description,
                "Audio model probability for Arousal, scaled from source 0-1 to output 0-100.",
            )
            self.assertEqual(
                export.info["Dominance"].description,
                "Audio model probability for Dominance, scaled from source 0-1 to output 0-100.",
            )
            self.assertEqual(
                export.info["Valence"].description,
                "Audio model value for Valence, scaled from source 0-1 to output -100 to 100.",
            )

    def test_compact_audio_analysis_csv_metadata_is_used_for_source_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Speaker_A" / "Video_One_[abc123]" / "audio_analysis.csv"
            path.parent.mkdir(parents=True)
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["#INFO"])
                writer.writerow(["#SpeakerName", "Speaker A"])
                writer.writerow(["#VideoTitle", "Video One"])
                writer.writerow(["#YoutubeID", "abc123"])
                writer.writerow(["#WindowSeconds", "10"])
                writer.writerow(["#StrideSeconds", "5"])
                writer.writerow(["#DATA"])
                writer.writerow(
                    [
                        "WindowIndex",
                        "StartSeconds",
                        "EndSeconds",
                        "PredictedEmotion",
                        "EmotionConfidence",
                        "Anger",
                        "Contempt",
                        "Disgust",
                        "Fear",
                        "Happiness",
                        "Neutral",
                        "Sadness",
                        "Surprise",
                        "Other",
                        "Arousal",
                        "Dominance",
                        "Valence",
                    ]
                )
                writer.writerow(["1", "5", "15", "Neutral", "0.7", "0.1", "", "", "", "0.2", "0.7", "", "", "", "0.55", "0.45", "0.75"])

            export = read_audio_analysis_export(path)

            self.assertEqual(export.source, "Speaker_A__Video_One_[abc123]")
            self.assertEqual(export.rows[0]["Timestamp"], "5000")
            self.assertEqual(export.rows[0]["Contempt"], "")
            self.assertEqual(export.rows[0]["Neutral"], "70")
            self.assertEqual(export.rows[0]["Valence"], "50")

    def test_audio_folder_writes_source_run_speaker_video_and_combined_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "audio_run"
            output_root = Path(temp_dir) / "output"
            write_compact_audio_csv(input_dir / "Speaker_A" / "Video_One_[abc123]" / "audio_analysis.csv", "Speaker A", "Video One", "abc123", "Happiness")
            write_opensmile_features_csv(input_dir / "Speaker_A" / "Video_One_[abc123]" / "opensmile_features.csv")
            write_compact_audio_csv(input_dir / "Speaker_A" / "Video_Two_[def456]" / "audio_analysis.csv", "Speaker A", "Video Two", "def456", "Neutral")
            write_compact_audio_csv(input_dir / "Speaker_B" / "Video_Three_[ghi789]" / "audio_analysis.csv", "Speaker B", "Video Three", "ghi789", "Fear")

            result = analyse_audio_folder(input_dir, output_root=output_root, write_graphs=False)

            run_dir = output_root / "emotion" / "audio_run"
            raw_run_dir = output_root / "raw" / "audio_run"
            speaker_a = run_dir / "Speaker_A"
            speaker_b = run_dir / "Speaker_B"

            self.assertEqual(result.output_dir, run_dir.resolve())
            self.assertEqual(result.domain_output_dirs["raw"], raw_run_dir.resolve())
            self.assertTrue((speaker_a / "Video_One_[abc123]" / "histograms.csv").exists())
            self.assertTrue((speaker_a / "Video_Two_[def456]" / "histograms.csv").exists())
            self.assertTrue((speaker_a / "combined" / "histograms.csv").exists())
            self.assertTrue((speaker_b / "Video_Three_[ghi789]" / "histograms.csv").exists())
            self.assertTrue((speaker_b / "combined" / "histograms.csv").exists())
            self.assertTrue((raw_run_dir / "Speaker_A" / "Video_One_[abc123]" / "histograms.csv").exists())
            self.assertTrue((raw_run_dir / "Speaker_A" / "Video_One_[abc123]_opensmile_features" / "histograms.csv").exists())
            self.assertFalse((run_dir / "Speaker_A" / "Video_One_[abc123]_opensmile_features").exists())

            histogram_text = (speaker_a / "combined" / "histograms.csv").read_text(encoding="utf-8")
            self.assertIn("Core emotions (0-100)", histogram_text)
            self.assertIn("Joy", histogram_text)
            self.assertIn("Anger\nbin_start,bin_end,Video_One_[abc123],Video_Two_[def456],total", histogram_text)
            self.assertNotIn("Video_Three_[ghi789]", histogram_text)
            manifest_text = (speaker_a / "combined" / "other_findings" / "column_manifest.csv").read_text(encoding="utf-8")
            self.assertIn("provided_by", manifest_text.splitlines()[0])
            self.assertIn("scale_hint", manifest_text.splitlines()[0])

            raw_descriptor_text = (
                raw_run_dir / "Speaker_A" / "Video_One_[abc123]_opensmile_features" / "other_findings" / "descriptive_statistics.csv"
            ).read_text(encoding="utf-8")
            self.assertIn("loudness_sma3_amean", raw_descriptor_text)
            self.assertIn("F0semitoneFrom27.5Hz_sma3nz_amean", raw_descriptor_text)
            self.assertIn("kurtosis", raw_descriptor_text)

    def test_opensmile_features_export_uses_raw_acoustic_column_info(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Speaker_A" / "Video_One_[abc123]" / "opensmile_features.csv"
            write_opensmile_features_csv(path)

            export = read_opensmile_features_export(path)

        self.assertEqual(export.source, "Speaker_A__Video_One_[abc123]__opensmile_features")
        self.assertEqual(export.header, ["loudness_sma3_amean", "F0semitoneFrom27.5Hz_sma3nz_amean"])
        self.assertEqual(export.info["loudness_sma3_amean"].category, "AUDIO(OpenSMILE Feature)")
        self.assertEqual(export.info["loudness_sma3_amean"].scale_hint, "raw_acoustic")

    def test_audio_analysis_does_not_double_scale_small_already_scaled_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "audio_run"
            output_root = Path(temp_dir) / "output"
            path = input_dir / "Speaker_A" / "Video_One_[abc123]" / "audio_analysis.csv"
            path.parent.mkdir(parents=True)
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["#INFO"])
                writer.writerow(["#SpeakerName", "Speaker A"])
                writer.writerow(["#VideoTitle", "Video One"])
                writer.writerow(["#YoutubeID", "abc123"])
                writer.writerow(["#DATA"])
                writer.writerow(
                    [
                        "WindowIndex",
                        "StartSeconds",
                        "EndSeconds",
                        "PredictedEmotion",
                        "EmotionConfidence",
                        "Anger",
                        "Contempt",
                        "Disgust",
                        "Fear",
                        "Happiness",
                        "Neutral",
                        "Sadness",
                        "Surprise",
                        "Other",
                        "Arousal",
                        "Dominance",
                        "Valence",
                    ]
                )
                writer.writerow(["1", "0", "10", "Neutral", "0.9", "0.004", "", "", "", "", "0.9", "", "", "0.005", "0.006", "0.5", "0.505"])

            result = analyse_audio_folder(input_dir, output_root=output_root, write_graphs=False)
            histogram_text = (
                result.output_dir / "Speaker_A" / "Video_One_[abc123]" / "histograms.csv"
            ).read_text(encoding="utf-8")

        self.assertRegex(histogram_text, r"Other\nbin_start,bin_end,Video_One_\[abc123\],total\n0,5,1,1")
        self.assertRegex(histogram_text, r"Arousal\nbin_start,bin_end,Video_One_\[abc123\],total\n0,5,1,1")
        self.assertRegex(histogram_text, r"Valence\nbin_start,bin_end,Video_One_\[abc123\],total\n-100,-95,0,0")
        self.assertIn("0,5,1,1", histogram_text)

    def test_missing_audio_analysis_message_explains_manifest_without_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "audio_run"
            input_dir.mkdir()
            (input_dir / "audio_analysis_manifest.csv").write_text("status\nok\n", encoding="utf-8")

            message = missing_audio_analysis_message(input_dir)

        self.assertIn("batch manifest exists", message)
        self.assertIn("per-video audio output files are missing", message)


if __name__ == "__main__":
    unittest.main()
