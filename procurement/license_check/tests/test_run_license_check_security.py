from __future__ import annotations

from pathlib import Path

from procurement.license_check import run_license_check


def test_verifier_invocation_keeps_api_key_out_of_process_arguments(tmp_path: Path) -> None:
    secret = "test-secret-that-must-not-enter-argv"

    command, environment = run_license_check.build_verifier_invocation(
        base=tmp_path,
        audited_docx=tmp_path / "audited.docx",
        verifier_csv=tmp_path / "verification.csv",
        verifier_summary=tmp_path / "summary.txt",
        api_key=secret,
    )

    assert secret not in command
    assert "--api-key" not in command
    assert environment["YOUTUBE_API_KEY"] == secret
