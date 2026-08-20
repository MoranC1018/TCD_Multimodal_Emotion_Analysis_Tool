"""Contract tests for the top-level desktop application package."""

from __future__ import annotations

import importlib
import importlib.util
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APPLICATION_ROOT = REPOSITORY_ROOT / "application"


class ApplicationPackageTests(unittest.TestCase):
    """Keep the cross-stack launcher outside any one pipeline stage."""

    def test_application_owns_launcher_backend_assets_and_tests(self) -> None:
        expected_paths = (
            "__init__.py",
            "launcher.py",
            "backend.py",
            "local_videos.py",
            "manual_segments.py",
            "static/index.html",
            "static/app.js",
            "static/styles.css",
            "tests/test_backend.py",
            "tests/test_release_ui_contract.py",
        )

        for relative_path in expected_paths:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((APPLICATION_ROOT / relative_path).is_file())

    def test_primary_launcher_uses_application_module(self) -> None:
        launcher = (REPOSITORY_ROOT / "Launch_Video_Processing_Stack.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("-m application.launcher", launcher)
        self.assertNotIn("-m procurement.ui.launcher", launcher)

    def test_application_modules_are_importable(self) -> None:
        for module_name in (
            "application.backend",
            "application.launcher",
            "application.local_videos",
            "application.manual_segments",
        ):
            with self.subTest(module_name=module_name):
                self.assertIsNotNone(importlib.import_module(module_name))

    def test_research_workflow_packages_are_importable(self) -> None:
        def find_module(module_name: str):
            try:
                return importlib.util.find_spec(module_name)
            except ModuleNotFoundError:
                return None

        for module_name in (
            "procurement",
            "procurement.run_pipeline",
            "analysis",
            "analysis.workflow",
        ):
            with self.subTest(module_name=module_name):
                self.assertIsNotNone(find_module(module_name))

    def test_application_is_the_only_ui_package(self) -> None:
        self.assertIsNone(importlib.util.find_spec("procurement.ui"))


if __name__ == "__main__":
    unittest.main()
