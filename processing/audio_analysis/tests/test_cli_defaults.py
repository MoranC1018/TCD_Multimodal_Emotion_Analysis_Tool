import tempfile
import unittest
import os
from pathlib import Path

from audio_pipeline.cli import default_batch_input_folder, default_batch_output_root, default_single_output_dir


class CliDefaultOutputTests(unittest.TestCase):
    def test_default_batch_output_root_is_project_output_folder(self):
        self.assertEqual(default_batch_output_root().name, "output")

    def test_default_batch_input_folder_uses_latest_procurement_downloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "procurement" / "output" / "Run_20260520_100000" / "downloads"
            newer = root / "procurement" / "output" / "Run_20260520_110000" / "downloads"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            os.utime(older.parent, (1, 1))
            os.utime(newer.parent, (2, 2))

            self.assertEqual(default_batch_input_folder(root), newer)

    def test_single_video_from_downloads_tree_uses_matching_relative_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = (
                Path(temp_dir)
                / "procurement"
                / "output"
                / "Run_One"
                / "downloads"
                / "Speaker_A"
                / "Video_One"
                / "stitched_imotions.mp4"
            )

            self.assertEqual(default_single_output_dir(video), default_batch_output_root() / "Speaker_A" / "Video_One")

    def test_single_video_outside_downloads_uses_video_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "clip.mp4"

            self.assertEqual(default_single_output_dir(video), default_batch_output_root() / "clip")


if __name__ == "__main__":
    unittest.main()
