"""Raise the Windows timer resolution for the duration of a measurement run.

Windows schedules ``asyncio.sleep`` on the system timer tick, which defaults to
~15.6 ms. The repository's link shaper implements one-way delay with
``asyncio.sleep``, so without raising the resolution a nominal 5 ms metro profile
cannot be realized and every arm's latency is inflated by the same multi-tick
floor.

Raising the timer is a measurement-environment control, not a protocol change: it
is applied to the whole suite (all arms), recorded in the run manifest, and
released at the end of the run. On non-Windows platforms it is a no-op.

The begin/end pair is also exposed directly because the runner starts it before
writing the manifest (which must record whether it was applied) and ends it in
its cleanup path.
"""
from __future__ import annotations

import contextlib
import ctypes
import os
from collections.abc import Iterator

__all__ = [
    "begin_high_resolution_timer",
    "end_high_resolution_timer",
    "high_resolution_timer",
    "timer_resolution_support",
]

_DEFAULT_PERIOD_MS = 1
_active_period_ms: int | None = None


def timer_resolution_support() -> dict[str, object]:
    return {
        "platform": os.name,
        "supported": os.name == "nt",
        "mechanism": "winmm.timeBeginPeriod" if os.name == "nt" else "no-op",
    }


def _winmm() -> object | None:
    if os.name != "nt":
        return None
    try:
        winmm = ctypes.WinDLL("winmm")
        winmm.timeBeginPeriod.argtypes = [ctypes.c_uint]
        winmm.timeBeginPeriod.restype = ctypes.c_uint
        winmm.timeEndPeriod.argtypes = [ctypes.c_uint]
        winmm.timeEndPeriod.restype = ctypes.c_uint
        return winmm
    except Exception:  # noqa: BLE001 - never fail a run because of this
        return None


def begin_high_resolution_timer(period_ms: int = _DEFAULT_PERIOD_MS) -> dict[str, object]:
    """Try to raise the timer resolution; returns what was actually applied."""
    global _active_period_ms
    if not 1 <= int(period_ms) <= 16:
        raise ValueError("period_ms must be within 1..16")
    if os.name != "nt":
        return {"applied": False, "period_ms": None, "reason": "not_windows"}
    winmm = _winmm()
    if winmm is None:
        return {"applied": False, "period_ms": None, "reason": "winmm_unavailable"}
    try:
        result = winmm.timeBeginPeriod(int(period_ms))  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        return {"applied": False, "period_ms": None, "reason": f"{type(exc).__name__}: {exc}"}
    applied = int(result) == 0
    if applied:
        _active_period_ms = int(period_ms)
    return {
        "applied": applied,
        "period_ms": int(period_ms) if applied else None,
        "reason": "ok" if applied else f"timeBeginPeriod returned {result}",
    }


def end_high_resolution_timer() -> None:
    """Release a resolution raise started by :func:`begin_high_resolution_timer`."""
    global _active_period_ms
    period = _active_period_ms
    _active_period_ms = None
    if period is None:
        return
    winmm = _winmm()
    if winmm is None:
        return
    with contextlib.suppress(Exception):
        winmm.timeEndPeriod(period)  # type: ignore[attr-defined]


@contextlib.contextmanager
def high_resolution_timer(period_ms: int = _DEFAULT_PERIOD_MS) -> Iterator[dict[str, object]]:
    """Best-effort raise of the OS timer resolution; yields what was applied."""
    state = begin_high_resolution_timer(period_ms)
    try:
        yield state
    finally:
        end_high_resolution_timer()
