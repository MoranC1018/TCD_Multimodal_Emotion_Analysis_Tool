import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio_pipeline.emotion_models import SkippedEmotionModels
from audio_pipeline.pipeline import run_single_video


class PipelineSmokeTests(unittest.TestCase):
    def test_single_video_pipeline_writes_clean_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_video = root / "clip.mp4"
            input_video.write_bytes(b"fake mp4")
            stale_supporting = root / "out" / "supporting_models"
            stale_supporting.mkdir(parents=True)
            (stale_supporting / "model_emotion_scores.csv").write_text("stale", encoding="utf-8")

            def fake_extract(_input_video: Path, output_wav: Path, sample_rate: int = 16000) -> Path:
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"fake wav")
                return output_wav

            def fake_opensmile(source_wav, windows, output_csv, feature_set="egemaps"):
                output_csv.parent.mkdir(parents=True, exist_ok=True)
                output_csv.write_text(
                    "\n".join(
                        [
                            "Row;WindowStart;WindowEnd;loudness_sma3_amean;F0semitoneFrom27.5Hz_sma3nz_amean;spectralFlux_sma3_amean;jitterLocal_sma3nz_amean;shimmerLocaldB_sma3nz_amean;HNRdBACF_sma3nz_amean",
                            "1;0;10;0.2;30;0.01;0.02;0.10;20",
                            "2;2;12;0.8;45;0.09;0.04;0.20;12",
                        ]
                    ),
                    encoding="utf-8",
                )
                return output_csv

            with (
                patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=fake_extract),
                patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=12.0),
                patch("audio_pipeline.pipeline.run_opensmile_windows", side_effect=fake_opensmile),
            ):
                result = run_single_video(input_video, root / "out", emotion_models=SkippedEmotionModels())

            self.assertTrue(result.audio_analysis_csv.exists())
            self.assertTrue(result.opensmile_csv.exists())
            self.assertTrue(result.manifest_path.exists())
            self.assertFalse((result.output_dir / "supporting_models").exists())
            self.assertFalse((result.output_dir / "supporting_models" / "model_emotion_scores.csv").exists())

            with result.audio_analysis_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            header = rows[rows.index(["#DATA"]) + 1]

        self.assertIn("PredictedEmotion", header)
        self.assertIn("Anger", header)
        self.assertIn("Arousal", header)
        self.assertNotIn("Activation", header)
        self.assertNotIn("PlainEnglishSummary", header)


if __name__ == "__main__":
    unittest.main()
