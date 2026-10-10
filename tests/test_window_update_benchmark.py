from __future__ import annotations

import unittest

from anonlab.network_impairment import DEFAULT_PROFILES
from anonlab.telescoping import WINDOW_UPDATE_BATCH_BYTES
from anonlab.window_update_benchmark import (
    _validate_batch_sizes,
    run_window_update_sensitivity,
    summarize_batch_sensitivity,
)


class WindowUpdateBenchmarkTests(unittest.IsolatedAsyncioTestCase):
    def test_batch_size_validation_is_bounded_and_requires_default_control(self) -> None:
        self.assertEqual(_validate_batch_sizes([16384, 65536]), (16384, 65536))
        with self.assertRaisesRegex(ValueError, "non-empty"):
            _validate_batch_sizes([])
        with self.assertRaisesRegex(ValueError, "duplicates"):
            _validate_batch_sizes([65536, 65536])
        with self.assertRaisesRegex(ValueError, "include the default"):
            _validate_batch_sizes([16384, 32768])
        with self.assertRaisesRegex(ValueError, "within 1..262144"):
            _validate_batch_sizes([262145, 65536])
        with self.assertRaisesRegex(ValueError, "within 1..262144"):
            _validate_batch_sizes([True, 65536])

    def test_paired_summary_uses_default_threshold_as_control(self) -> None:
        metrics = {
            "bulk_goodput_mbps": 100.0,
            "bulk_completion_ms": 10.0,
            "early_interactive_rtt_p50_ms": 2.0,
            "early_interactive_rtt_p95_ms": 3.0,
            "late_interactive_rtt_p50_ms": 2.5,
            "late_interactive_rtt_p95_ms": 4.0,
            "window_update_commands": 10.0,
            "flow_pause_over_1ms_count": 2.0,
            "flow_pause_over_1ms_total_ms": 5.0,
        }
        runs = []
        for trial, factor in ((1, 1.1), (2, 0.9)):
            control = {"trial": trial, "window_update_batch_bytes": WINDOW_UPDATE_BATCH_BYTES, **metrics}
            candidate = {"trial": trial, "window_update_batch_bytes": 32768, **{
                key: (value * factor if key == "bulk_goodput_mbps" else value)
                for key, value in metrics.items()
            }}
            runs.extend((control, candidate))
        result = summarize_batch_sensitivity(runs)
        self.assertEqual(result[str(WINDOW_UPDATE_BATCH_BYTES)]["metrics"]["bulk_goodput_mbps"]["paired_trials"], 2)
        self.assertEqual(result[str(WINDOW_UPDATE_BATCH_BYTES)]["metrics"]["bulk_goodput_mbps"]["median_paired_trial_delta_percent"], 0.0)
        self.assertEqual(result["32768"]["metrics"]["bulk_goodput_mbps"]["wins_vs_control"], 1)
        self.assertEqual(result["32768"]["metrics"]["bulk_goodput_mbps"]["losses_vs_control"], 1)

    async def test_sensitivity_smoke_checks_integrity_cleanup_and_configuration(self) -> None:
        result = await run_window_update_sensitivity(
            profile_name="loopback",
            trials=1,
            batch_sizes=(16 * 1024, WINDOW_UPDATE_BATCH_BYTES),
            bulk_bytes=32 * 1024,
            interactive_requests=2,
            request_bytes=64,
            request_gap_ms=0,
            stagger_after_ms=1,
            write_chunk_bytes=4096,
            pipeline_depth=2,
            seed=77,
        )
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["config"]["batch_sizes_bytes"], [16384, 65536])
        self.assertTrue(result["all_integrity_cleanup_and_bounds_checks_passed"])
        self.assertEqual(len(result["runs"]), 2)
        for run in result["runs"]:
            self.assertTrue(run["integrity_verified"])
            self.assertTrue(run["relay_observability_check"])
            self.assertTrue(run["resources_closed"])
            self.assertTrue(run["all_relays_event_buffers_bounded"])
            self.assertGreaterEqual(run["window_update_commands"], 0)
            self.assertIn(str(run["window_update_batch_bytes"]), result["summary"])


if __name__ == "__main__":
    unittest.main()
