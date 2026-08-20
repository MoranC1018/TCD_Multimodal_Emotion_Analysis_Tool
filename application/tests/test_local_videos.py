from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from application import local_videos


class LocalVideosTests(unittest.TestCase):
    def test_source_videos_accepts_one_supported_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "clip.mov"
            video.write_bytes(b"video")

            discovered = local_videos.source_videos(video)

        self.assertEqual(discovered, [video])

    def test_source_videos_rejects_empty_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "No supported videos"):
                local_videos.source_videos(Path(temp_dir))

    def test_source_videos_filters_first_level_speaker_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected = root / "Marine Le Pen" / "one.mp4"
            excluded = root / "Jordan Bardella" / "two.mp4"
            selected.parent.mkdir()
            excluded.parent.mkdir()
            selected.write_bytes(b"video")
            excluded.write_bytes(b"video")

            discovered = local_videos.source_videos(root, selected_speakers=["  marine   le pen "])

        self.assertEqual(discovered, [selected])

    def test_random_segments_are_deterministic_non_overlapping_and_exact(self) -> None:
        first = local_videos.random_segments(600.0, 120, 30, seed="video")
        second = local_videos.random_segments(600.0, 120, 30, seed="video")

        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(length for _start, length in first), 120.0)
        self.assertTrue(all(length <= 30 for _start, length in first))
        self.assertTrue(all(start >= 0 and start + length <= 600.000001 for start, length in first))
        ordered = sorted((start, start + length) for start, length in first)
        self.assertTrue(all(left[1] <= right[0] + 1e-9 for left, right in zip(ordered, ordered[1:])))

    def test_full_mode_processes_a_single_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "input" / "speaker.mp4"
            video.parent.mkdir()
            video.write_bytes(b"video-bytes")
            output_base = root / "outputs"
            args = argparse.Namespace(
                source=video,
                output_root=output_base,
                mode="full",
                percentage=0.10,
                max_segment_seconds=30,
            )

            with (
                patch.object(local_videos, "parse_args", return_value=args),
                patch.object(local_videos.backend, "read_duration_seconds", return_value=10.0),
                patch.object(
                    local_videos,
                    "create_full_video",
                    side_effect=lambda _source, target: target.write_bytes(b"canonical-video"),
                ),
            ):
                result = local_videos.main()

            run_folders = list(output_base.glob("speaker_local_full_*"))
            self.assertEqual(result, 0)
            self.assertEqual(len(run_folders), 1)
            copied = run_folders[0] / "speaker" / "stitched_imotions.mp4"
            self.assertEqual(copied.read_bytes(), b"canonical-video")
            manifest = json.loads((run_folders[0] / "local_procurement_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest), 1)
            self.assertEqual(manifest[0]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
