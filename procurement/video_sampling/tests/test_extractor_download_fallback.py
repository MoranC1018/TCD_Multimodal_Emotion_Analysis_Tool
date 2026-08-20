import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from procurement.video_sampling import extractor


class FakeDownloadLogger:
    """Small logger double that can make the first download fail."""

    def __init__(self, raw_clip_folder: Path) -> None:
        self.raw_clip_folder = raw_clip_folder
        self.commands: list[list[str]] = []
        self.messages: list[str] = []

    def log(self, message: object = "") -> None:
        self.messages.append(str(message))

    def run_command_live(
        self,
        command: list[str],
        overall_timeout_seconds: int,
        stall_timeout_seconds: int,
    ) -> None:
        self.commands.append(command)

        joined_command = " ".join(command)
        if "[protocol^=m3u8]" not in joined_command:
            raise subprocess.CalledProcessError(1, command)

        output_path = self.raw_clip_folder / "001_00_10_00_21.mp4"
        output_path.write_bytes(b"fallback clip")


class ExtractorDownloadFallbackTests(unittest.TestCase):
    def test_download_segment_uses_hls_fallback_after_standard_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_clip_folder = Path(temp_dir)
            logger = FakeDownloadLogger(raw_clip_folder)

            downloaded = extractor.download_segment(
                url="https://www.youtube.com/watch?v=uerr3AUkc1g",
                segment={"start": 10, "end": 21, "length": 11},
                segment_number=1,
                raw_clip_folder=raw_clip_folder,
                logger=logger,
                format_selector=extractor.DEFAULT_FORMAT_SELECTOR_TEMPLATE.format(max_height=720),
                max_height=720,
                retries=1,
                overall_timeout_seconds=30,
                stall_timeout_seconds=10,
            )

            self.assertEqual(downloaded.name, "001_00_10_00_21.mp4")
            self.assertEqual(len(logger.commands), 2)
            self.assertIn("[protocol^=m3u8]", " ".join(logger.commands[1]))
            self.assertTrue(any("HLS fallback" in message for message in logger.messages))

    def test_hls_fallback_selector_prefers_m3u8_formats(self):
        selector = extractor.build_hls_fallback_format_selector(max_height=720)

        self.assertIn("[protocol^=m3u8]", selector)
        self.assertIn("height<=720", selector)

    def test_segment_command_includes_optional_cookie_file_auth(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_template = Path(temp_dir) / "segment.%(ext)s"

            with patch.dict(extractor.os.environ, {extractor.YT_DLP_COOKIES_FILE_ENV: r"C:\cookies.txt"}, clear=False):
                command = extractor.build_yt_dlp_segment_command(
                    url="https://www.youtube.com/watch?v=abc123",
                    start_timestamp="00:00:10",
                    end_timestamp="00:00:20",
                    output_path_template=output_template,
                    format_selector="best",
                    max_height=720,
                )

        self.assertIn("--cookies", command)
        self.assertIn(r"C:\cookies.txt", command)

    def test_download_segments_with_replacements_recovers_from_bad_random_segment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            raw_clip_folder = temp_path / extractor.RAW_CLIP_FOLDER_NAME
            raw_clip_folder.mkdir()
            timecode_log_path = temp_path / "timecodes.txt"
            logger = FakeDownloadLogger(raw_clip_folder)

            def fake_download_segment(**kwargs):
                segment = kwargs["segment"]
                segment_number = kwargs["segment_number"]
                if segment["start"] == 0:
                    raise RuntimeError("temporary YouTube challenge")

                output_path = raw_clip_folder / f"{segment_number:03d}.mp4"
                output_path.write_bytes(b"replacement clip")
                return output_path

            with patch.object(extractor, "download_segment", side_effect=fake_download_segment):
                with patch.object(extractor, "choose_start_from_allowed_intervals", return_value=60):
                    raw_clips, selected_segments, failed_segments = extractor.download_segments_with_replacements(
                        url="https://www.youtube.com/watch?v=abc123",
                        selected_segments=[{"start": 0, "end": 30, "length": 30}],
                        video_duration=120,
                        no_go_segments=[],
                        raw_clip_folder=raw_clip_folder,
                        logger=logger,
                        format_selector=extractor.DEFAULT_FORMAT_SELECTOR_TEMPLATE.format(max_height=720),
                        max_height=720,
                        retries=1,
                        overall_timeout_seconds=30,
                        stall_timeout_seconds=10,
                        max_segment_replacements=1,
                        timecode_log_path=timecode_log_path,
                        title="Example",
                        video_id="abc123",
                        total_seconds_to_download=30,
                        seed=123,
                        seed_source="cli",
                        metadata={},
                    )

            self.assertEqual(len(raw_clips), 1)
            self.assertEqual(len(selected_segments), 2)
            self.assertEqual(selected_segments[1], {"start": 60, "end": 90, "length": 30})
            self.assertEqual(failed_segments[0]["start"], 0)
            self.assertTrue(timecode_log_path.exists())
            self.assertIn("00:01:00 to 00:01:30", timecode_log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
