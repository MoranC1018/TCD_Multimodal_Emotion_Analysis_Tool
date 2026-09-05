"""Contract tests for the top-level desktop application package."""

from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
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
        source = (REPOSITORY_ROOT / "Launch_Video_Processing_Stack.bat").read_text(
            encoding="utf-8"
        )
        self.assertIn('"%~1" -m application.launcher', source)
        self.assertNotIn("procurement.ui", source)

    def test_primary_launcher_enforces_simulated_python_version_and_webview_policy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="emotion-tool-simulated-python311-") as raw_root:
            root = Path(raw_root)
            launcher = root / "Launch_Video_Processing_Stack.bat"
            shutil.copy2(REPOSITORY_ROOT / launcher.name, launcher)
            record = root / "launcher-invocation.txt"
            controlled_application = root / "application"
            controlled_application.mkdir()
            (controlled_application / "__init__.py").write_text("", encoding="utf-8")
            (controlled_application / "launcher.py").write_text(
                "import os\n"
                "import sys\n"
                "from pathlib import Path\n"
                "\n"
                "Path(os.environ['LAUNCHER_TEST_RECORD']).write_text(\n"
                "    f\"{sys.version_info[:2]}|\"\n"
                "    f\"{os.environ.get('PYTHON_MANAGER_AUTOMATIC_INSTALL', '<unset>')}|\"\n"
                "    '-m application.launcher', encoding='utf-8'\n"
                ")\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["LOCALAPPDATA"] = str(root / "no-local-python")
            environment["ProgramFiles"] = str(root / "no-program-files")
            environment["PATH"] = os.pathsep.join(
                (str(Path(sys.executable).parent), str(Path(os.environ["SystemRoot"]) / "System32"))
            )
            environment["PATHEXT"] = ".COM;.EXE;.BAT;.CMD"
            environment["PYTHONPATH"] = str(root)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["LAUNCHER_TEST_RECORD"] = str(record)
            environment.pop("PYTHON_MANAGER_AUTOMATIC_INSTALL", None)

            cases = (
                ((3, 10), True, False),
                ((3, 11), True, True),
                ((3, 13), True, True),
                ((3, 12), False, False),
            )
            for (major, minor), has_webview, should_launch in cases:
                with self.subTest(version=(major, minor), has_webview=has_webview):
                    record.unlink(missing_ok=True)
                    (root / "sitecustomize.py").write_text(
                        "import sys\n"
                        "\n"
                        "class ControlledVersionInfo(tuple):\n"
                        f"    major = {major}\n"
                        f"    minor = {minor}\n"
                        "    micro = 9\n"
                        "    releaselevel = 'final'\n"
                        "    serial = 0\n"
                        "\n"
                        "sys.version_info = ControlledVersionInfo("
                        f"({major}, {minor}, 9, 'final', 0))\n",
                        encoding="utf-8",
                    )
                    (root / "webview.py").write_text(
                        "" if has_webview else "raise ModuleNotFoundError('webview blocked by test')\n",
                        encoding="utf-8",
                    )

                    simulated_identity = subprocess.run(
                        [sys.executable, "-c", "import sys; print(sys.version_info[:2])"],
                        cwd=root,
                        env=environment,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertEqual(
                        simulated_identity.returncode,
                        0,
                        simulated_identity.stdout + simulated_identity.stderr,
                    )
                    self.assertEqual(
                        simulated_identity.stdout.strip(),
                        f"({major}, {minor})",
                    )

                    completed = subprocess.run(
                        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(launcher)],
                        cwd=root,
                        env=environment,
                        input="\n",
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )

                    if should_launch:
                        self.assertEqual(
                            completed.returncode,
                            0,
                            completed.stdout + completed.stderr,
                        )
                        self.assertEqual(
                            record.read_text(encoding="utf-8"),
                            f"({major}, {minor})|false|-m application.launcher",
                        )
                    else:
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertFalse(record.exists())

    def test_primary_launcher_prefers_compatible_project_venv(self) -> None:
        with tempfile.TemporaryDirectory(prefix="emotion-tool-venv-priority-") as raw_root:
            root = Path(raw_root)
            launcher = root / "Launch_Video_Processing_Stack.bat"
            shutil.copy2(REPOSITORY_ROOT / launcher.name, launcher)
            venv_python = root / ".venv" / "Scripts" / "python.exe"
            venv_python.parent.mkdir(parents=True)
            # A venv redirector cannot be relocated without its pyvenv.cfg.
            try:
                os.link(sys._base_executable, venv_python)
            except OSError:
                shutil.copy2(sys._base_executable, venv_python)

            record = root / "launcher-invocation.txt"
            py_record = root / "py-invocation.txt"
            command_dir = root / "commands"
            command_dir.mkdir()
            (command_dir / "py.cmd").write_text(
                "@echo off\n"
                f">>\"{py_record}\" echo %*\n"
                "exit /b 97\n",
                encoding="utf-8",
            )
            (root / "webview.py").write_text("", encoding="utf-8")
            controlled_application = root / "application"
            controlled_application.mkdir()
            (controlled_application / "__init__.py").write_text("", encoding="utf-8")
            (controlled_application / "launcher.py").write_text(
                "import os\n"
                "import sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['LAUNCHER_TEST_RECORD']).write_text(\n"
                "    f\"{sys.executable}|\"\n"
                "    f\"{os.environ.get('PYTHON_MANAGER_AUTOMATIC_INSTALL', '<unset>')}\",\n"
                "    encoding='utf-8',\n"
                ")\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["LOCALAPPDATA"] = str(root / "no-local-python")
            environment["ProgramFiles"] = str(root / "no-program-files")
            environment["PATH"] = os.pathsep.join(
                (
                    str(command_dir),
                    str(Path(sys.executable).parent),
                    str(Path(sys._base_executable).parent),
                    str(Path(os.environ["SystemRoot"]) / "System32"),
                )
            )
            environment["PATHEXT"] = ".COM;.EXE;.BAT;.CMD"
            environment["PYTHONHOME"] = sys.base_prefix
            environment["PYTHONPATH"] = str(root)
            environment["LAUNCHER_TEST_RECORD"] = str(record)
            environment.pop("PYTHON_MANAGER_AUTOMATIC_INSTALL", None)

            completed = subprocess.run(
                [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(launcher)],
                cwd=root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            selected, automatic_install = record.read_text(encoding="utf-8").split("|")
            self.assertEqual(Path(selected).resolve(), venv_python.resolve())
            self.assertEqual(automatic_install, "false")
            self.assertFalse(py_record.exists(), "py must not be probed before a compatible .venv")

    def test_primary_launcher_lists_registered_runtimes_without_launching_py(self) -> None:
        with tempfile.TemporaryDirectory(prefix="emotion-tool-registered-python-") as raw_root:
            root = Path(raw_root)
            launcher = root / "Launch_Video_Processing_Stack.bat"
            shutil.copy2(REPOSITORY_ROOT / launcher.name, launcher)
            registered_313 = root / "registered-313" / "python.exe"
            registered_312 = root / "registered-312" / "python.exe"
            for target in (registered_313, registered_312):
                target.parent.mkdir(parents=True)
                try:
                    os.link(sys._base_executable, target)
                except OSError:
                    shutil.copy2(sys._base_executable, target)

            record = root / "launcher-invocation.txt"
            py_record = root / "py-invocation.txt"
            command_dir = root / "commands"
            command_dir.mkdir()
            (command_dir / "py.cmd").write_text(
                "@echo off\n"
                f">>\"{py_record}\" echo %*;%PYTHON_MANAGER_AUTOMATIC_INSTALL%\n"
                "if /I not \"%~1\"==\"-0p\" exit /b 97\n"
                f"echo  -3.13-64        {registered_313}\n"
                f"echo  -3.12-64        {registered_312}\n"
                "exit /b 0\n",
                encoding="utf-8",
            )
            (root / "webview.py").write_text("", encoding="utf-8")
            controlled_application = root / "application"
            controlled_application.mkdir()
            (controlled_application / "__init__.py").write_text("", encoding="utf-8")
            (controlled_application / "launcher.py").write_text(
                "import os\n"
                "import sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['LAUNCHER_TEST_RECORD']).write_text(\n"
                "    f\"{sys.executable}|\"\n"
                "    f\"{os.environ.get('PYTHON_MANAGER_AUTOMATIC_INSTALL', '<unset>')}\",\n"
                "    encoding='utf-8',\n"
                ")\n",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["LOCALAPPDATA"] = str(root / "no-local-python")
            environment["ProgramFiles"] = str(root / "no-program-files")
            environment["PATH"] = os.pathsep.join(
                (
                    str(command_dir),
                    str(Path(sys.executable).parent),
                    str(Path(sys._base_executable).parent),
                    str(Path(os.environ["SystemRoot"]) / "System32"),
                )
            )
            environment["PATHEXT"] = ".COM;.EXE;.BAT;.CMD"
            environment["PYTHONHOME"] = sys.base_prefix
            environment["PYTHONPATH"] = str(root)
            environment["LAUNCHER_TEST_RECORD"] = str(record)
            environment.pop("PYTHON_MANAGER_AUTOMATIC_INSTALL", None)

            completed = subprocess.run(
                [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(launcher)],
                cwd=root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            selected, automatic_install = record.read_text(encoding="utf-8").split("|")
            self.assertEqual(Path(selected).resolve(), registered_312.resolve())
            self.assertEqual(automatic_install, "false")
            self.assertEqual(py_record.read_text(encoding="utf-8").strip(), "-0p;false")

    def test_primary_launcher_skips_crashed_project_python_for_healthy_path_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="emotion-tool-crashed-python-") as raw_root:
            root = Path(raw_root)
            launcher = root / "Launch_Video_Processing_Stack.bat"
            shutil.copy2(REPOSITORY_ROOT / launcher.name, launcher)
            venv_python = root / ".venv" / "Scripts" / "python.exe"
            venv_python.parent.mkdir(parents=True)
            try:
                os.link(sys._base_executable, venv_python)
            except OSError:
                shutil.copy2(sys._base_executable, venv_python)

            record = root / "launcher-invocation.txt"
            (root / "sitecustomize.py").write_text(
                "import os, sys\n"
                "from pathlib import Path\n"
                f"if Path(sys.executable).resolve() == Path({str(venv_python)!r}).resolve():\n"
                "    os._exit(-1073741515)\n",
                encoding="utf-8",
            )
            (root / "webview.py").write_text("", encoding="utf-8")
            controlled_application = root / "application"
            controlled_application.mkdir()
            (controlled_application / "__init__.py").write_text("", encoding="utf-8")
            (controlled_application / "launcher.py").write_text(
                "import os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['LAUNCHER_TEST_RECORD']).write_text(sys.executable, encoding='utf-8')\n",
                encoding="utf-8",
            )
            command_dir = root / "commands"
            command_dir.mkdir()
            (command_dir / "py.cmd").write_text("@echo off\nexit /b 97\n", encoding="utf-8")
            environment = dict(os.environ)
            environment.update(
                LOCALAPPDATA=str(root / "no-local-python"),
                ProgramFiles=str(root / "no-program-files"),
                PATH=os.pathsep.join((
                    str(command_dir),
                    str(Path(sys.executable).parent),
                    str(Path(sys._base_executable).parent),
                    str(Path(os.environ["SystemRoot"]) / "System32"),
                )),
                PATHEXT=".COM;.EXE;.BAT;.CMD",
                PYTHONHOME=sys.base_prefix,
                PYTHONPATH=str(root),
                PYTHONDONTWRITEBYTECODE="1",
                LAUNCHER_TEST_RECORD=str(record),
            )
            crashed_probe = subprocess.run(
                [str(venv_python), "-c", "import sys, webview"],
                cwd=root, env=environment, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(crashed_probe.returncode, 0xC0000135)

            completed = subprocess.run(
                [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(launcher)],
                cwd=root, env=environment, input="\n",
                capture_output=True, text=True, timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(Path(record.read_text(encoding="utf-8")).resolve(), Path(sys.executable).resolve())

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
