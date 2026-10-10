from __future__ import annotations

import unittest

from anonlab.network_impairment import DEFAULT_PROFILES
from anonlab.telescoping import WINDOW_UPDATE_BATCH_BYTES, WINDOW_UPDATE_MAX_DELAY_SECONDS
from anonlab.window_update_timer_benchmark import (
    CONTROL_TIMER_MS,
    _validate_timer_values,
    run_window_update_timer_sensitivity,
    summarize_timer_sensitivity,
)


class WindowUpdateTimerBenchmarkTests(unittest.IsolatedAsyncioTestCase):
    def test_timer_validation_is_bounded_unique_and_requires_control(self) -> None:
        self.assertEqual(_validate_timer_values([0.5, 2, 5]), (0.5, 2.0, 5.0))
        with self.assertRaisesRegex(ValueError, "non-empty"):
            _validate_timer_values([])
        with self.assertRaisesRegex(ValueError, "duplicates"):
            _validate_timer_values([2, 2])
        with self.assertRaisesRegex(ValueError, "include the default"):
            _validate_timer_values([0.5, 5])
        for value in (0, 0.09, 100.01, float("inf"), float("nan"), True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite and within"):
                _validate_timer_values([2, value])
        self.assertEqual(CONTROL_TIMER_MS, 2.0)
        self.assertEqual(WINDOW_UPDATE_MAX_DELAY_SECONDS, 0.002)

    def test_paired_summary_reports_timer_deltas_against_two_ms_control(self) -> None:
        runs = []
        for trial, control_rate, candidate_rate in ((1, 100.0, 110.0), (2, 120.0, 108.0)):
            runs.append({
                "trial": trial, "window_update_max_delay_ms": 2.0,
                "bulk_goodput_mbps": control_rate, "bulk_completion_ms": 10.0,
            })
            runs.append({
                "trial": trial, "window_update_max_delay_ms": 0.5,
                "bulk_goodput_mbps": candidate_rate, "bulk_completion_ms": 11.0,
            })
        summary = summarize_timer_sensitivity(runs)
        metric = summary["0.5"]["metrics"]["bulk_goodput_mbps"]
        self.assertEqual(metric["paired_trials"], 2)
        self.assertEqual(metric["wins_vs_control"], 1)
        self.assertEqual(metric["losses_vs_control"], 1)
        self.assertAlmostEqual(metric["median_paired_trial_delta_percent"], 0.0, places=6)

    async def test_timer_sensitivity_smoke_checks_integrity_configuration_and_cleanup(self) -> None:
        result = await run_window_update_timer_sensitivity(
            profile_name="loopback",
            trials=1,
            timer_values_ms=(0.5, 2.0),
            batch_bytes=WINDOW_UPDATE_BATCH_BYTES,
            bulk_bytes=64 * 1024,
            interactive_requests=2,
            request_bytes=64,
            request_gap_ms=250,
            stagger_after_ms=1,
            write_chunk_bytes=4096,
            pipeline_depth=2,
            seed=78,
        )
        self.assertEqual(len(result["runs"]), 2)
        self.assertEqual(result["config"]["request_gap_ms"], 250.0)
        self.assertTrue(result["all_integrity_cleanup_configuration_and_bounds_checks_passed"])
        for row in result["runs"]:
            self.assertTrue(row["integrity_verified"])
            self.assertTrue(row["resources_closed"])
            self.assertTrue(row["configured_timer_matches"])
            self.assertEqual(row["window_update_batch_bytes"], WINDOW_UPDATE_BATCH_BYTES)
            self.assertIn(f"{row['window_update_max_delay_ms']:g}", result["summary"])


if __name__ == "__main__":
    unittest.main()
