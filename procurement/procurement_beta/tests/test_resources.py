from __future__ import annotations

from pathlib import Path

from procurement.procurement_beta import resources
from procurement.external_tools import resolve_nvidia_smi


def test_nvidia_resolver_rejects_current_directory_path_decoy(monkeypatch, tmp_path: Path) -> None:
    decoy = tmp_path / "nvidia-smi.exe"
    decoy.write_bytes(b"decoy")
    monkeypatch.chdir(tmp_path)

    try:
        resolved = resolve_nvidia_smi(search_path=str(tmp_path))
    except FileNotFoundError:
        return

    assert resolved != decoy.resolve(), "current-directory nvidia-smi decoy should not be trusted"


def test_nvidia_resolver_rejects_sibling_user_data_path_decoy(monkeypatch, tmp_path: Path) -> None:
    selected_root = tmp_path / "selected-input"
    selected_root.mkdir()
    decoy = tmp_path / "user-data" / "bin" / "nvidia-smi.exe"
    decoy.parent.mkdir(parents=True)
    decoy.write_bytes(b"decoy")
    monkeypatch.chdir(selected_root)

    try:
        resolved = resolve_nvidia_smi(
            excluded_roots=(selected_root,),
            search_path=str(decoy.parent),
        )
    except FileNotFoundError:
        return

    assert resolved != decoy.resolve(), "sibling user-data nvidia-smi PATH decoy should not be trusted"


def test_gpu_telemetry_uses_absolute_binary_and_credential_free_environment(monkeypatch) -> None:
    captured: dict[str, object] = {}
    secret_names = ("YOUTUBE_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN")

    class Result:
        returncode = 0
        stdout = "10, 100, 1000\n"

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return Result()

    for name in secret_names:
        monkeypatch.setenv(name, f"secret-{name}")
    monkeypatch.setattr(resources, "resolve_nvidia_smi", lambda **_kwargs: Path("C:/trusted/NVSMI/nvidia-smi.exe"))
    monkeypatch.setattr(resources.subprocess, "run", fake_run)

    resources.gpu_pressure_reasons(5.0)

    assert captured["command"][0] == "C:\\trusted\\NVSMI\\nvidia-smi.exe"
    environment = captured.get("env")
    assert isinstance(environment, dict)
    assert all(name not in environment for name in secret_names)


def test_resource_pressure_reasons_reports_low_headroom(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(resources, "physical_memory_available_percent", lambda: 4.0)
    monkeypatch.setattr(resources, "cpu_busy_percent", lambda: 96.0)
    monkeypatch.setattr(resources, "gpu_pressure_reasons", lambda _minimum: ["GPU 1 free 2.0% < required 5.0%"])

    reasons = resources.resource_pressure_reasons(5.0, output_path=tmp_path)

    assert "RAM free 4.0% < required 5.0%" in reasons
    assert "CPU free 4.0% < required 5.0%" in reasons
    assert "GPU 1 free 2.0% < required 5.0%" in reasons


def test_wait_for_resource_headroom_sleeps_until_clear(monkeypatch, tmp_path: Path) -> None:
    calls = iter([["RAM free 4.0% < required 5.0%"], []])
    sleeps: list[float] = []
    logs: list[str] = []
    monkeypatch.setattr(resources, "resource_pressure_reasons", lambda _minimum, output_path: next(calls))
    monkeypatch.setattr(resources.time, "sleep", lambda seconds: sleeps.append(seconds))

    resources.wait_for_resource_headroom(
        min_free_percent=5.0,
        output_path=tmp_path,
        poll_seconds=2.0,
        logger=logs.append,
        stage="unit test",
    )

    assert sleeps == [2.0]
    assert logs and "waiting before unit test" in logs[0]


def test_wait_for_resource_headroom_can_be_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(resources, "resource_pressure_reasons", lambda _minimum, output_path: (_ for _ in ()).throw(AssertionError()))

    resources.wait_for_resource_headroom(min_free_percent=0.0, output_path=tmp_path, poll_seconds=1.0)


def test_wait_for_resource_headroom_times_out(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(resources, "resource_pressure_reasons", lambda _minimum, output_path: ["RAM free 4.0% < required 15.0%"])
    monkeypatch.setattr(resources.time, "sleep", lambda _seconds: None)

    times = iter([0.0, 901.0])
    monkeypatch.setattr(resources.time, "monotonic", lambda: next(times))

    try:
        resources.wait_for_resource_headroom(
            min_free_percent=15.0,
            output_path=tmp_path,
            poll_seconds=1.0,
            timeout_seconds=900.0,
            stage="unit timeout",
        )
    except TimeoutError as exc:
        assert "Resource guard timed out before unit timeout" in str(exc)
    else:
        raise AssertionError("resource guard should time out when pressure never clears")



def test_disk_space_warning_only_reports_below_ten_gib(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(resources, "disk_available_bytes", lambda _path: 9 * 1024 * 1024 * 1024)

    warning = resources.disk_space_warning(tmp_path)

    assert "recommended minimum is 10 GiB" in warning
