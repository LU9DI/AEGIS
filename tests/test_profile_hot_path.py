from __future__ import annotations

import cProfile

from anonlab.profile_hot_path import _profiled_functions


def test_profile_summary_includes_selected_crypto_and_descriptor_functions() -> None:
    profile = cProfile.Profile()

    def seal() -> int:
        value = 1 + 1
        return value

    profile.enable()
    for _ in range(100):
        assert seal() == 2
    profile.disable()
    # Summary extraction is deliberately a whitelist so it never collects
    # function arguments, application contents, or arbitrary local variables.
    rows = _profiled_functions(profile)
    seal_row = next(row for row in rows if row["function"] == "seal")
    assert seal_row["calls"] == 100


def test_profile_summary_does_not_capture_payloads_or_locals() -> None:
    profile = cProfile.Profile()
    profile.enable()
    sum(range(10))
    profile.disable()
    rows = _profiled_functions(profile)
    assert all("payload" not in row for row in rows)
    assert all(set(row) == {
        "file", "line", "function", "primitive_calls", "calls", "self_seconds", "cumulative_seconds"
    } for row in rows)
