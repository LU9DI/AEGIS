"""Unit tests for THOR lab provenance and resource sampling."""
from __future__ import annotations

import json
import re

import pytest

from anonlab.thor_lab.provenance import (
    canonical_digest,
    code_revision,
    environment,
    manifest,
    repository_root,
)
from anonlab.thor_lab.resources import available_detail, delta, snapshot


def test_canonical_digest_is_key_order_independent() -> None:
    assert canonical_digest({"a": 1, "b": 2}) == canonical_digest({"b": 2, "a": 1})
    assert canonical_digest({"a": 1}) != canonical_digest({"a": 2})
    assert len(canonical_digest({"a": 1})) == 64


def test_repository_root_and_code_revision_shape() -> None:
    root = repository_root()
    assert root is not None and (root / ".git").exists()
    revision = code_revision(root)
    if revision["revision"] is None:
        pytest.skip("git is not available in this environment")
    assert re.fullmatch(r"[0-9a-f]{40}", str(revision["revision"]))
    assert isinstance(revision["dirty"], bool)
    assert revision["source"] == "git"


def test_environment_reports_interpreter_facts() -> None:
    env = environment()
    assert env["python"]
    assert env["python_implementation"] == "CPython"
    assert isinstance(env["cpu_count"], int) and env["cpu_count"] >= 1
    assert "dependencies" in env


def test_manifest_records_revision_digest_and_claim_scope() -> None:
    configuration = {"arms": ["surface"], "workloads": [{"kind": "bulk_echo"}]}
    payload = manifest(configuration=configuration, seed=1234, tier="lab")
    assert payload["schema_version"] == 1
    assert payload["tier"] == "lab"
    assert payload["seed"] == 1234
    assert payload["configuration_digest"] == canonical_digest(configuration)
    assert "does not establish anonymity" in str(payload["claim_scope"])
    json.dumps(payload)  # must be serializable as written to disk
    with pytest.raises(ValueError):
        manifest(configuration={}, seed=1, tier="wan")


def test_resource_delta_is_non_negative_and_time_ordered() -> None:
    before = snapshot()
    total = 0
    for index in range(200_000):
        total += index
    after = snapshot()
    result = delta(before, after)
    assert result.wall_s >= 0.0
    assert result.cpu_process_s >= 0.0
    assert result.cpu_user_s >= 0.0
    assert result.cpu_system_s >= 0.0
    assert result.memory_detail
    with pytest.raises(ValueError):
        delta(after, before)


def test_available_detail_states_what_is_measured() -> None:
    detail = available_detail()
    assert detail["memory_detail"]
    assert "cpu_detail" in detail


def test_timer_resolution_control_is_recorded_and_released() -> None:
    from anonlab.thor_lab.timers import (
        begin_high_resolution_timer,
        end_high_resolution_timer,
        high_resolution_timer,
        timer_resolution_support,
    )

    support = timer_resolution_support()
    assert support["mechanism"]
    state = begin_high_resolution_timer(1)
    assert "applied" in state and "reason" in state
    if support["supported"]:
        assert state["applied"] is True
        assert state["period_ms"] == 1
    end_high_resolution_timer()
    with high_resolution_timer(1) as nested:
        assert "applied" in nested
    with pytest.raises(ValueError):
        with high_resolution_timer(99):
            pass
