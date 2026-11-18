"""Regression coverage for the offline route-selection demo.

The demo previously imported a ``GeoPoint`` symbol that no longer exists, so it
was broken for several versions without any test noticing. These assertions keep
it importable, runnable, and honest about being synthetic.
"""
from __future__ import annotations

import json

from anonlab.route_selection_demo import main, run_demo


def test_demo_reports_a_synthetic_plan_without_live_claims() -> None:
    payload = run_demo()
    metadata = payload["metadata"]
    assert metadata["is_synthetic_demo"] is True
    assert metadata["is_live_network_test"] is False
    assert metadata["is_security_proof"] is False

    selection = payload["selection"]
    assert selection["relays"] == ["guard-pinned-sp", "middle-sp", "exit-sp"]
    assert selection["is_live_network_test"] is False
    assert selection["measured_link_count"] >= 1
    assert selection["bottleneck_mbps"] > 0


def test_demo_cli_writes_the_same_plan_to_a_file(tmp_path) -> None:
    target = tmp_path / "route-demo.json"
    assert main(["--output", str(target)]) == 0

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["metadata"]["is_synthetic_demo"] is True
    assert payload["selection"]["relays"] == run_demo()["selection"]["relays"]
