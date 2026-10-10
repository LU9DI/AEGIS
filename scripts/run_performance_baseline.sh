#!/usr/bin/env bash
# Repeatable local AEGIS characterization suite. This is not a WAN benchmark.
set -euo pipefail

TRIALS="${TRIALS:-5}"
PAYLOAD_BYTES="${PAYLOAD_BYTES:-65536}"
SEED="${SEED:-20261009}"
PROFILE="${PROFILE:-metro}"
OUT_DIR="${OUT_DIR:-artifacts/performance-baseline-$(date -u +%Y%m%dT%H%M%SZ)}"

[[ "$TRIALS" =~ ^[1-9][0-9]*$ ]] || { echo "TRIALS must be a positive integer" >&2; exit 2; }
(( TRIALS <= 10 )) || { echo "TRIALS must be <= 10 for the mixed-workload matrix" >&2; exit 2; }
[[ "$PAYLOAD_BYTES" =~ ^[1-9][0-9]*$ ]] || { echo "PAYLOAD_BYTES must be a positive integer" >&2; exit 2; }
(( PAYLOAD_BYTES <= 1048576 )) || { echo "PAYLOAD_BYTES must be <= 1048576" >&2; exit 2; }
[[ "$SEED" =~ ^[0-9]+$ ]] || { echo "SEED must be a non-negative integer" >&2; exit 2; }
mkdir -p "$OUT_DIR"

if ! python -c 'import anonlab, cryptography' >/dev/null 2>&1; then
  echo "Missing package/dependency. From the repository root run: python -m pip install -e '.[onion-lab]' pytest" >&2
  exit 2
fi
if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "Run this script from inside a Git checkout." >&2
  exit 2
fi

export AEGIS_OUT_DIR="$OUT_DIR" AEGIS_TRIALS="$TRIALS" AEGIS_PAYLOAD_BYTES="$PAYLOAD_BYTES"
export AEGIS_SEED="$SEED" AEGIS_PROFILE="$PROFILE"
python - <<'PY'
import json, os, platform, subprocess, sys
from pathlib import Path

def command(args):
    try:
        return subprocess.run(args, check=False, capture_output=True, text=True).stdout.strip()
    except OSError:
        return None

out = Path(os.environ["AEGIS_OUT_DIR"])
try:
    commit = command(["git", "rev-parse", "HEAD"])
    dirty = bool(command(["git", "status", "--porcelain"]))
except Exception:
    commit, dirty = None, None
cpu_model = None
try:
    for line in Path("/proc/cpuinfo").read_text(errors="replace").splitlines():
        if line.lower().startswith(("model name", "hardware")):
            cpu_model = line.split(":", 1)[-1].strip()
            break
except OSError:
    pass
memory_kib = None
try:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            memory_kib = int(line.split()[1])
            break
except (OSError, ValueError, IndexError):
    pass
manifest = {
    "schema_version": 1,
    "project": "AEGIS",
    "experiment": "local characterization suite; not a WAN baseline",
    "git_commit": commit,
    "git_worktree_dirty": dirty,
    "python": sys.version,
    "platform": platform.platform(),
    "system": platform.system(),
    "release": platform.release(),
    "machine": platform.machine(),
    "cpu_model": cpu_model,
    "logical_cpu_count": os.cpu_count(),
    "memory_total_kib_linux_only": memory_kib,
    "pip_freeze": command([sys.executable, "-m", "pip", "freeze"]),
    "config": {
        "trials": int(os.environ["AEGIS_TRIALS"]),
        "payload_bytes": int(os.environ["AEGIS_PAYLOAD_BYTES"]),
        "seed": int(os.environ["AEGIS_SEED"]),
        "profile": os.environ["AEGIS_PROFILE"],
    },
    "limitations": [
        "All current harnesses are local/loopback experiments; this suite does not measure a real WAN.",
        "Telescoping and impairment harnesses are fixed at three hops.",
        "No complete CPU/RSS or retransmission measurement is collected by this script.",
        "Mixed-workload trials are small exploratory paired comparisons, not a security proof.",
        "A dirty worktree is recorded but is not rejected; archive the exact source diff with the results if dirty.",
    ],
}
(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY

echo "Writing raw JSON results to $OUT_DIR"
python -m anonlab.telescoping_benchmark \
  --bytes "$PAYLOAD_BYTES" --trials "$TRIALS" --seed "$SEED" \
  --output "$OUT_DIR/telescoping.json"

# Repeat the shaped three-hop comparison as independent whole-run samples.
for ((trial=1; trial<=TRIALS; trial++)); do
  trial_seed=$((SEED + trial))
  python -m anonlab.network_impairment_benchmark \
    --profile "$PROFILE" --streams 4 --payload-bytes "$PAYLOAD_BYTES" \
    --seed "$trial_seed" --pipeline-depth 1 \
    --output "$OUT_DIR/network-impairment-trial-$trial.json"
done

python -m anonlab.mixed_workload_matrix \
  --trials "$TRIALS" --seed "$SEED" \
  --output "$OUT_DIR/mixed-workload-matrix.json"

echo "Completed local characterization suite. Review manifest.json and every raw JSON result."
echo "Do not describe these loopback results as real-WAN performance or proof of anonymity."
