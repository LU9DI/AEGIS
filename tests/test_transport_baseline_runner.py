from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_transport_baseline.py"


def test_transport_baseline_runner_writes_auditable_artifact(tmp_path: Path) -> None:
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
