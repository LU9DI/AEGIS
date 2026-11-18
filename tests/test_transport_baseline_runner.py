from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_transport_baseline.py"


def test_transport_baseline_runner_writes_auditable_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AEGIS_GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("AEGIS_GITHUB_REF", "refs/pull/34/merge")
    monkeypatch.setenv("AEGIS_GITHUB_SHA", "merge-sha")
    monkeypatch.setenv("AEGIS_GITHUB_HEAD_REF", "perf/reproducible-baseline-plan")
    monkeypatch.setenv("AEGIS_GITHUB_BASE_REF", "main")
    monkeypatch.setenv("AEGIS_PR_HEAD_SHA", "head-sha")
    monkeypatch.setenv("AEGIS_PR_BASE_SHA", "base-sha")
    monkeypatch.setenv("AEGIS_GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("AEGIS_GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("AEGIS_GITHUB_WORKFLOW", "Transport baseline regression")
    artifact = tmp_path / "baseline.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--hops", "1",
            "--bytes", "1024",
            "--trials", "1",
            "--latency-samples", "3",
            "--output", str(artifact),
            "--timeout", "30",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(completed.stdout)
    saved = json.loads(artifact.read_text(encoding="utf-8"))

    assert summary["exit_code"] == 0
    assert saved["schema_version"] == 1
    assert saved["source"]["git_commit"]
    assert saved["github_actions"] == {
        "event_name": "pull_request",
        "ref": "refs/pull/34/merge",
        "sha": "merge-sha",
        "head_ref": "perf/reproducible-baseline-plan",
        "base_ref": "main",
        "pr_head_sha": "head-sha",
        "pr_base_sha": "base-sha",
        "run_id": "12345",
        "run_attempt": "2",
        "workflow": "Transport baseline regression",
    }
    assert saved["command"][-1] == "20261009"
    assert saved["benchmark"]["results"]["integrity_verified"] is True
    assert saved["benchmark"]["is_live_internet_test"] is False
    assert saved["benchmark"]["is_anonymity_test"] is False
    assert len(saved["stdout_sha256"]) == 64
    assert json.loads(saved["raw_stdout"])["results"]["integrity_verified"] is True


def test_transport_baseline_runner_refuses_to_overwrite_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "existing.json"
    artifact.write_text('{"preserve": true}\n', encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--hops", "1",
            "--bytes", "1024",
            "--trials", "1",
            "--latency-samples", "3",
            "--output", str(artifact),
            "--timeout", "30",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )

    assert completed.returncode == 3
    assert "Refusing to overwrite" in completed.stderr
    assert artifact.read_text(encoding="utf-8") == '{"preserve": true}\n'


def test_transport_baseline_runner_records_timeout_without_losing_partial_output(monkeypatch) -> None:
    import importlib.util
    from argparse import Namespace
    from subprocess import CompletedProcess, TimeoutExpired

    spec = importlib.util.spec_from_file_location("transport_baseline_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner
    spec.loader.exec_module(runner)

    calls = 0
    killed_groups: list[tuple[int, int]] = []
    killed_processes: list[int] = []

    def fake_run(command, **kwargs):
        nonlocal calls
        calls += 1
        assert command[0] == "git"
        return CompletedProcess(command, 0, stdout="abc123\n", stderr="")

    class FakeProcess:
        pid = 4321
        returncode = -9

        def __init__(self, command, **kwargs):
            self.command = command

        def communicate(self, timeout=None):
            if timeout is not None:
                raise TimeoutExpired(
                    self.command, timeout=timeout,
                    output=b'{"partial":', stderr=b"still running",
                )
            return ('{"partial":', "still running")

        def kill(self):
            killed_processes.append(self.pid)

    # Keep host metadata and process-group termination deterministic.
    monkeypatch.setattr(runner.platform, "platform", lambda: "test-platform")
    monkeypatch.setattr(runner.platform, "machine", lambda: "test-machine")
    monkeypatch.setattr(runner.platform, "processor", lambda: "test-processor")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner.subprocess, "Popen", FakeProcess)
    if runner.os.name == "posix":
        # Process groups are POSIX-only; on Windows the runner falls back to
        # process.kill(), and os.killpg does not exist to be patched.
        monkeypatch.setattr(
            runner.os, "killpg",
            lambda pid, sig: killed_groups.append((pid, sig)),
        )
    result = runner._run(Namespace(
        hops=1,
        payload_bytes=1024,
        trials=1,
        latency_samples=3,
        seed=20261009,
        timeout=1,
    ))

    assert calls == 2
    if runner.os.name == "posix":
        # POSIX termination targets the whole process group.
        assert killed_groups == [(4321, runner.signal.SIGKILL)]
        assert killed_processes == []
    else:
        # Windows falls back to killing the benchmark process itself.
        assert killed_groups == []
        assert killed_processes == [4321]
    assert result["timed_out"] is True
    assert result["exit_code"] == 124
    assert result["raw_stdout"] == '{"partial":'
    assert "still running" in result["stderr"]
    assert "exceeded timeout" in result["stderr"]
    assert len(result["stdout_sha256"]) == 64

