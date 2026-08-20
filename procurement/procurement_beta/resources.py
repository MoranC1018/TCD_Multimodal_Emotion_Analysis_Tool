from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from procurement.external_tools import credential_free_media_environment, resolve_nvidia_smi


Logger = Callable[[str], None]
DISK_WARNING_BYTES = 10 * 1024 * 1024 * 1024
NATIVE_THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "ONNX_NUM_THREADS",
    "ORT_NUM_THREADS",
)


@dataclass(frozen=True)
class ResourceReading:
    """One host-resource measurement used by the run throttle."""

    name: str
    available_percent: float
    required_percent: float

    def reason(self) -> str:
        return f"{self.name} free {self.available_percent:.1f}% < required {self.required_percent:.1f}%"


def lower_current_process_priority(logger: Logger | None = None) -> None:
    """Ask Windows to favor the desktop over this long-running pipeline."""

    if not sys.platform.startswith("win"):
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetCurrentProcess()
        below_normal_priority_class = 0x00004000
        if kernel32.SetPriorityClass(handle, below_normal_priority_class) and logger:
            logger("Resource guard: process priority set to below normal.")
    except Exception:
        return



def configure_low_impact_native_threads(thread_count: int = 1, logger: Logger | None = None) -> None:
    """Keep native math libraries from fanning one video job across every CPU core."""

    bounded_threads = max(1, int(thread_count))
    changed: list[str] = []
    for name in NATIVE_THREAD_ENV_VARS:
        current = os.environ.get(name)
        try:
            current_threads = int(current) if current else None
        except ValueError:
            current_threads = None
        if current_threads is None or current_threads > bounded_threads:
            os.environ[name] = str(bounded_threads)
            changed.append(name)
    os.environ.setdefault("KMP_BLOCKTIME", "0")
    os.environ.setdefault("KMP_AFFINITY", "granularity=fine,compact,1,0")
    if logger and changed:
        logger(f"Resource guard: native math threads capped at {bounded_threads} ({', '.join(changed)}).")


def configure_torch_runtime_threads(torch_module, thread_count: int = 1, logger: Logger | None = None) -> None:
    """Apply the same low-impact thread cap to PyTorch after it is imported."""

    bounded_threads = max(1, int(thread_count))
    configured: list[str] = []
    for setter_name in ("set_num_threads", "set_num_interop_threads"):
        setter = getattr(torch_module, setter_name, None)
        if callable(setter):
            try:
                setter(bounded_threads)
                configured.append(setter_name)
            except RuntimeError:
                # PyTorch can reject interop changes after work has started; the env cap still applies.
                continue
            except Exception:
                continue
    if logger and configured:
        logger(f"Resource guard: PyTorch runtime threads capped at {bounded_threads}.")


def avoid_logical_cpus(cpu_indices: list[int] | tuple[int, ...], logger: Logger | None = None) -> None:
    """Exclude unstable logical CPUs from this process on Windows."""

    if not cpu_indices or not sys.platform.startswith("win"):
        return
    mask_to_remove = 0
    for index in cpu_indices:
        if 0 <= int(index) < 63:
            mask_to_remove |= 1 << int(index)
    if mask_to_remove <= 0:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetCurrentProcess()
        process_mask = ctypes.c_size_t()
        system_mask = ctypes.c_size_t()
        if not kernel32.GetProcessAffinityMask(handle, ctypes.byref(process_mask), ctypes.byref(system_mask)):
            return
        updated_mask = int(process_mask.value) & ~mask_to_remove
        if updated_mask <= 0 or updated_mask == int(process_mask.value):
            return
        if kernel32.SetProcessAffinityMask(handle, ctypes.c_size_t(updated_mask)) and logger:
            skipped = ", ".join(str(index) for index in cpu_indices)
            logger(f"Resource guard: excluded logical CPU(s) {skipped} from this process.")
    except Exception:
        return


def limit_current_process_affinity(max_cores: int, logger: Logger | None = None) -> None:
    """Restrict this Windows process to a small number of available CPU cores."""

    core_limit = int(max_cores)
    if core_limit <= 0 or not sys.platform.startswith("win"):
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetCurrentProcess()
        process_mask = ctypes.c_size_t()
        system_mask = ctypes.c_size_t()
        if not kernel32.GetProcessAffinityMask(handle, ctypes.byref(process_mask), ctypes.byref(system_mask)):
            return
        current_mask = int(process_mask.value)
        available = [index for index in range(63) if current_mask & (1 << index)]
        if len(available) <= core_limit:
            return
        updated_mask = 0
        for index in available[:core_limit]:
            updated_mask |= 1 << index
        if kernel32.SetProcessAffinityMask(handle, ctypes.c_size_t(updated_mask)) and logger:
            logger(f"Resource guard: process affinity limited to {core_limit} logical CPU(s).")
    except Exception:
        return


def wait_for_busy_thresholds(
    *,
    cpu_high_percent: float,
    cpu_low_percent: float,
    ram_high_percent: float,
    ram_low_percent: float,
    poll_seconds: float,
    timeout_seconds: float | None,
    logger: Logger | None = None,
    stage: str = "next video",
) -> None:
    """Pause between video jobs until CPU/RAM pressure cools below resume limits."""

    cpu_high = clamp_percent(cpu_high_percent)
    cpu_low = min(cpu_high, clamp_percent(cpu_low_percent))
    ram_high = clamp_percent(ram_high_percent)
    ram_low = min(ram_high, clamp_percent(ram_low_percent))
    sleep_seconds = max(1.0, float(poll_seconds))
    timeout_limit = None if timeout_seconds is None else max(0.0, float(timeout_seconds))
    started_at = time.monotonic()
    pressure_seen = False

    while True:
        cpu_threshold = cpu_low if pressure_seen else cpu_high
        ram_threshold = ram_low if pressure_seen else ram_high
        reasons = busy_threshold_reasons(cpu_threshold=cpu_threshold, ram_threshold=ram_threshold)
        if not reasons:
            return
        pressure_seen = True
        elapsed = time.monotonic() - started_at
        if timeout_limit and elapsed >= timeout_limit:
            raise TimeoutError(
                f"Resource guard timed out before {stage} after {elapsed:.0f}s; {'; '.join(reasons)}"
            )
        if logger:
            logger(f"Resource guard: cooling before {stage}; " + "; ".join(reasons))
        time.sleep(sleep_seconds)


def busy_threshold_reasons(*, cpu_threshold: float, ram_threshold: float) -> list[str]:
    """Return reasons when CPU or RAM busy percentages exceed a threshold."""

    reasons: list[str] = []
    cpu_busy = cpu_busy_percent()
    if cpu_busy is not None and cpu_busy >= cpu_threshold:
        reasons.append(f"CPU busy {cpu_busy:.1f}% >= {cpu_threshold:.1f}%")

    memory_free = physical_memory_available_percent()
    if memory_free is not None:
        ram_busy = max(0.0, 100.0 - memory_free)
        if ram_busy >= ram_threshold:
            reasons.append(f"RAM busy {ram_busy:.1f}% >= {ram_threshold:.1f}%")
    return reasons


def clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def wait_for_resource_headroom(
    *,
    min_free_percent: float,
    output_path: Path,
    poll_seconds: float,
    timeout_seconds: float | None = 900.0,
    logger: Logger | None = None,
    stage: str = "next stage",
) -> None:
    """Pause before expensive work when the host is already under pressure."""

    required = max(0.0, min(95.0, float(min_free_percent)))
    if required <= 0:
        return
    sleep_seconds = max(1.0, float(poll_seconds))
    timeout_limit = None if timeout_seconds is None else max(0.0, float(timeout_seconds))
    started_at = time.monotonic()
    disk_warning_logged = False

    while True:
        if logger and not disk_warning_logged:
            disk_warning = disk_space_warning(output_path)
            if disk_warning:
                logger(disk_warning)
                disk_warning_logged = True
        reasons = resource_pressure_reasons(required, output_path=output_path)
        if not reasons:
            return
        elapsed = time.monotonic() - started_at
        if timeout_limit and elapsed >= timeout_limit:
            reason_text = "; ".join(reasons)
            raise TimeoutError(
                f"Resource guard timed out before {stage} after {elapsed:.0f}s; {reason_text}"
            )
        if logger:
            logger(f"Resource guard: waiting before {stage}; " + "; ".join(reasons))
        time.sleep(sleep_seconds)


def pause_if_resource_pressure(
    *,
    min_free_percent: float,
    output_path: Path,
    poll_seconds: float,
    timeout_seconds: float | None,
    logger: Logger | None = None,
    stage: str = "active work",
) -> None:
    """Yield during long-running loops when the machine is already under pressure."""

    required = max(0.0, min(95.0, float(min_free_percent)))
    if required <= 0:
        return
    if resource_pressure_reasons(required, output_path=output_path):
        wait_for_resource_headroom(
            min_free_percent=required,
            output_path=output_path,
            poll_seconds=poll_seconds,
            timeout_seconds=timeout_seconds,
            logger=logger,
            stage=stage,
        )


def resource_pressure_reasons(min_free_percent: float, *, output_path: Path) -> list[str]:
    """Return human-readable reasons the pipeline should wait."""

    reasons: list[str] = []
    memory_free = physical_memory_available_percent()
    if memory_free is not None and memory_free < min_free_percent:
        reasons.append(ResourceReading("RAM", memory_free, min_free_percent).reason())

    cpu_busy = cpu_busy_percent()
    if cpu_busy is not None:
        cpu_free = max(0.0, 100.0 - cpu_busy)
        if cpu_free < min_free_percent:
            reasons.append(ResourceReading("CPU", cpu_free, min_free_percent).reason())

    for reason in gpu_pressure_reasons(min_free_percent):
        reasons.append(reason)
    return reasons


def physical_memory_available_percent() -> float | None:
    """Return available physical RAM percentage using psutil or Win32 APIs."""

    psutil = optional_import("psutil")
    if psutil is not None:
        try:
            return float(psutil.virtual_memory().available) / float(psutil.virtual_memory().total) * 100.0
        except Exception:
            pass

    if not sys.platform.startswith("win"):
        return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) or status.ullTotalPhys <= 0:
            return None
        return float(status.ullAvailPhys) / float(status.ullTotalPhys) * 100.0
    except Exception:
        return None


def disk_space_warning(path: Path) -> str:
    """Return a warning when output storage is genuinely low, without blocking."""

    available = disk_available_bytes(path)
    if available is None or available >= DISK_WARNING_BYTES:
        return ""
    gib = available / float(1024 ** 3)
    required_gib = DISK_WARNING_BYTES / float(1024 ** 3)
    return f"Resource guard warning: output disk has {gib:.1f} GiB free; recommended minimum is {required_gib:.0f} GiB. Continuing."


def disk_available_bytes(path: Path) -> int | None:
    """Return free bytes for the output location."""

    anchor = path.expanduser().resolve()
    while not anchor.exists() and anchor.parent != anchor:
        anchor = anchor.parent
    try:
        usage = shutil.disk_usage(anchor)
    except OSError:
        return None
    return int(usage.free)


def disk_available_percent(path: Path) -> float | None:
    """Return free disk percentage for diagnostics and older callers."""

    anchor = path.expanduser().resolve()
    while not anchor.exists() and anchor.parent != anchor:
        anchor = anchor.parent
    try:
        usage = shutil.disk_usage(anchor)
    except OSError:
        return None
    if usage.total <= 0:
        return None
    return float(usage.free) / float(usage.total) * 100.0


def cpu_busy_percent() -> float | None:
    """Return current CPU use when psutil is available."""

    psutil = optional_import("psutil")
    if psutil is None:
        return None
    try:
        return float(psutil.cpu_percent(interval=0.25))
    except Exception:
        return None


def gpu_pressure_reasons(min_free_percent: float) -> list[str]:
    """Return GPU pressure reasons when NVIDIA telemetry is available."""

    try:
        result = subprocess.run(
            [
                str(resolve_nvidia_smi()),
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
            env=credential_free_media_environment(),
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []

    reasons: list[str] = []
    for index, line in enumerate(result.stdout.splitlines(), start=1):
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            continue
        try:
            gpu_busy = float(parts[0])
            memory_used = float(parts[1])
            memory_total = float(parts[2])
        except ValueError:
            continue
        gpu_free = max(0.0, 100.0 - gpu_busy)
        if gpu_free < min_free_percent:
            reasons.append(ResourceReading(f"GPU {index}", gpu_free, min_free_percent).reason())
        if memory_total > 0:
            gpu_memory_free = max(0.0, (memory_total - memory_used) / memory_total * 100.0)
            if gpu_memory_free < min_free_percent:
                reasons.append(ResourceReading(f"GPU {index} memory", gpu_memory_free, min_free_percent).reason())
    return reasons


def optional_import(module_name: str):
    try:
        return __import__(module_name)
    except Exception:
        return None
