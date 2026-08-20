from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from application import manual_segments


class ManualSegmentsTests(unittest.TestCase):
    def test_main_rejects_expected_source_that_does_not_match_cli_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            other_source = root / "other.mp4"
            source.write_bytes(b"video")
            other_source.write_bytes(b"other video")
            manifest = root / "focus.json"
            manifest.write_text(
                json.dumps(
                    {
                        "source_path": str(other_source),
                        "processing_source_path": str(other_source),
                        "selected_segments": [],
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                source=source,
                output_root=root / "output",
                segments_json=manifest,
                manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                expected_source=str(other_source),
            )

            with patch.object(manual_segments, "parse_args", return_value=args), self.assertRaisesRegex(
                ValueError,
                "source identity does not match",
            ):
                manual_segments.main()

    def test_focus_manifest_rejects_replacement_after_launcher_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            manifest = root / "focus.json"
            original = {
                "source_path": str(source),
                "selected_segments": [
                    {
                        "source_kind": "file",
                        "source_path": str(source),
                        "start_seconds": 0,
                        "end_seconds": 1,
                    }
                ],
            }
            original_bytes = (json.dumps(original, indent=2) + "\n").encode("utf-8")
            expected_sha256 = hashlib.sha256(original_bytes).hexdigest()
            manifest.write_bytes(original_bytes)
            manifest.write_text(
                json.dumps(
                    {
                        "source_path": str(root / "attacker.docx"),
                        "selected_segments": [
                            {
                                "source_kind": "docx",
                                "source_path": str(root / "attacker.docx"),
                                "video_id": "aaaaaaaaaaa",
                                "youtube_url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "digest does not match"):
                manual_segments.load_focus_manifest(
                    manifest,
                    expected_sha256=expected_sha256,
                    expected_source=str(source),
                )

    def test_main_rejects_oversized_focus_control_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "clip.mp4"
            source.write_bytes(b"video")
            manifest = root / "focus.json"
            manifest.write_text('{"padding":"' + ("x" * (1024 * 1024)) + '"}', encoding="utf-8")
            args = argparse.Namespace(
                source=source,
                output_root=root / "output",
                segments_json=manifest,
                manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                expected_source=str(source),
            )

            with patch.object(manual_segments, "parse_args", return_value=args), self.assertRaisesRegex(
                ValueError,
                "Focus manifest JSON exceeds",
            ):
                manual_segments.main()

    def test_main_rejects_excessive_focus_segment_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "clip.mp4"
            source.write_bytes(b"video")
            manifest = root / "focus.json"
            manifest.write_text(
                json.dumps({"source_path": str(source), "selected_segments": [{}] * 10001}),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                source=source,
                output_root=root / "output",
                segments_json=manifest,
                manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                expected_source=str(source),
            )

            with patch.object(manual_segments, "parse_args", return_value=args), self.assertRaisesRegex(
                ValueError,
                "at most 10000",
            ):
                manual_segments.main()
    def test_docx_focus_selection_uses_youtube_even_when_docx_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "videos.docx"
            source.write_bytes(b"docx placeholder")
            payload = {
                "selected_segments": [
                    {
                        "source_path": str(source),
                        "source_kind": "docx",
                        "youtube_url": "https://www.youtube.com/watch?v=abcdefghijk",
                        "start_seconds": 0,
                        "end_seconds": 10,
                    }
                ]
            }

            with (
                patch.object(manual_segments, "process_one_video") as process_local,
                patch.object(manual_segments, "process_one_youtube_video") as process_youtube,
            ):
                result = manual_segments.process_local_segments(source, root / "output", payload)

        process_local.assert_not_called()
        process_youtube.assert_called_once()
        self.assertEqual(result, {"processed": 1, "recorded_only": 0, "failed": 0})

    def test_docx_focus_selection_rejects_an_arbitrary_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source_catalog.docx"
            source.write_bytes(b"docx placeholder")
            unrelated = root / "unrelated.mp4"
            unrelated.write_bytes(b"video placeholder")
            payload = {
                "source_path": str(source),
                "selected_segments": [
                    {
                        "source_path": str(unrelated),
                        "source_kind": "docx",
                        "youtube_url": "https://www.youtube.com/watch?v=abcdefghijk",
                        "start_seconds": 0,
                        "end_seconds": 10,
                    }
                ],
            }

            with (
                patch.object(manual_segments, "process_one_video") as process_local,
                patch.object(manual_segments, "process_one_youtube_video") as process_youtube,
            ):
                result = manual_segments.process_local_segments(source, root / "output", payload)

        process_local.assert_not_called()
        process_youtube.assert_not_called()
        self.assertEqual(result, {"processed": 0, "recorded_only": 0, "failed": 1})

    def test_focus_processor_rejects_blank_and_unknown_source_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "clip.mp4"
            source.write_bytes(b"video placeholder")
            for source_kind in ("", "archive"):
                payload = {
                    "source_path": str(source),
                    "selected_segments": [
                        {
                            "source_path": str(source),
                            "source_kind": source_kind,
                            "youtube_url": "https://www.youtube.com/watch?v=abcdefghijk",
                            "start_seconds": 0,
                            "end_seconds": 10,
                        }
                    ],
                }
                with self.subTest(source_kind=source_kind):
                    with (
                        patch.object(manual_segments, "process_one_video") as process_local,
                        patch.object(manual_segments, "process_one_youtube_video") as process_youtube,
                    ):
                        result = manual_segments.process_local_segments(source, root / "output", payload)
                        process_local.assert_not_called()
                        process_youtube.assert_not_called()
                        self.assertEqual(result, {"processed": 0, "recorded_only": 0, "failed": 1})

    def test_build_youtube_segment_command_downloads_only_time_range(self) -> None:
        command = manual_segments.build_youtube_segment_command(
            youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
            start=12.5,
            end=42.5,
            target=Path(r"C:\out\segment_001.mp4"),
            python_executable=Path(sys.executable),
            ffmpeg_binary=Path(r"C:\trusted-tools\ffmpeg.exe"),
        )

        self.assertEqual(command[:5], [str(Path(sys.executable).resolve()), "-E", "-P", "-m", "yt_dlp"])
        self.assertEqual(
            command[command.index("--ffmpeg-location") + 1],
            r"C:\trusted-tools\ffmpeg.exe",
        )
        self.assertIn("--download-sections", command)
        self.assertIn("*00:00:12.500-00:00:42.500", command)
        self.assertIn("--force-keyframes-at-cuts", command)
        self.assertIn("https://www.youtube.com/watch?v=abcdefghijk", command)

    def test_interleave_gap_file_places_one_gap_between_each_segment(self) -> None:
        clips = [Path("one.mp4"), Path("two.mp4"), Path("three.mp4")]
        gap = Path("gap.mp4")

        result = manual_segments.interleave_gap_file(clips, gap)

        self.assertEqual(result, [clips[0], gap, clips[1], gap, clips[2]])

    def test_add_focus_gap_clips_is_noop_when_gap_is_zero(self) -> None:
        clips = [Path("one.mp4"), Path("two.mp4")]

        result = manual_segments.add_focus_gap_clips(Path("output"), clips, 0)

        self.assertEqual(result, clips)

    def test_parse_frame_rate_supports_fractional_ffprobe_values(self) -> None:
        self.assertAlmostEqual(manual_segments.parse_frame_rate("30000/1001"), 29.97002997)
        self.assertEqual(manual_segments.parse_frame_rate("invalid"), 25.0)

    def test_target_relative_stem_supports_single_video_source(self) -> None:
        source = Path(r"C:\videos\speech.mp4")

        self.assertEqual(manual_segments.target_relative_stem(source, source), Path("speech"))


if __name__ == "__main__":
    unittest.main()
