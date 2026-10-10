from __future__ import annotations

import unittest
from dataclasses import replace

from anonlab.model import ExperimentConfig
from anonlab.profiles import (
    CANDIDATE_FAST, CANDIDATE_FIXED_RATE, CANDIDATE_NOISE, DIRECT, TOR_LIKE
)
from anonlab.simulator import generate_workload, run_suite, simulate_profile


class SimulatorTests(unittest.TestCase):
    def test_workload_is_reproducible(self) -> None:
        config = ExperimentConfig(duration_s=20, request_rate_per_s=1.0, seed=1234)
        self.assertEqual(generate_workload(config), generate_workload(config))

    def test_same_seed_produces_same_suite(self) -> None:
        config = ExperimentConfig(duration_s=30, request_rate_per_s=1.3, seed=55)
        a = [result.to_dict() for result in run_suite(config, (DIRECT, TOR_LIKE, CANDIDATE_FAST))]
        b = [result.to_dict() for result in run_suite(config, (DIRECT, TOR_LIKE, CANDIDATE_FAST))]
        self.assertEqual(a, b)

    def test_candidate_hypothesis_uses_more_capacity_than_onion_reference(self) -> None:
        self.assertLess(TOR_LIKE.bottleneck_mbps, CANDIDATE_FAST.bottleneck_mbps)

    def test_fixed_rate_model_has_nonzero_overhead(self) -> None:
        config = ExperimentConfig(duration_s=60, request_rate_per_s=1.0, seed=2026)
        result = simulate_profile(CANDIDATE_FIXED_RATE, config)
        self.assertGreater(result.traffic_overhead_ratio, 0)
        self.assertEqual(result.fixed_rate_mbps, 20)

    def test_fixed_rate_reduces_simple_correlation_but_costs_more_bandwidth(self) -> None:
        config = ExperimentConfig(duration_s=90, request_rate_per_s=1.4, seed=20261009)
        baseline = simulate_profile(CANDIDATE_FAST, config)
        padded = simulate_profile(CANDIDATE_FIXED_RATE, config)
        self.assertIsNotNone(baseline.max_lag_pearson)
        self.assertIsNotNone(padded.max_lag_pearson)
        self.assertLess(padded.max_lag_pearson, baseline.max_lag_pearson)
        self.assertGreater(padded.traffic_overhead_ratio, 1.0)

    def test_independent_noise_lowers_simple_correlation_and_is_costed(self) -> None:
        config = ExperimentConfig(duration_s=90, request_rate_per_s=1.4, seed=20261009)
        no_cover_profile = replace(
            CANDIDATE_NOISE, cover_mode="none", cover_ratio_per_edge=0.0
        )
        baseline = simulate_profile(no_cover_profile, config)
        noisy = simulate_profile(CANDIDATE_NOISE, config)
        self.assertIsNotNone(baseline.max_lag_pearson)
        self.assertIsNotNone(noisy.max_lag_pearson)
        self.assertLess(noisy.max_lag_pearson, baseline.max_lag_pearson)
        self.assertGreater(noisy.cover_mb, 0.0)
        self.assertAlmostEqual(noisy.traffic_overhead_ratio, 3.0, places=4)

    def test_empty_workload_is_rejected(self) -> None:
        config = ExperimentConfig(duration_s=0.01, request_rate_per_s=0.01, seed=1)
        with self.assertRaises(ValueError):
            simulate_profile(DIRECT, config, flows=[])


if __name__ == "__main__":
    unittest.main()
