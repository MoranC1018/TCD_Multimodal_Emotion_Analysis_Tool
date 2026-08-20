import builtins
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from procurement.video_sampling import extractor


class ExtractorLoggerTests(unittest.TestCase):
    def test_terminal_write_failure_does_not_abort_logging(self):
        """Windows console write failures should not stop a media extraction."""

        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                with patch.object(builtins, "print", side_effect=OSError(22, "Invalid argument")):
                    logger = extractor.RunLogger()
                    logger.log("ffmpeg progress line")
                    finished_log = logger.finish("test").resolve()
            finally:
                os.chdir(original_cwd)

            log_text = finished_log.read_text(encoding="utf-8")

        self.assertIn("Run started:", log_text)
        self.assertIn("ffmpeg progress line", log_text)


if __name__ == "__main__":
    unittest.main()
