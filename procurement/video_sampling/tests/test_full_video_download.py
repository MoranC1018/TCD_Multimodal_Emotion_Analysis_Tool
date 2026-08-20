import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from procurement.video_sampling import full_video_download


class FullVideoDownloadTests(unittest.TestCase):
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
