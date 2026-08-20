import unittest

from unittest.mock import patch

from audio_pipeline.doctor import (
    DEPENDENCIES,
    DiagnosticCheck,
    audio_io_check,
    collect_diagnostics,
    required_checks_pass,
    torchaudio_runtime_check,
)


class DoctorTests(unittest.TestCase):
    def test_optional_warning_does_not_fail_required_diagnostics(self):
        checks = [
            DiagnosticCheck("required", True, "ok"),
            DiagnosticCheck("optional model layer", False, "not installed", required=False),
        ]

        self.assertTrue(required_checks_pass(checks))

    def test_diagnostics_do_not_require_vox_profile_checkout(self):
        with (
            patch("audio_pipeline.doctor.dependency_check", side_effect=lambda distribution, module: DiagnosticCheck(distribution, True, "ok")),
            patch("audio_pipeline.doctor.audio_io_check", return_value=DiagnosticCheck("production audio I/O", True, "ok")),
            patch(
                "audio_pipeline.doctor.torchaudio_runtime_check",
                return_value=DiagnosticCheck("optional TorchAudio codec runtime", True, "ok", required=False),
            ),
            patch("audio_pipeline.doctor.torch_device_check", return_value=DiagnosticCheck("torch device", True, "cpu")),
            patch("audio_pipeline.doctor.local_tool_check", side_effect=lambda name, resolver: DiagnosticCheck(name, True, "ok")),
        ):
            checks = collect_diagnostics()

        self.assertNotIn("vox-profile", " ".join(check.name for check in checks).lower())

    def test_loralib_is_not_required_without_vox_profile_wrapper(self):
        self.assertNotIn("loralib", [distribution for distribution, _module in DEPENDENCIES])

    def test_production_audio_io_round_trip_passes(self):
        self.assertTrue(audio_io_check().ok)

    def test_torchaudio_runtime_problem_is_only_a_warning(self):
        with patch.dict("sys.modules", {"torchaudio": None}):
            check = torchaudio_runtime_check()

        self.assertFalse(check.ok)
        self.assertFalse(check.required)


if __name__ == "__main__":
    unittest.main()
