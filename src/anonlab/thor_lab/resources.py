"""Dependency-free CPU and memory sampling for benchmark trials.

The repository has no ``psutil`` dependency and must keep working in the
crypto-free virtualenv, so process resources are read from the standard library
and, on Windows, from ``psapi`` through :mod:`ctypes`.

Scope of the numbers:

* CPU is *process-wide* (all threads and all relays hosted in this process), so
  it is comparable between arms of the same harness but is not a per-connection
  cost;
* memory is the resident working set and its peak for the whole process, so it
  includes the interpreter and every in-process relay;
* the kernel clock resolution limits short trials; a trial shorter than a few
  hundred milliseconds should report CPU as "not_resolved" rather than 0.0.
"""
from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass

__all__ = ["ResourceSnapshot", "ResourceDelta", "snapshot", "delta", "available_detail"]


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    monotonic_ns: int
    process_cpu_ns: int
    user_s: float
    system_s: float
    rss_kb: int | None
    peak_rss_kb: int | None


@dataclass(frozen=True, slots=True)
class ResourceDelta:
    wall_s: float
    cpu_process_s: float
    cpu_user_s: float
    cpu_system_s: float
    cpu_fraction_of_one_core: float | None
    rss_start_kb: int | None
    rss_end_kb: int | None
    peak_rss_kb: int | None
    memory_detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "wall_s": self.wall_s,
            "cpu_process_s": self.cpu_process_s,
            "cpu_user_s": self.cpu_user_s,
            "cpu_system_s": self.cpu_system_s,
            "cpu_fraction_of_one_core": self.cpu_fraction_of_one_core,
            "rss_start_kb": self.rss_start_kb,
            "rss_end_kb": self.rss_end_kb,
            "peak_rss_kb": self.peak_rss_kb,
            "memory_detail": self.memory_detail,
        }


def _windows_memory() -> tuple[int | None, int | None, str]:
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        # The pseudo-handle is -1 on 64-bit Windows; without an explicit restype
        # ctypes truncates it to a 32-bit int and the call fails with
        # ERROR_INVALID_HANDLE, which would silently disable memory reporting.
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        )
        if not ok:
            return None, None, "psapi_unavailable"
        return (
            int(counters.WorkingSetSize) // 1024,
            int(counters.PeakWorkingSetSize) // 1024,
            "windows_psapi_working_set",
        )
    except Exception:  # noqa: BLE001 - never fail a trial because sampling failed
        return None, None, "windows_psapi_error"


def _posix_memory() -> tuple[int | None, int | None, str]:
    status_path = "/proc/self/status"
    try:
        with open(status_path, encoding="ascii") as handle:
            values: dict[str, int] = {}
            for line in handle:
                if line.startswith(("VmRSS:", "VmHWM:")):
                    name, _, rest = line.partition(":")
                    values[name.strip()] = int(rest.split()[0])
        if "VmRSS" in values:
            return values.get("VmRSS"), values.get("VmHWM"), "proc_self_status"
    except OSError:
        pass
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        divisor = 1024 if platform.system() == "Darwin" else 1
        peak = int(usage.ru_maxrss) // divisor
        return None, peak, "getrusage_maxrss"
    except Exception:  # noqa: BLE001
        return None, None, "unavailable"


def _memory() -> tuple[int | None, int | None, str]:
    if os.name == "nt":
        return _windows_memory()
    return _posix_memory()


def available_detail() -> dict[str, object]:
    """Describe what this host can actually sample (used in the manifest)."""
    rss, peak, detail = _memory()
    return {
        "platform": platform.system(),
        "memory_detail": detail,
        "rss_kb": rss,
        "peak_rss_kb": peak,
        "cpu_detail": "time.process_time_ns()+os.times() process-wide",
    }


def snapshot() -> ResourceSnapshot:
    times = os.times()
    rss_kb, peak_rss_kb, _detail = _memory()
    return ResourceSnapshot(
        monotonic_ns=time.perf_counter_ns(),
        process_cpu_ns=time.process_time_ns(),
        user_s=float(times.user),
        system_s=float(times.system),
        rss_kb=rss_kb,
        peak_rss_kb=peak_rss_kb,
    )


def delta(before: ResourceSnapshot, after: ResourceSnapshot) -> ResourceDelta:
    """Differences between two snapshots captured around one trial."""
    if after.monotonic_ns < before.monotonic_ns:
        raise ValueError("resource snapshots are out of order")
    wall_s = (after.monotonic_ns - before.monotonic_ns) / 1_000_000_000
    cpu_process_s = max(0, after.process_cpu_ns - before.process_cpu_ns) / 1_000_000_000
    user_s = max(0.0, after.user_s - before.user_s)
    system_s = max(0.0, after.system_s - before.system_s)
    fraction = cpu_process_s / wall_s if wall_s > 0 else None
    _rss, peak, detail = _memory()
    return ResourceDelta(
        wall_s=wall_s,
        cpu_process_s=round(cpu_process_s, 6),
        cpu_user_s=round(user_s, 6),
        cpu_system_s=round(system_s, 6),
        cpu_fraction_of_one_core=None if fraction is None else round(fraction, 6),
        rss_start_kb=before.rss_kb,
        rss_end_kb=after.rss_kb,
        peak_rss_kb=after.peak_rss_kb if after.peak_rss_kb is not None else peak,
        memory_detail=detail,
    )
