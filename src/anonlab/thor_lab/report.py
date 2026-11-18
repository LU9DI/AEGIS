"""Render a THOR summary as a Markdown report.

The report is generated from ``summary.json`` only; it never re-derives numbers
by hand. Every table states its tier and the number of paired trials, and the
caveat block is copied from the tier definition so a table cannot silently
migrate from "loopback" to "public-network" in a later edit.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["render_markdown", "write_report"]

_TIER_CAVEATS = {
    "lab": (
        "All endpoints are IPv4 loopback on one host inside one Python process. "
        "These numbers are **not** WAN performance, **not** Tor performance and do "
        "not establish anonymity. They isolate implementation cost under identical "
        "origin, destination, payload, duration and (absent an explicit link profile) "
        "network conditions."
    ),
    "emulated": (
        "Loopback plus the repository's user-space link shaper. The shaper models "
        "one-way delay, jitter and serialization rate on **byte-stream chunks**, not "
        "IP packets: there is no loss, no retransmission model and no queueing "
        "discipline. Treat these numbers as a sensitivity study, not a forecast."
    ),
    "public": (
        "Real public-network endpoints over the local access link. Results depend on "
        "this host's ISP, time of day and the remote server, and Tor's path changes "
        "per connection. They are a baseline for the Surface/Tor gap on this machine, "
        "not a property of the networks in general."
    ),
}


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        if value != value:  # NaN guard
            return "n/a"
        return f"{value:,.{digits}f}{suffix}"
    return str(value)


def _metric(summary: dict[str, Any], arm: str, label: str, key: str, field: str = "p50") -> Any:
    entry = summary.get("workloads", {}).get(label, {}).get(arm)
    if not entry:
        return None
    metric = entry.get(key)
    if not isinstance(metric, dict) or not metric.get("n"):
        return None
    return metric.get(field)


def _ci(summary: dict[str, Any], arm: str, label: str, key: str) -> str:
    entry = summary.get("workloads", {}).get(label, {}).get(arm)
    if not entry:
        return "n/a"
    metric = entry.get(key)
    if not isinstance(metric, dict) or not metric.get("n"):
        return "n/a"
    interval = metric.get("ci") or {}
    if not interval.get("reliable"):
        return f"{_fmt(metric.get('p50'))} (CI n/a, n<5)"
    return f"{_fmt(metric.get('p50'))} [{_fmt(interval.get('low'))}, {_fmt(interval.get('high'))}]"


def render_markdown(summary: dict[str, Any], *, title: str | None = None) -> str:
    tier = str(summary.get("tier"))
    code = summary.get("code") or {}
    environment = summary.get("environment") or {}
    raw = summary.get("raw") or {}
    lines: list[str] = []
    heading = title or f"THOR measurement report — {summary.get('run_id', 'unlabeled run')}"
    lines.append(f"# {heading}")
    lines.append("")
    lines.append(f"- **Tier**: `{tier}`")
    lines.append(f"- **Run id**: `{summary.get('run_id')}`")
    lines.append(f"- **Seed**: `{summary.get('seed')}`")
    lines.append(f"- **Revision**: `{code.get('revision')}` (dirty: `{code.get('dirty')}`)")
    lines.append(
        f"- **Environment**: Python {environment.get('python')} on {environment.get('platform')}; "
        f"{environment.get('cpu_count')} logical CPUs; cryptography {((environment.get('dependencies') or {}).get('cryptography'))}"
    )
    lines.append(f"- **Configuration digest**: `{summary.get('configuration_digest')}`")
    lines.append(f"- **Raw trials**: {raw.get('records')} records ({raw.get('warmup_records')} warmup, {raw.get('error_records')} errors), digest `{str(raw.get('trials_sha256'))[:16]}…`")
    lines.append("")
    lines.append("> " + _TIER_CAVEATS.get(tier, "Unknown tier; do not interpret these numbers."))
    lines.append("")

    availability = summary.get("availability") or []
    if availability:
        lines.append("## Arms that could not run")
        lines.append("")
        lines.append("| Arm | Reason | Detail |")
        lines.append("|---|---|---|")
        for entry in availability:
            lines.append(
                f"| `{entry.get('backend')}` | `{entry.get('reason')}` | {_fmt(entry.get('detail'))} |"
            )
        lines.append("")

    gates = summary.get("gates") or []
    lines.append("## Target gate: AEGIS goodput ≥ 90% of Surface")
    lines.append("")
    if not gates:
        lines.append("No gate could be evaluated for this run.")
    else:
        lines.append("| Workload | Candidate | Paired trials | Goodput ratio (median [95% CI]) | Needs × | Status |")
        lines.append("|---|---|---|---|---|---|")
        for gate in gates:
            ratio = gate.get("goodput_ratio") or {}
            if gate.get("status") == "insufficient_data":
                lines.append(
                    f"| `{gate.get('workload')}` | `{gate.get('candidate')}` | {gate.get('paired_trials', 0)} | n/a | n/a | "
                    f"**insufficient data** ({gate.get('reason')}) |"
                )
                continue
            lines.append(
                f"| `{gate.get('workload')}` | `{gate.get('candidate')}` | {gate.get('paired_trials')} | "
                f"{_fmt(ratio.get('point'), 3)} [{_fmt(ratio.get('low'), 3)}, {_fmt(ratio.get('high'), 3)}] | "
                f"{_fmt(gate.get('headroom_needed_factor'), 2)} | **{gate.get('status')}** |"
            )
    lines.append("")

    for label, per_arm in sorted((summary.get("workloads") or {}).items()):
        lines.append(f"## Workload `{label}`")
        lines.append("")
        lines.append(
            "| Arm | Trials | Goodput Mb/s (p50 [95% CI]) | TTFB ms | Completion p95 ms | Completion p99 ms | "
            "Per-op p95 ms | Setup ms | Wire up ×payload | Wire down ×payload | CPU of one core | Peak RSS MiB |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for arm in sorted(per_arm):
            entry = per_arm[arm]
            peak_rss = _metric(summary, arm, label, "peak_rss_kb", "p50")
            lines.append(
                "| `{arm}` | {trials} | {goodput} | {ttfb} | {cp95} | {cp99} | {p95} | {setup} | {wire_up} | {wire_down} | {cpu} | {rss} |".format(
                    arm=arm,
                    trials=entry.get("trials"),
                    goodput=_ci(summary, arm, label, "goodput_mbps"),
                    ttfb=_fmt(_metric(summary, arm, label, "ttfb_ms")),
                    cp95=_fmt(_metric(summary, arm, label, "total_ms", "p95")),
                    cp99=_fmt(_metric(summary, arm, label, "total_ms", "p99")),
                    p95=_fmt(_metric(summary, arm, label, "latency_p95_ms")),
                    setup=_fmt(_metric(summary, arm, label, "setup_ms")),
                    wire_up=_fmt(_metric(summary, arm, label, "wire_up_ratio"), 3),
                    wire_down=_fmt(_metric(summary, arm, label, "wire_down_ratio"), 3),
                    cpu=_fmt(_metric(summary, arm, label, "cpu_fraction_of_one_core"), 3),
                    rss=_fmt(None if peak_rss is None else peak_rss / 1024.0),
                )
            )
        lines.append("")
        lines.append(
            "Goodput is payload bits divided by the wall time from first write to last echoed byte "
            "(one direction of useful payload per round trip). Completion p95/p99 is the per-trial "
            "total time; per-op p95/p99 exists only for round-trip workloads and is `n/a` for bulk. "
            "Wire ratios are counted by the per-arm edge proxy and include every byte the client put "
            "on its access link, including AEAD tags, headers and window updates."
        )
        lines.append("")

    lines.append("## Reproducing this artifact")
    lines.append("")
    lines.append("```")
    lines.append(f"python -m anonlab.thor_lab summarize {summary.get('run_id')}")
    lines.append("python -m anonlab.thor_lab verify <run-directory>")
    lines.append("```")
    lines.append("")
    lines.append("`verify` recomputes the SHA-256 of `trials.jsonl` and the configuration digest and fails if either changed.")
    lines.append("")
    return "\n".join(lines)


def write_report(summary_path: Path | str, out_path: Path | str, *, title: str | None = None) -> Path:
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    rendered = render_markdown(summary, title=title)
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    return output
