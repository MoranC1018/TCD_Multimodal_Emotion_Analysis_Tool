from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from procurement.external_tools import build_yt_dlp_command, credential_free_media_environment


class ExternalToolIsolationTests(unittest.TestCase):
    def test_external_media_environment_strips_model_and_api_credentials(self) -> None:
        environment = credential_free_media_environment(
            {
                "PATH": r"C:\trusted-tools",
                "YOUTUBE_API_KEY": "youtube-secret",
                "HF_TOKEN": "hf-secret",
                "HUGGINGFACE_TOKEN": "legacy-hf-secret",
                "HUGGING_FACE_HUB_TOKEN": "hub-secret",
            }
        )

        self.assertEqual(environment["PATH"], r"C:\trusted-tools")
        for name in ("YOUTUBE_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
            self.assertNotIn(name, environment)

    def test_selected_working_directory_cannot_shadow_ytdlp_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            selected_output = Path(temp_dir) / "selected-output"
            selected_output.mkdir()
            marker = selected_output / "attacker-module-ran.txt"
            (selected_output / "yt_dlp.py").write_text(
                "import os\n"
                "from pathlib import Path\n"
                "Path(os.environ['YT_DLP_ATTACK_MARKER']).write_text('ran', encoding='utf-8')\n"
                "raise SystemExit(37)\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(selected_output)
            environment["YT_DLP_ATTACK_MARKER"] = str(marker)
            command = build_yt_dlp_command(
                ["--version"],
                ffmpeg_binary=Path(sys.executable),
                python_executable=Path(sys.executable),
            )

            completed = subprocess.run(
                command,
                cwd=selected_output,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertNotEqual(completed.returncode, 37)
            self.assertFalse(marker.exists(), "yt-dlp module lookup executed code from selected user data")


if __name__ == "__main__":
    unittest.main()
