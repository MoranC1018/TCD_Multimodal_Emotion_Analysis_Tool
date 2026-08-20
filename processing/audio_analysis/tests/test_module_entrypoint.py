from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class AudioModuleEntrypointTests(unittest.TestCase):
    def test_direct_audio_script_imports_shared_boundaries_from_any_working_directory(self) -> None:
        script = REPO_ROOT / "processing" / "audio_analysis" / "run_audio_analysis.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [sys.executable, str(script), "--help"],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout.casefold())

    def test_repository_module_entrypoints_import_cleanly(self) -> None:
        modules = (
            "processing.audio_analysis.audio_pipeline",
            "processing.audio_analysis.audio_pipeline.cli",
            "processing.audio_analysis.audio_pipeline.run_batch",
            "processing.audio_analysis.audio_pipeline.run_single",
        )
        for module in modules:
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-m", module, "--help"],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout.casefold())


if __name__ == "__main__":
    unittest.main()
