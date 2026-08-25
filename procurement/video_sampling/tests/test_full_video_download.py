import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from procurement.video_sampling import full_video_download


class FullVideoDownloadTests(unittest.TestCase):
    def test_network_commands_reject_non_youtube_urls_before_subprocess(self) -> None:
        invalid = "https://youtube.com.attacker.example/watch?v=abcdefghijk"
        with self.assertRaisesRegex(ValueError, "YouTube"):
            full_video_download.read_video_info(invalid, 30)
        with self.assertRaisesRegex(ValueError, "YouTube"):
            full_video_download.build_download_command(invalid, Path("output"), "best")

    def test_download_command_has_a_hard_file_size_ceiling(self) -> None:
        command = full_video_download.build_download_command(
            "https://www.youtube.com/watch?v=abcdefghijk", Path("output"), "best"
        )
        self.assertIn("--max-filesize", command)
        self.assertEqual(
            command[command.index("--max-filesize") + 1],
            str(full_video_download.DEFAULT_MAX_DOWNLOAD_BYTES),
        )

    def test_download_command_includes_optional_browser_cookie_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_folder = Path(temp_dir)

            with patch.dict(
                full_video_download.os.environ,
                {full_video_download.YT_DLP_COOKIES_BROWSER_ENV: "chrome"},
                clear=False,
            ):
                command = full_video_download.build_download_command(
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    output_folder,
                    "best",
                )

        self.assertIn("--cookies-from-browser", command)
        self.assertIn("chrome", command)


if __name__ == "__main__":
    unittest.main()
