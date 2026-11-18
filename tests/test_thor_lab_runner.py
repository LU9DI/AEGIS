"""End-to-end tests for the THOR lab runner, summary, gates and digest checks.

These tests create their own temporary directories instead of using pytest's
``tmp_path`` fixture so they also run in a sandboxed environment where the
pytest temporary-directory scanner is denied access to the system temp root.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from anonlab.thor_lab.cli import parse_workload_spec
from anonlab.thor_lab.metrics import (
    GATE_TARGET,
    load_run,
    summarize_run,
    verify_run_digest,
)
from anonlab.thor_lab.runner import ArmSpec, run_suite
from anonlab.thor_lab.workloads import WorkloadSpec

HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None


@contextlib.contextmanager
def _workdir() -> Iterator[Path]:
    """Temporary directory for one test.

    ``THOR_LAB_TEST_TMP`` overrides the base directory so the suite also runs in
    a sandbox that only allows nested directories under the workspace. The
    directory is created with ``Path.mkdir`` rather than ``mkdtemp`` because some
    sandboxes deny child creation inside a directory that ``mkdtemp`` created.
    """
    base = Path(os.environ.get("THOR_LAB_TEST_TMP") or tempfile.gettempdir())
    directory = base / f"thor-lab-test-{uuid.uuid4().hex}"
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _lab_run(root: Path, *, trials: int = 3, arms: list[ArmSpec] | None = None):
    return run_suite(
        out_dir=root / "run-01",
        tier="lab",
        arms=arms or [ArmSpec("surface"), ArmSpec("relay3_plain")],
        workloads=[WorkloadSpec(kind="bulk_echo", payload_bytes=32768, chunk_bytes=8192)],
        trials=trials,
        warmup_trials=1,
        seed=424242,
    )


def test_runner_writes_immutable_artifact_set() -> None:
    with _workdir() as root:
        result = asyncio.run(_lab_run(root))
        run_dir = result.out_dir
        for name in ("manifest.json", "trials.jsonl", "run.json", "availability.json"):
            assert (run_dir / name).is_file(), name
        records = [
            json.loads(line) for line in (run_dir / "trials.jsonl").read_text().splitlines() if line
        ]
        assert len(records) == 1 * 2 + 3 * 2  # one warmup round per arm, then three trials per arm
        assert sum(1 for record in records if record["warmup"]) == 2
        assert {record["tier"] for record in records} == {"lab"}
        assert all(record["seed"] == 424242 for record in records)
        assert all(record["status"] == "ok" for record in records)
        assert any(
            record["edge"] and record["edge"]["client_to_upstream_bytes"] > 0 for record in records
        )
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert manifest["tier"] == "lab"
        assert manifest["configuration_digest"]
        assert manifest["environment"]["python"]
        data = load_run(run_dir)
        assert data.measured_arms == ["relay3_plain", "surface"]


def test_runner_refuses_to_reuse_a_non_empty_directory() -> None:
    with _workdir() as root:
        (root / "run-01").mkdir()
        (root / "run-01" / "existing.txt").write_text("do not overwrite", encoding="utf-8")
        with pytest.raises(FileExistsError):
            asyncio.run(_lab_run(root))


def test_summary_records_digest_and_gate_requires_enough_trials() -> None:
    with _workdir() as root:
        result = asyncio.run(_lab_run(root, trials=2))
        data = load_run(result.out_dir)
        summary = summarize_run(data)
        assert summary["raw"]["records"] == 2 * 2 + 1 * 2
        assert summary["raw"]["warmup_records"] == 2
        assert summary["tier"] == "lab"
        assert summary["configuration_digest"] == summary["configuration_digest_recomputed"]
        gates = summary["gates"]
        assert gates and all(gate["status"] == "insufficient_data" for gate in gates)
        assert all(gate["required_paired_trials"] == 3 for gate in gates)


def test_gate_met_matches_the_reported_ratio() -> None:
    with _workdir() as root:
        result = asyncio.run(_lab_run(root, trials=3))
        data = load_run(result.out_dir)
        summary = summarize_run(data)
        gate = next(gate for gate in summary["gates"] if gate["candidate"] == "relay3_plain")
        assert gate["status"] in {"met", "not_met"}
        ratio = gate["goodput_ratio"]["point"]
        assert (gate["status"] == "met") == (ratio >= GATE_TARGET)
        assert gate["paired_trials"] == 3
        assert gate["headroom_needed_factor"] is not None


def test_verify_detects_a_tampered_raw_file() -> None:
    with _workdir() as root:
        result = asyncio.run(_lab_run(root, trials=3))
        data = load_run(result.out_dir)
        summary_path = result.out_dir / "summary.json"
        summary_path.write_text(json.dumps(summarize_run(data)), encoding="utf-8")
        summary = json.loads(summary_path.read_text())
        assert verify_run_digest(load_run(result.out_dir), summary)["ok"] is True

        trials = result.out_dir / "trials.jsonl"
        trials.write_text(trials.read_text() + "\n", encoding="utf-8")
        tampered = verify_run_digest(load_run(result.out_dir), summary)
        assert tampered["ok"] is False
        assert tampered["raw_digest_sha256"]["matches"] is False


def test_runner_records_unavailable_arm_instead_of_dropping_it() -> None:
    with _workdir() as root:
        result = asyncio.run(
            run_suite(
                out_dir=root / "run-tor",
                tier="lab",
                arms=[ArmSpec("surface"), ArmSpec("tor_socks", {"socks_port": 1})],
                workloads=[WorkloadSpec(kind="bulk_echo", payload_bytes=2048, chunk_bytes=2048)],
                trials=1,
                warmup_trials=0,
            )
        )
        assert result.partial is True
        unavailable = json.loads((result.out_dir / "availability.json").read_text())
        assert unavailable and unavailable[0]["backend"] == "tor_socks"
        data = load_run(result.out_dir)
        summary = summarize_run(data)
        assert "tor_socks" not in data.measured_arms
        gate = summary["gates"][0]
        assert gate["status"] == "insufficient_data"
        assert gate["reason"] == "no_candidate_arm_measured_against_surface"


def test_rejects_workload_and_tier_mismatches() -> None:
    with _workdir() as root:
        with pytest.raises(ValueError):
            asyncio.run(
                run_suite(
                    out_dir=root / "bad-1",
                    tier="public",
                    arms=[ArmSpec("surface")],
                    workloads=[WorkloadSpec(kind="bulk_echo", payload_bytes=1024)],
                    trials=1,
                    warmup_trials=0,
                )
            )
        with pytest.raises(ValueError):
            asyncio.run(
                run_suite(
                    out_dir=root / "bad-2",
                    tier="lab",
                    arms=[ArmSpec("surface")],
                    workloads=[
                        WorkloadSpec(kind="http_get", operations=1, http_host="example.com")
                    ],
                    trials=1,
                    warmup_trials=0,
                )
            )
        with pytest.raises(ValueError):
            WorkloadSpec(kind="http_get", operations=1)  # requires http_host


def test_workload_spec_parsing_matches_grammar() -> None:
    bulk = parse_workload_spec("bulk_echo:131072", chunk_bytes=4096, in_flight=2)
    assert bulk.kind == "bulk_echo" and bulk.payload_bytes == 131072
    assert bulk.chunk_bytes == 4096 and bulk.max_in_flight == 2

    rtt = parse_workload_spec("small_rtt:512x10")
    assert rtt.kind == "small_rtt" and rtt.payload_bytes == 512 and rtt.operations == 10

    parallel = parse_workload_spec("parallel_bulk:8192x4")
    assert parallel.streams == 4 and parallel.payload_bytes == 8192

    http = parse_workload_spec("http_get:2", http_host="example.com", http_path="/x")
    assert http.kind == "http_get" and http.operations == 2 and http.http_host == "example.com"
    ranged = parse_workload_spec(
        "http_get:1", http_host="example.com", http_headers=(("Range", "bytes=0-1023"),)
    )
    assert ranged.http_headers == (("Range", "bytes=0-1023"),)

    with pytest.raises(ValueError):
        parse_workload_spec("http_get:2")
    with pytest.raises(ValueError):
        parse_workload_spec("teleport:1")

    sweep = parse_workload_spec("bulk_echo:262144@65536i4")
    assert sweep.chunk_bytes == 65536 and sweep.max_in_flight == 4
    assert sweep.label.endswith("@c65536i4")
    default_label = parse_workload_spec("bulk_echo:262144").label
    assert default_label != sweep.label, "chunking must be part of the workload identity"
    with pytest.raises(ValueError):
        parse_workload_spec("bulk_echo:1@65536")
