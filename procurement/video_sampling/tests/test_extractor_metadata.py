import json
import random
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from procurement.video_sampling import extractor


class FakeVideoInfoLogger:
    """Logger double that lets tests control metadata command outcomes."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.commands: list[list[str]] = []
        self.messages: list[str] = []

    def log(self, message: object = "") -> None:
        self.messages.append(str(message))

    def run_command_capture(self, command: list[str], timeout_seconds: int | None = None):
        self.commands.append(command)
        outcome = self.outcomes.pop(0)

        if isinstance(outcome, Exception):
            raise outcome

        return outcome


class ExtractorMetadataTests(unittest.TestCase):
    def test_network_boundaries_reject_non_youtube_url_before_runner(self):
        invalid = "https://youtube.com.attacker.example/watch?v=abcdefghijk"
        logger = FakeVideoInfoLogger([])
        with self.assertRaisesRegex(ValueError, "YouTube"):
            extractor.get_video_info(invalid, logger, info_timeout_seconds=30)
        self.assertEqual(logger.commands, [])

        with self.assertRaisesRegex(ValueError, "YouTube"):
            extractor.build_yt_dlp_segment_command(
                invalid,
                "00:00:00",
                "00:00:30",
                Path("clip.%(ext)s"),
                "best",
                720,
            )

    def test_segment_download_has_a_hard_file_size_ceiling(self):
        command = extractor.build_yt_dlp_segment_command(
            "https://www.youtube.com/watch?v=abcdefghijk",
            "00:00:00",
            "00:00:30",
            Path("clip.%(ext)s"),
            "best",
            720,
        )
        self.assertIn("--max-filesize", command)
        self.assertEqual(
            command[command.index("--max-filesize") + 1],
            str(extractor.DEFAULT_MAX_DOWNLOAD_BYTES),
        )
    def test_resolve_seed_records_cli_or_generated_source_and_seeds_random(self):
        with patch.object(extractor.random, "seed") as seed_mock:
            seed, seed_source = extractor.resolve_seed(2468)

        self.assertEqual(seed, 2468)
        self.assertEqual(seed_source, "cli")
        seed_mock.assert_called_once_with(2468)

        with patch.object(extractor.random, "randint", return_value=13579):
            with patch.object(extractor.random, "seed") as seed_mock:
                seed, seed_source = extractor.resolve_seed(None)

        self.assertEqual(seed, 13579)
        self.assertEqual(seed_source, "generated")
        seed_mock.assert_called_once_with(13579)

    def test_finalize_metadata_writes_no_stitch_completion_only_with_raw_clip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_folder = Path(temp_dir)
            raw_clip_folder = output_folder / extractor.RAW_CLIP_FOLDER_NAME
            raw_clip_folder.mkdir()
            raw_clip = raw_clip_folder / "001_00_00_00_30.mp4"
            raw_clip.write_bytes(b"clip")

            metadata = {
                "url": "https://www.youtube.com/watch?v=abc123",
                "video_id": "abc123",
                "title": "Example",
                "seed": 99,
                "seed_source": "cli",
                "selected_segments": [{"start": 0, "end": 30}],
                "skip_stitch": True,
                "skip_imotions_conversion": False,
                "output_files_created": [str(raw_clip)],
            }

            extractor.finalize_extraction_metadata(output_folder, metadata)

            metadata_path = output_folder / extractor.METADATA_FILE_NAME
            complete_path = output_folder / extractor.COMPLETION_FILE_NAME
            self.assertTrue(metadata_path.exists())
            self.assertTrue(complete_path.exists())

            saved_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            completion = json.loads(complete_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_metadata["status"], "success")
            self.assertEqual(completion["status"], "success")
            self.assertEqual(completion["seed_source"], "cli")

    def test_finalize_metadata_requires_stitched_video_for_stitched_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_folder = Path(temp_dir)
            metadata = {
                "url": "https://www.youtube.com/watch?v=abc123",
                "video_id": "abc123",
                "title": "Example",
                "seed": 99,
                "seed_source": "cli",
                "selected_segments": [{"start": 0, "end": 30}],
                "skip_stitch": False,
                "skip_imotions_conversion": False,
                "output_files_created": [],
            }

            with self.assertRaises(RuntimeError):
                extractor.finalize_extraction_metadata(output_folder, metadata)

            stitched = output_folder / extractor.STITCHED_VIDEO_NAME
            stitched.write_bytes(b"stitched")

            extractor.finalize_extraction_metadata(output_folder, metadata)

            self.assertTrue((output_folder / extractor.COMPLETION_FILE_NAME).exists())

    def test_get_video_info_retries_transient_yt_dlp_metadata_failure(self):
        failed_attempt = subprocess.CalledProcessError(
            returncode=1,
            cmd=["yt-dlp"],
            stderr="HTTP Error 429: Too Many Requests",
        )
        successful_attempt = subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=json.dumps({"title": "Retry Works", "duration": 123}),
        )
        logger = FakeVideoInfoLogger([failed_attempt, successful_attempt])

        with patch.object(extractor.time, "sleep") as sleep_mock:
            video_info = extractor.get_video_info(
                "https://www.youtube.com/watch?v=abcdefghijk",
                logger,
                info_timeout_seconds=30,
            )

        self.assertEqual(video_info, {"title": "Retry Works", "duration": 123})
        self.assertEqual(len(logger.commands), 2)
        sleep_mock.assert_called_once_with(extractor.VIDEO_INFO_RETRY_DELAY_SECONDS)
        self.assertTrue(any("attempt 1/3 failed" in message for message in logger.messages))
        self.assertTrue(any("HTTP Error 429" in message for message in logger.messages))

    def test_get_video_info_includes_optional_browser_cookie_auth(self):
        successful_attempt = subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=json.dumps({"title": "Cookie Works", "duration": 123}),
        )
        logger = FakeVideoInfoLogger([successful_attempt])

        with patch.dict(extractor.os.environ, {extractor.YT_DLP_COOKIES_BROWSER_ENV: "edge"}, clear=False):
            extractor.get_video_info(
                "https://www.youtube.com/watch?v=abcdefghijk",
                logger,
                info_timeout_seconds=30,
            )

        self.assertIn("--cookies-from-browser", logger.commands[0])
        self.assertIn("edge", logger.commands[0])


if __name__ == "__main__":
    unittest.main()
