import unittest
from pathlib import Path
from unittest.mock import patch

from procurement.video_sampling import run_from_docx


class RunFromDocxTests(unittest.TestCase):
    def test_build_wrapper_command_routes_through_new_video_sampling_package(self):
        command = run_from_docx.build_wrapper_command(
            python_executable=Path("C:/Python/python.exe"),
            script_root=Path("C:/project/procurement/video_sampling"),
            docx_path=Path("C:/project/Videos.docx"),
            output_docx_path=Path("C:/project/Videos_with_links.docx"),
            limit=3,
            force=True,
            no_stitch=True,
        )

        self.assertEqual(command[0], str(Path("C:/Python/python.exe")))
        self.assertEqual(command[1], "-m")
        self.assertEqual(command[2], "procurement.video_sampling.run_docx_extractions")
        self.assertIn("--speaker-output-root", command)
        self.assertIn(str(Path("C:/project/procurement/video_sampling")), command)
        self.assertIn("--output", command)
        self.assertIn("--limit", command)
        self.assertIn("3", command)
        self.assertIn("--force", command)
        self.assertIn("--no-stitch", command)

    def test_resolve_python_prefers_python_environment_variable(self):
        with patch.dict(run_from_docx.os.environ, {"PYTHON": "C:/custom/python.exe"}):
            with patch.object(run_from_docx.Path, "exists", return_value=True):
                resolved = run_from_docx.resolve_python_executable()

        self.assertEqual(resolved, Path("C:/custom/python.exe"))


if __name__ == "__main__":
    unittest.main()
