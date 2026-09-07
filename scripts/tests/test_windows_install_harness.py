"""Real PowerShell checks for installation evidence and host-protection guards."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "scripts" / "test_windows_install.ps1"
POWERSHELL = shutil.which("powershell.exe")


def quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "Windows PowerShell required")
class InstallEvidenceTests(unittest.TestCase):
    def run_ps(self, command: str) -> subprocess.CompletedProcess:
        self.assertTrue(HARNESS.is_file(), "The installation harness is missing")
        environment = os.environ.copy()
        # A Python child of PowerShell 7 otherwise inherits incompatible core
        # module directories. Exercise Windows PowerShell's actual builtins.
        environment['PSModulePath'] = str(
            Path(os.environ['SystemRoot']) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'Modules'
        )
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
             "$ErrorActionPreference='Stop'; . " + quote(HARNESS)
             + " -FunctionsOnly; " + command],
            capture_output=True, text=True, timeout=30, env=environment,
        )

    def test_loading_functions_has_no_install_side_effects(self):
        result = self.run_ps("Write-Output 'definitions-only'")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "definitions-only")

    def test_nonzero_child_preserves_logs_and_failure_status(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.run_ps(
                "Invoke-InstallTestCommand -Name 'failure' -Executable $PSHOME\\powershell.exe "
                "-Arguments @('-NoProfile','-Command','Write-Output retained; exit 23') "
                "-ReportDirectory " + quote(root)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('failure failed with exit code 23', result.stderr)
            report = json.loads((Path(root) / "failure.command.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(report["exit_code"], 23)
            self.assertEqual(report["state"], "failed")
            self.assertIn("retained", (Path(root) / "failure.log").read_text(encoding="utf-8-sig"))

    def test_success_and_literal_arguments(self):
        with tempfile.TemporaryDirectory(prefix="install evidence '") as root:
            result = self.run_ps(
                "Invoke-InstallTestCommand -Name 'success' -Executable $PSHOME\\powershell.exe "
                "-Arguments @('-NoProfile','-Command','Write-Output ''literal $value; data''; exit 0') "
                "-ReportDirectory " + quote(root)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((Path(root) / "success.command.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(report["exit_code"], 0)
            self.assertEqual(report["state"], "passed")
            self.assertIn("literal $value; data", (Path(root) / "success.log").read_text(encoding="utf-8-sig"))

    def test_existing_command_evidence_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "again.log"
            target.write_text("original", encoding="utf-8")
            result = self.run_ps(
                "Invoke-InstallTestCommand -Name 'again' -Executable $PSHOME\\powershell.exe "
                "-Arguments @('-NoProfile','-Command','exit 0') -ReportDirectory " + quote(root)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('already exists', result.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_existing_evidence_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            result = self.run_ps("New-InstallTestEvidence -Path " + quote(root) + " -Repository " + quote(REPO))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('already exists', result.stderr)
            self.assertEqual(marker.read_text(), "keep")

    def test_evidence_inside_repository_is_rejected(self):
        target = REPO / "uncreated-install-test-evidence"
        self.assertFalse(target.exists())
        result = self.run_ps("New-InstallTestEvidence -Path " + quote(target) + " -Repository " + quote(REPO))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('outside the repository', result.stderr)
        self.assertFalse(target.exists())

    def test_missing_executable_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.run_ps(
                "Invoke-InstallTestCommand -Name 'missing' -Executable 'Z:\\missing-install-test.exe' "
                "-Arguments @() -ReportDirectory " + quote(root)
            )
            self.assertNotEqual(result.returncode, 0)
            report = json.loads((Path(root) / "missing.command.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(report['state'], 'failed')
            self.assertIsNone(report['exit_code'])

    def test_self_hosted_actions_runner_is_rejected(self):
        result = self.run_ps(
            "$env:GITHUB_ACTIONS='true'; $env:RUNNER_ENVIRONMENT='self-hosted'; "
            "Assert-InstallTestEnvironment -Kind GitHubHosted"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('disposable environment', result.stderr)

    def test_github_hosted_guard_accepts_its_recorded_environment(self):
        result = self.run_ps(
            "$env:GITHUB_ACTIONS='true'; $env:RUNNER_ENVIRONMENT='github-hosted'; "
            "Assert-InstallTestEnvironment -Kind GitHubHosted"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_snapshot_covers_javascript_java_and_batch_files(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            for name in ('app.js', 'Adapter.java', 'launch.bat'):
                (directory / name).write_text('original', encoding='utf-8')
            subprocess.run(['git', 'init', '-q', root], check=True, capture_output=True)
            subprocess.run(['git', '-C', root, 'add', '.'], check=True, capture_output=True)
            subprocess.run(['git', '-C', root, '-c', 'user.name=Install test', '-c',
                            'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'],
                           check=True, capture_output=True)
            command = 'Get-InstallTestSource -Repository ' + quote(root) + ' | ConvertTo-Json -Depth 8'
            before = self.run_ps(command)
            self.assertEqual(before.returncode, 0, before.stderr)
            original = json.loads(before.stdout)['hashes']
            for name in ('app.js', 'Adapter.java', 'launch.bat'):
                self.assertIn(name, original)
                (directory / name).write_text('changed', encoding='utf-8')
            after = self.run_ps(command)
            self.assertEqual(after.returncode, 0, after.stderr)
            modified = json.loads(after.stdout)['hashes']
            for name in original:
                self.assertNotEqual(original[name], modified[name])

    def test_lfs_hydration_identity_without_global_or_system_git_config(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            payload = b'Exact installation fixture payload\x00\xff'
            pointer = (
                'version https://git-lfs.github.com/spec/v1\n'
                f'oid sha256:{hashlib.sha256(payload).hexdigest()}\n'
                f'size {len(payload)}\n'
            )
            (directory / '.gitattributes').write_text(
                '*.bin filter=lfs diff=lfs merge=lfs -text\n', encoding='utf-8'
            )
            target = directory / 'weights.bin'
            target.write_bytes(pointer.encode('utf-8'))
            environment = os.environ.copy()
            environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='NUL',
                               GIT_LFS_SKIP_SMUDGE='1')
            for arguments in (
                ['init', '-q', root], ['-C', root, 'add', '.'],
                ['-C', root, '-c', 'user.name=Install test', '-c',
                 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'],
            ):
                subprocess.run(['git', *arguments], env=environment,
                               check=True, capture_output=True)
            command = (
                "$env:GIT_CONFIG_NOSYSTEM='1'; $env:GIT_CONFIG_GLOBAL='NUL'; "
                "$env:GIT_LFS_SKIP_SMUDGE='1'; Get-InstallTestSource -Repository "
                + quote(root) + ' | ConvertTo-Json -Depth 8'
            )

            def snapshot():
                result = self.run_ps(command)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)['hashes']['weights.bin']

            original = snapshot()
            self.assertTrue(original.startswith('git-clean-blob:'))
            target.write_bytes(payload)
            self.assertEqual(original, snapshot())
            target.write_bytes(payload + b'changed')
            self.assertNotEqual(original, snapshot())


if __name__ == "__main__":
    unittest.main()
