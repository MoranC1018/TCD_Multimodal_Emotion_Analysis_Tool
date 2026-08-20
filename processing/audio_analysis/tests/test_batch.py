import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio_pipeline.batch import discover_videos, run_batch, write_manifest_csv


class AvailableEmotionModels:
    skipped = False
    device = "cpu"
    errors: list[str] = []
    categorical_available = True
    dimensional_available = True


class BatchPipelineTests(unittest.TestCase):
    def test_batch_manifest_neutralizes_user_controlled_paths_and_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.csv"
            write_manifest_csv(
                path,
                [
                    {
                        "status": "failed",
                        "speaker": "@speaker",
                        "input_video": "=video.mp4",
                        "error": "+error",
                    }
                ],
            )
            with path.open(encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))

        self.assertEqual(row["speaker"], "'@speaker")
        self.assertEqual(row["input_video"], "'=video.mp4")
        self.assertEqual(row["error"], "'+error")

    def test_discovery_uses_stitched_videos_and_preserves_relative_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "downloads"
            stitched = root / "Speaker_A" / "Video_One" / "stitched_imotions.mp4"
            raw_clip = root / "Speaker_A" / "Video_One" / "raw_clips" / "001.mp4"
            other_stitched = root / "Speaker_B" / "Video_Two" / "stitched_imotions.mp4"
            for path in (stitched, raw_clip, other_stitched):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"mp4")

            jobs = discover_videos(root)

        self.assertEqual([job.relative_output_dir for job in jobs], [Path("Speaker_A/Video_One"), Path("Speaker_B/Video_Two")])
        self.assertEqual([job.input_video.name for job in jobs], ["stitched_imotions.mp4", "stitched_imotions.mp4"])

    def test_discovery_includes_full_video_mp4s_in_mixed_procurement_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "downloads"
            stitched = root / "Speaker_A" / "Video_One" / "stitched_imotions.mp4"
            raw_clip = root / "Speaker_A" / "Video_One" / "raw_clips" / "001.mp4"
            full_video = root / "Speaker_CC" / "Video_CC" / "_full_video" / "Creative_Commons_[cc001].mp4"
            for path in (stitched, raw_clip, full_video):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"mp4")

            jobs = discover_videos(root)

        self.assertEqual(
            [job.relative_output_dir for job in jobs],
            [Path("Speaker_A/Video_One"), Path("Speaker_CC/Video_CC/_full_video/Creative_Commons_[cc001]")],
        )
        self.assertEqual([job.input_video.name for job in jobs], ["stitched_imotions.mp4", "Creative_Commons_[cc001].mp4"])

    def test_discovery_falls_back_to_mp4_files_when_no_stitched_outputs_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "marine_test_videos"
            first = root / "001_marine.mp4"
            second = root / "nested" / "002_marine.mp4"
            for path in (first, second):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"mp4")

            jobs = discover_videos(root)

        self.assertEqual([job.relative_output_dir for job in jobs], [Path("001_marine"), Path("nested/002_marine")])
        self.assertEqual([job.input_video.name for job in jobs], ["001_marine.mp4", "002_marine.mp4"])

    def test_batch_writes_manifest_and_mirrors_input_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloads = root / "downloads"
            output = root / "audio_output"
            stale_csv = output / "Old_Speaker" / "Old_Video" / "audio_analysis.csv"
            stale_csv.parent.mkdir(parents=True)
            stale_csv.write_text("stale", encoding="utf-8")
            video = downloads / "Speaker_A" / "Video_One" / "stitched_imotions.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"mp4")
            loaded_models = AvailableEmotionModels()
            passed_models = []

            def fake_run(input_video: Path, output_dir: Path, **_kwargs):
                passed_models.append(_kwargs["emotion_models"])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "audio_analysis.csv").write_text("WindowIndex,PredictedEmotion\n1,Neutral\n", encoding="utf-8")
                (output_dir / "opensmile_features.csv").write_text("raw\n", encoding="utf-8")
                (output_dir / "audio_analysis_manifest.json").write_text("{}", encoding="utf-8")
                return type(
                    "Result",
                    (),
                    {
                        "output_dir": output_dir,
                        "audio_analysis_csv": output_dir / "audio_analysis.csv",
                        "opensmile_csv": output_dir / "opensmile_features.csv",
                        "manifest_path": output_dir / "audio_analysis_manifest.json",
                        "window_count": 1,
                    },
                )()

            with (
                patch("audio_pipeline.batch.EmotionModelBundle.load", return_value=loaded_models) as load_models,
                patch("audio_pipeline.batch.run_single_video", side_effect=fake_run),
            ):
                messages = []
                result = run_batch(downloads, output, progress=messages.append)

            mirrored = output / "Speaker_A" / "Video_One" / "audio_analysis.csv"
            manifest = output / "audio_analysis_manifest.csv"

            self.assertTrue(mirrored.exists())
            self.assertTrue(stale_csv.exists())
            self.assertTrue(manifest.exists())
            self.assertEqual(result.processed_count, 1)
            self.assertEqual(result.failed_count, 0)
            load_models.assert_called_once()
            self.assertEqual(passed_models, [loaded_models])
            self.assertIn("Scanning for analysis .mp4 files.", messages)
            self.assertIn("Batch complete: 1 processed, 0 failed.", messages)
            self.assertIn("Batch complete: 1 processed, 0 failed.", (output / "run_log.txt").read_text(encoding="utf-8-sig"))

    def test_batch_exports_for_full_stack_deployment_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloads = root / "procurement" / "output" / "Run_One" / "downloads"
            output = root / "audio_output"
            video = downloads / "Speaker_A" / "Video_One" / "stitched_imotions.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"mp4")

            def fake_run(input_video: Path, output_dir: Path, **_kwargs):
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "audio_analysis.csv").write_text("WindowIndex,PredictedEmotion\n1,Neutral\n", encoding="utf-8")
                (output_dir / "opensmile_features.csv").write_text("raw\n", encoding="utf-8")
                (output_dir / "audio_analysis_manifest.json").write_text("{}", encoding="utf-8")
                return type(
                    "Result",
                    (),
                    {
                        "output_dir": output_dir,
                        "audio_analysis_csv": output_dir / "audio_analysis.csv",
                        "opensmile_csv": output_dir / "opensmile_features.csv",
                        "manifest_path": output_dir / "audio_analysis_manifest.json",
                        "window_count": 1,
                    },
                )()

            with (
                patch("audio_pipeline.batch.config.Full_Stack_Deployment", True),
                patch("audio_pipeline.batch.EmotionModelBundle.load", return_value=AvailableEmotionModels()),
                patch("audio_pipeline.batch.run_single_video", side_effect=fake_run),
                patch("audio_pipeline.batch.export_batch_to_analysis_audio_outputs") as export_outputs,
            ):
                run_batch(downloads, output)

            export_outputs.assert_called_once()
            self.assertEqual(export_outputs.call_args.kwargs["run_name"], "Run_One")


if __name__ == "__main__":
    unittest.main()
