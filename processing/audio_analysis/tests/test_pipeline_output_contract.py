import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio_pipeline.emotion_models import SkippedEmotionModels
from audio_pipeline.pipeline import run_single_video


class PipelineOutputContractTests(unittest.TestCase):
    def test_single_video_outputs_are_clean_pipeline_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_video = root / "stitched_imotions.mp4"
            input_video.write_bytes(b"mp4")

            def fake_extract(_input_video, output_wav, sample_rate=16000):
                output_wav.parent.mkdir(parents=True, exist_ok=True)
                output_wav.write_bytes(b"wav")
                return output_wav

            def fake_opensmile(_source_wav, _windows, output_csv, feature_set="egemaps"):
                output_csv.parent.mkdir(parents=True, exist_ok=True)
                output_csv.write_text(
                    "Row;WindowStart;WindowEnd;loudness_sma3_amean;F0semitoneFrom27.5Hz_sma3nz_amean;spectralFlux_sma3_amean\n"
                    "1;0;10;0.5;40;0.02\n",
                    encoding="utf-8",
                )
                return output_csv

            with (
                patch("audio_pipeline.pipeline.extract_mono_wav", side_effect=fake_extract),
                patch("audio_pipeline.pipeline.probe_duration_seconds", return_value=10.0),
                patch("audio_pipeline.pipeline.run_opensmile_windows", side_effect=fake_opensmile),
            ):
                messages = []
                result = run_single_video(input_video, root / "out", emotion_models=SkippedEmotionModels(), progress=messages.append)

            self.assertEqual(result.audio_analysis_csv.name, "audio_analysis.csv")
            self.assertEqual(result.opensmile_csv.name, "opensmile_features.csv")
            self.assertTrue(result.manifest_path.exists())
            self.assertFalse((root / "out" / "technical").exists())
            self.assertFalse((root / "out" / "START_HERE.txt").exists())
            self.assertIn("Extracting mono audio with ffmpeg.", messages)
            self.assertIn("Finished video.", messages)
            self.assertIn("Writing per-window model output table.", messages)


if __name__ == "__main__":
    unittest.main()
