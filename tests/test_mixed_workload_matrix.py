from __future__ import annotations

import unittest

from anonlab.mixed_workload_matrix import summarize_paired_runs


class MixedWorkloadMatrixTests(unittest.TestCase):
    def test_paired_summary_counts_directional_wins(self) -> None:
        rows = [
            {"trial": 1, "scheduler": "baseline", "bulk_goodput_mbps": 10.0, "early_interactive_rtt_p50_ms": 50.0},
            {"trial": 1, "scheduler": "round_robin", "bulk_goodput_mbps": 9.0, "early_interactive_rtt_p50_ms": 40.0},
            {"trial": 2, "scheduler": "baseline", "bulk_goodput_mbps": 10.0, "early_interactive_rtt_p50_ms": 40.0},
            {"trial": 2, "scheduler": "round_robin", "bulk_goodput_mbps": 11.0, "early_interactive_rtt_p50_ms": 40.0},
        ]
        summary = summarize_paired_runs(rows)
        self.assertEqual(summary["bulk_goodput_mbps"]["round_robin_wins"], 1)
        self.assertEqual(summary["bulk_goodput_mbps"]["baseline_wins"], 1)
        self.assertAlmostEqual(summary["bulk_goodput_mbps"]["median_paired_delta_percent"], 0.0)
        self.assertEqual(summary["early_interactive_rtt_p50_ms"]["round_robin_wins"], 1)
        self.assertEqual(summary["early_interactive_rtt_p50_ms"]["ties"], 1)

    def test_missing_scheduler_pair_is_rejected(self) -> None:
        rows = [{"trial": 1, "scheduler": "baseline", "bulk_goodput_mbps": 10.0}]
        with self.assertRaisesRegex(ValueError, "missing paired"):
            summarize_paired_runs(rows)

    def test_zero_baseline_does_not_emit_nonfinite_delta(self) -> None:
        rows = [
            {"trial": 1, "scheduler": "baseline", "bulk_goodput_mbps": 0.0},
            {"trial": 1, "scheduler": "round_robin", "bulk_goodput_mbps": 1.0},
        ]
        summary = summarize_paired_runs(rows)
        self.assertIsNone(summary["bulk_goodput_mbps"]["median_paired_delta_percent"])
        self.assertEqual(summary["bulk_goodput_mbps"]["round_robin_wins"], 1)


if __name__ == "__main__":
    unittest.main()
