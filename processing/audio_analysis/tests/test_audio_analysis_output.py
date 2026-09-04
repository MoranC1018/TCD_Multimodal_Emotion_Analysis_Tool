import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio_pipeline.emotion_models import EMOTION_COLUMNS, FALLBACK_CATEGORICAL_MODEL_NAME, EmotionModelResult
from audio_pipeline.audio_analysis_csv import write_audio_analysis_csv
from audio_pipeline.pipeline import run_single_video


def read_audio_analysis_csv(path: Path) -> tuple[dict[str, str], list[dict[str, str]], list[str]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    data_index = lines.index("#DATA")
    metadata: dict[str, str] = {}
    for line in lines[:data_index]:
        if line.startswith("#") and "," in line:
            key, value = line.split(",", 1)
            metadata[key.lstrip("#")] = value
    reader = csv.DictReader(lines[data_index + 1 :])
    return metadata, list(reader), reader.fieldnames or []


class FakeEmotionModels:
    categorical_model_name = "fake-categorical"
    categorical_model_version = "test"
    dimensional_model_name = "fake-dimensional"
    dimensional_model_version = "test"
    device = "cpu"
    skipped = False
    categorical_available = True
    dimensional_available = True
    errors = []

    def predict_window(self, _window_wav: Path) -> EmotionModelResult:
        return EmotionModelResult(
            probabilities={
                "Anger": 0.05,
                "Contempt": 0.02,
                "Disgust": 0.01,
                "Fear": 0.03,
                "Happiness": 0.70,
                "Neutral": 0.10,
                "Sadness": 0.04,
                "Surprise": 0.03,
                "Other": 0.02,
            },
            arousal=0.61,
            dominance=0.52,
            valence=0.73,
        )


class FakeUnavailableEmotionModels:
    categorical_model_name = "fake-categorical"
    categorical_model_version = "test"
    dimensional_model_name = "fake-dimensional"
    dimensional_model_version = "test"
    device = "cpu"
    skipped = False
    categorical_available = False
    dimensional_available = False
    errors = ["models unavailable"]

    def predict_window(self, _window_wav: Path) -> EmotionModelResult:
        raise AssertionError("Unavailable model layers should not be called")


class FakeFallbackEmotionModels:
    categorical_model_name = FALLBACK_CATEGORICAL_MODEL_NAME
    categorical_model_version = "debug"
    dimensional_model_name = ""
    dimensional_model_version = ""
    device = "cpu"
    skipped = False
    categorical_available = True
    dimensional_available = False
    errors = []

    def predict_window(self, _window_wav: Path) -> EmotionModelResult:
        return EmotionModelResult(
            probabilities={
                "Anger": 0.1,
                "Happiness": 0.8,
                "Neutral": 0.1,
            },
            arousal="",
            dominance="",
            valence="",
        )


class AudioAnalysisOutputTests(unittest.TestCase):
    def test_audio_csv_neutralizes_hostile_metadata_and_text_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "audio_analysis.csv"
            write_audio_analysis_csv(
                path,
                [{"WindowIndex": "1", "StartSeconds": "0", "PredictedEmotion": "+cmd"}],
                metadata={
                    "SourceFile": "=1+1",
                    "SpeakerName": "@speaker",
                    "VideoTitle": "\tvideo",
                    "YoutubeID": "ordinary",
                    "Note": "\rnote",
                },
            )
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))

        data_index = rows.index(["#DATA"])
        metadata = {row[0].lstrip("#"): row[1] for row in rows[1:data_index]}
        data = dict(zip(rows[data_index + 1], rows[data_index + 2]))
        self.assertEqual(metadata["SourceFile"], "'=1+1")
        self.assertEqual(metadata["SpeakerName"], "'@speaker")
        self.assertEqual(metadata["VideoTitle"], "'\tvideo")
        self.assertEqual(metadata["Note"], "'\rnote")
        self.assertEqual(metadata["YoutubeID"], "ordinary")
        self.assertEqual(data["PredictedEmotion"], "'+cmd")
        self.assertEqual(data["WindowIndex"], "1")

    def test_audio_analysis_csv_contains_model_outputs_not_interpretation_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_video = root / "downloads" / "Speaker_A" / "Video_Title_[abc123]" / "stitched_imotions.mp4"
            input_video.parent.mkdir(parents=True)
            input_video.write_bytes(b"mp4")

            def fake_extract(_input_video, output_wav, sample_rate=16000):
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"wav")
                return output_wav

            def fake_window_export(_source_wav, _window, output_wav):
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"window wav")
                return output_wav

            def fake_opensmile(_source_wav, _windows, output_csv, feature_set="egemaps"):
                output_csv.parent.mkdir(parents=True, exist_ok=True)
                output_csv.write_text(
                    "Row,WindowStart,WindowEnd,loudness_sma3_amean\n"
                    "1,0,10,0.5\n",
                    encoding="utf-8",
                )
                return output_csv

            with (
                patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=fake_extract),
                patch("audio_pipeline.pipeline.export_window_wav", side_effect=fake_window_export),
                patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=10.0),
                patch("audio_pipeline.pipeline.run_opensmile_windows", side_effect=fake_opensmile),
            ):
                result = run_single_video(input_video, root / "out", emotion_models=FakeEmotionModels())

            metadata, rows, header = read_audio_analysis_csv(result.audio_analysis_csv)

        self.assertEqual(len(rows), 1)
        self.assertNotIn("PlainEnglishSummary", header)
        self.assertNotIn("Activation", header)
        self.assertNotIn("Loudness", header)
        self.assertNotIn("Pitch", header)
        self.assertNotIn("VoiceStability", header)
        self.assertNotIn("SourceFile", header)
        self.assertNotIn("SpeakerName", header)
        self.assertNotIn("VideoTitle", header)
        self.assertNotIn("YoutubeID", header)
        self.assertNotIn("DurationSeconds", header)
        self.assertNotIn("WindowSeconds", header)
        self.assertNotIn("StrideSeconds", header)
        self.assertNotIn("ModelCategoricalName", header)
        for column in EMOTION_COLUMNS:
            self.assertIn(column, header)
        self.assertEqual(metadata["SpeakerName"], "Speaker_A")
        self.assertEqual(metadata["VideoTitle"], "Video_Title")
        self.assertEqual(metadata["YoutubeID"], "abc123")
        self.assertEqual(metadata["WindowSeconds"], "10")
        self.assertEqual(metadata["StrideSeconds"], "5")
        self.assertEqual(metadata["ModelCategoricalName"], "fake-categorical")
        self.assertEqual(metadata["CategoricalModelAvailable"], "true")
        self.assertEqual(metadata["DimensionalModelAvailable"], "true")
        self.assertEqual(metadata["EmotionModelsSkipped"], "false")
        self.assertEqual(metadata["ModelDevice"], "cpu")
        self.assertEqual(rows[0]["PredictedEmotion"], "Happiness")
        self.assertEqual(rows[0]["EmotionConfidence"], "0.7")
        self.assertEqual(rows[0]["Arousal"], "0.61")
        self.assertEqual(rows[0]["Dominance"], "0.52")
        self.assertEqual(rows[0]["Valence"], "0.73")

    def test_skip_emotion_models_keeps_schema_with_blank_model_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_video = root / "clip.mp4"
            input_video.write_bytes(b"mp4")

            def fake_extract(_input_video, output_wav, sample_rate=16000):
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"wav")
                return output_wav

            def fake_opensmile(_source_wav, _windows, output_csv, feature_set="egemaps"):
                output_csv.parent.mkdir(parents=True, exist_ok=True)
                output_csv.write_text("Row,WindowStart,WindowEnd\n1,0,5\n", encoding="utf-8")
                return output_csv

            with (
                patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=fake_extract),
                patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=5.0),
                patch("audio_pipeline.pipeline.run_opensmile_windows", side_effect=fake_opensmile),
            ):
                result = run_single_video(input_video, root / "out", skip_emotion_models=True)

            _metadata, rows, _header = read_audio_analysis_csv(result.audio_analysis_csv)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(rows[0]["PredictedEmotion"], "")
        self.assertEqual(rows[0]["Anger"], "")
        self.assertEqual(rows[0]["Arousal"], "")
        self.assertTrue(manifest["emotion_models_skipped"])
        self.assertEqual(manifest["audio_analysis_contents"], "per-window model outputs and probabilities")
        self.assertFalse(manifest["categorical_model_available"])
        self.assertFalse(manifest["dimensional_model_available"])
        self.assertEqual(manifest["model_errors"], [])

    def test_direct_stitched_video_does_not_invent_speaker_from_parent_folders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_video = root / "input" / "stitched_imotions.mp4"
            input_video.parent.mkdir(parents=True)
            input_video.write_bytes(b"mp4")

            def fake_extract(_input_video, output_wav, sample_rate=16000):
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"wav")
                return output_wav

            def fake_opensmile(_source_wav, _windows, output_csv, feature_set="egemaps"):
                output_csv.parent.mkdir(parents=True, exist_ok=True)
                output_csv.write_text("Row,WindowStart,WindowEnd\n1,0,5\n", encoding="utf-8")
                return output_csv

            with (
                patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=fake_extract),
                patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=5.0),
                patch("audio_pipeline.pipeline.run_opensmile_windows", side_effect=fake_opensmile),
            ):
                result = run_single_video(input_video, root / "out", skip_emotion_models=True)

            metadata, _rows, _header = read_audio_analysis_csv(result.audio_analysis_csv)

        self.assertEqual(metadata["SpeakerName"], "")
        self.assertEqual(metadata["VideoTitle"], "input")

    def test_non_stitched_downloads_mp4_keeps_speaker_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_video = root / "downloads" / "Speaker_CC" / "Video_CC_[cc001]" / "_full_video" / "Creative_Commons_[cc001].mp4"
            input_video.parent.mkdir(parents=True)
            input_video.write_bytes(b"mp4")

            def fake_extract(_input_video, output_wav, sample_rate=16000):
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"wav")
                return output_wav

            def fake_opensmile(_source_wav, _windows, output_csv, feature_set="egemaps"):
                output_csv.parent.mkdir(parents=True, exist_ok=True)
                output_csv.write_text("Row,WindowStart,WindowEnd\n1,0,5\n", encoding="utf-8")
                return output_csv

            with (
                patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=fake_extract),
                patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=5.0),
                patch("audio_pipeline.pipeline.run_opensmile_windows", side_effect=fake_opensmile),
            ):
                result = run_single_video(input_video, root / "out", skip_emotion_models=True)

            metadata, _rows, _header = read_audio_analysis_csv(result.audio_analysis_csv)

        self.assertEqual(metadata["SpeakerName"], "Speaker_CC")
        self.assertEqual(metadata["VideoTitle"], "Creative_Commons")
        self.assertEqual(metadata["YoutubeID"], "cc001")

    def test_unavailable_requested_emotion_models_fail_without_writing_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_video = root / "clip.mp4"
            input_video.write_bytes(b"mp4")

            def fake_extract(_input_video, output_wav, sample_rate=16000):
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"wav")
                return output_wav

            def fake_opensmile(_source_wav, _windows, output_csv, feature_set="egemaps"):
                output_csv.parent.mkdir(parents=True, exist_ok=True)
                output_csv.write_text("Row,WindowStart,WindowEnd\n1,0,5\n", encoding="utf-8")
                return output_csv

            messages = []
            with (
                patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=fake_extract),
                patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=5.0),
                patch("audio_pipeline.pipeline.run_opensmile_windows", side_effect=fake_opensmile),
                patch("audio_pipeline.pipeline.export_window_wav") as export_window,
            ):
                with self.assertRaisesRegex(RuntimeError, "model layer.*unavailable"):
                    run_single_video(
                        input_video,
                        root / "out",
                        emotion_models=FakeUnavailableEmotionModels(),
                        progress=messages.append,
                    )
            self.assertFalse((root / "out").exists())

        export_window.assert_not_called()

    def test_unsupported_emotion_columns_are_blank_not_zero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_video = root / "clip.mp4"
            input_video.write_bytes(b"mp4")

            class FourClassEmotionModels(FakeEmotionModels):
                categorical_model_name = "four-class"

                def predict_window(self, _window_wav: Path) -> EmotionModelResult:
                    return EmotionModelResult(
                        probabilities={
                            "Anger": 0.1,
                            "Happiness": 0.7,
                            "Neutral": 0.1,
                            "Sadness": 0.1,
                        },
                        arousal=0.5,
                        dominance=0.5,
                        valence=0.5,
                    )

            def fake_extract(_input_video, output_wav, sample_rate=16000):
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"wav")
                return output_wav

            def fake_window_export(_source_wav, _window, output_wav):
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"window wav")
                return output_wav

            def fake_opensmile(_source_wav, _windows, output_csv, feature_set="egemaps"):
                output_csv.parent.mkdir(parents=True, exist_ok=True)
                output_csv.write_text("Row,WindowStart,WindowEnd\n1,0,5\n", encoding="utf-8")
                return output_csv

            with (
                patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=fake_extract),
                patch("audio_pipeline.pipeline.export_window_wav", side_effect=fake_window_export),
                patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=5.0),
                patch("audio_pipeline.pipeline.run_opensmile_windows", side_effect=fake_opensmile),
            ):
                result = run_single_video(input_video, root / "out", emotion_models=FourClassEmotionModels())

            _metadata, rows, _header = read_audio_analysis_csv(result.audio_analysis_csv)

        self.assertEqual(rows[0]["Contempt"], "")
        self.assertEqual(rows[0]["Disgust"], "")
        self.assertEqual(rows[0]["Fear"], "")
        self.assertEqual(rows[0]["Surprise"], "")
        self.assertEqual(rows[0]["Other"], "")
        self.assertEqual(rows[0]["PredictedEmotion"], "Happiness")

    def test_debug_mode_writes_fallback_outputs_separately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_video = root / "clip.mp4"
            input_video.write_bytes(b"mp4")

            def fake_extract(_input_video, output_wav, sample_rate=16000):
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"wav")
                return output_wav

            def fake_window_export(_source_wav, _window, output_wav):
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"window wav")
                return output_wav

            def fake_opensmile(_source_wav, _windows, output_csv, feature_set="egemaps"):
                output_csv.parent.mkdir(parents=True, exist_ok=True)
                output_csv.write_text("Row,WindowStart,WindowEnd\n1,0,5\n", encoding="utf-8")
                return output_csv

            with (
                patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=fake_extract),
                patch("audio_pipeline.pipeline.export_window_wav", side_effect=fake_window_export),
                patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=5.0),
                patch("audio_pipeline.pipeline.run_opensmile_windows", side_effect=fake_opensmile),
                patch("audio_pipeline.pipeline.load_debug_fallback_emotion_models", create=True, return_value=FakeFallbackEmotionModels()),
            ):
                result = run_single_video(
                    input_video,
                    root / "out",
                    emotion_models=FakeEmotionModels(),
                    debug=True,
                )

            _main_metadata, main_rows, _main_header = read_audio_analysis_csv(result.audio_analysis_csv)
            debug_csv = result.output_dir / "debug" / "fallback_audio_analysis.csv"
            debug_exists = debug_csv.exists()
            debug_metadata, debug_rows, _debug_header = read_audio_analysis_csv(debug_csv)

        self.assertEqual(main_rows[0]["PredictedEmotion"], "Happiness")
        self.assertEqual(main_rows[0]["Anger"], "0.05")
        self.assertTrue(debug_exists)
        self.assertEqual(debug_metadata["ModelCategoricalName"], FALLBACK_CATEGORICAL_MODEL_NAME)
        self.assertEqual(debug_rows[0]["PredictedEmotion"], "Happiness")
        self.assertEqual(debug_rows[0]["Happiness"], "0.8")


if __name__ == "__main__":
    unittest.main()
