"""Render the P2 campaign summary as Markdown tables (no numbers are invented).

Usage:
    python experiments/thor-p2-lab/analyze_campaign.py experiments/thor-p2-lab/campaign-01
"""
from __future__ import annotations

import json
import pathlib
import sys


def fmt(value, digits=2):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def ratio_cell(cell):
    if not cell or cell.get("median") is None:
        return "—"
    return f"{cell['median']:.3f} [{cell['ci_low']:.3f}, {cell['ci_high']:.3f}]"


def main(directory: pathlib.Path) -> int:
    document = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    summary = document["summary"]
    meta = document["metadata"]
    print(f"# Campaign {directory.name}\n")
    print(f"- commit: `{meta['git']['commit']}` (dirty: {meta['git']['dirty']})")
    print(f"- tier: {document['tier']}; trials/cell: {meta['trials_per_cell']}; warmups: {meta['warmups_per_cell']}")
    print(f"- duration: {meta['duration_s']:.1f}s; failures: {len(document['failures'])}\n")

    for workload in meta["workloads"]:
        print(f"## {workload}\n")
        print("| arm | goodput Mb/s (med) | TTFB ms | p95 ms | p99 ms | down-wait ms | credit-wait ms | events | V | AEAD/KiB |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for arm in meta["arms"]:
            cell = summary["cells"].get(f"{workload}/{arm}")
            if not cell:
                continue
            print(
                f"| `{arm}` | {fmt(cell['goodput_mbps_median'])} | {fmt(cell['ttfb_ms_median'])} | "
                f"{fmt(cell['read_latency_ms_p95_median'])} | {fmt(cell['read_latency_ms_p99_median'])} | "
                f"{fmt(cell['downstream_response_wait_ms_median'])} | "
                f"{fmt(cell['flow_credit_wait_ms_median'])} | "
                f"{fmt(cell['client_visible_events_median'], 0)} | {fmt(cell['window_updates_median'], 0)} | "
                f"{fmt(cell['aead_ops_per_kib_median'], 3)} |"
            )
        print("\npaired vs control (median ratio [95% CI], 1.0 = no change):\n")
        print("| arm | goodput | wall | p95 | p99 | down-wait | credit-wait | wins/losses |")
        print("|---|---|---|---|---|---|---|---|")
        for arm in meta["arms"]:
            if arm == "control":
                continue
            cell = summary["paired"].get(f"{workload}/{arm}")
            if not cell:
                continue
            print(
                f"| `{arm}` | {ratio_cell(cell['goodput_ratio'])} | {ratio_cell(cell['wall_ratio'])} | "
                f"{ratio_cell(cell['read_latency_p95_ratio'])} | {ratio_cell(cell['read_latency_p99_ratio'])} | "
                f"{ratio_cell(cell['downstream_response_wait_ratio'])} | "
                f"{ratio_cell(cell['flow_credit_wait_ratio'])} | {cell['wins']}/{cell['losses']} |"
            )
        print()
    print("## Decisions\n")
    print("| arm | workloads with CI-low > 1 | p95 ok | p99 ok | integrity | accepted |")
    print("|---|---|---|---|---|---|")
    for arm, decision in document["decisions"].items():
        print(
            f"| `{arm}` | {decision['workloads_with_ci_lower_bound_above_1']}/"
            f"{decision['workloads_measured']} | {decision['p95_within_5_percent']} | "
            f"{decision['p99_within_5_percent']} | {decision['integrity_ok']} | "
            f"**{decision['accepted']}** |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "experiments/thor-p2-lab/campaign-01")))
