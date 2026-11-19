"""Command-line entry point for the THOR lab.

Examples::

    python -m anonlab.thor_lab probe
    python -m anonlab.thor_lab run --tier lab --out experiments/thor-lab/lab-01 \
        --arms surface,relay3_plain,aegis_telescope3 \
        --workloads bulk_echo:262144,small_rtt:1024x50 --trials 5
    python -m anonlab.thor_lab summarize experiments/thor-lab/lab-01
    python -m anonlab.thor_lab report experiments/thor-lab/lab-01
    python -m anonlab.thor_lab verify experiments/thor-lab/lab-01

The CLI never edits a raw artifact. ``run`` produces a new directory; every
other subcommand only reads it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .. import __version__
from . import TIERS
from .backends import probe_tor
from .metrics import load_run, summarize_run, verify_run_digest
from .provenance import code_revision, environment
from .report import write_report
from .runner import ArmSpec, run_suite
from .workloads import WorkloadSpec

__all__ = ["main", "parse_workload_spec"]

_ARM_CHOICES = (
    "surface",
    "relay3_plain",
    "aegis_telescope3",
    "aegis_io_batch",
    "aegis_lean_dispatch",
    "aegis_combined",
    "tor_socks",
)


def _parse_chunked(specification: str, *, chunk_bytes: int, in_flight: int, timeout: float) -> WorkloadSpec:
    return parse_workload_spec(
        specification, chunk_bytes=chunk_bytes, in_flight=in_flight, timeout=timeout
    )


def _apply_chunk_suffix(
    text: str, chunk_bytes: int, in_flight: int
) -> tuple[str, int, int]:
    """Split an optional ``@<chunk>i<in_flight>`` suffix off a workload spec."""
    if "@" not in text:
        return text, chunk_bytes, in_flight
    body, _, suffix = text.partition("@")
    chunk_text, separator, in_flight_text = suffix.partition("i")
    if not separator:
        raise ValueError(f"chunk suffix must be '<chunk>i<in_flight>', got {suffix!r}")
    return body, int(chunk_text), int(in_flight_text)


def parse_workload_spec(
    specification: str,
    *,
    chunk_bytes: int = 16 * 1024,
    in_flight: int = 4,
    timeout: float = 120.0,
    http_host: str | None = None,
    http_path: str = "/",
    http_headers: tuple[tuple[str, str], ...] = (),
) -> WorkloadSpec:
    """Parse ``kind:payload[xcount][@chunk iinflight]`` from the command line.

    Grammar::

        bulk_echo:<payload_bytes>[@<chunk_bytes>i<in_flight>]
        small_rtt:<payload_bytes>x<operations>[@<chunk_bytes>i<in_flight>]
        parallel_bulk:<payload_bytes>x<streams>[@<chunk_bytes>i<in_flight>]
        http_get:<operations>

    The ``@`` suffix matters for fairness: an arm measured with 16 KiB commands
    and one measured with 256 KiB commands are different experiments.
    """
    text = specification.strip()
    if not text:
        raise ValueError("empty workload specification")
    text, chunk_bytes, in_flight = _apply_chunk_suffix(text, chunk_bytes, in_flight)
    kind, _, rest = text.partition(":")
    kind = kind.strip()
    if kind == "bulk_echo":
        payload = int(rest or "262144")
        return WorkloadSpec(
            kind="bulk_echo",
            payload_bytes=payload,
            chunk_bytes=chunk_bytes,
            max_in_flight=in_flight,
            timeout_s=timeout,
        )
    if kind == "small_rtt":
        payload_text, _, count_text = rest.partition("x")
        return WorkloadSpec(
            kind="small_rtt",
            payload_bytes=int(payload_text or "1024"),
            operations=int(count_text or "50"),
            chunk_bytes=chunk_bytes,
            max_in_flight=in_flight,
            timeout_s=timeout,
        )
    if kind == "parallel_bulk":
        payload_text, _, count_text = rest.partition("x")
        return WorkloadSpec(
            kind="parallel_bulk",
            payload_bytes=int(payload_text or "65536"),
            streams=int(count_text or "8"),
            chunk_bytes=chunk_bytes,
            max_in_flight=in_flight,
            timeout_s=timeout,
        )
    if kind == "http_get":
        if not http_host:
            raise ValueError("http_get workloads require --public-url")
        return WorkloadSpec(
            kind="http_get",
            operations=int(rest or "3"),
            timeout_s=timeout,
            http_host=http_host,
            http_path=http_path,
            http_headers=http_headers,
        )
    raise ValueError(f"unknown workload kind {kind!r}")


def _parse_socks(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    if not host or not port:
        raise ValueError("--socks must be HOST:PORT")
    return host, int(port)


def _split_list(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError("expected a comma-separated list")
    return items


def _cmd_probe(args: argparse.Namespace) -> int:
    revision = code_revision()
    env = environment()
    crypto_available = True
    crypto_detail = "ok"
    try:
        import cryptography  # noqa: F401,PLC0415 - probe only

        crypto_detail = str(getattr(cryptography, "__version__", "unknown"))
    except Exception as exc:  # noqa: BLE001
        crypto_available = False
        crypto_detail = f"{type(exc).__name__}: {exc}"
    socks_host, socks_port = _parse_socks(args.socks)
    tor = asyncio.run(probe_tor(socks_host, socks_port, timeout=args.timeout))
    payload = {
        "aegis_version": __version__,
        "revision": revision,
        "environment": env,
        "crypto_extra": {"available": crypto_available, "detail": crypto_detail},
        "tor_socks": tor,
        "tiers": TIERS,
        "note": "probe is read-only: it opens one TCP connection to the SOCKS port and closes it",
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    arms = [ArmSpec(name) for name in _split_list(args.arms)]
    for name in arms:
        if name.name not in _ARM_CHOICES:
            print(f"error: unknown arm {name.name!r}; choose from {', '.join(_ARM_CHOICES)}", file=sys.stderr)
            return 2
    if "tor_socks" in [arm.name for arm in arms] and args.tier != "public":
        print("error: the tor_socks arm is a public-tier arm; pass --tier public", file=sys.stderr)
        return 2
    http_host = None
    http_path = "/"
    if args.public_url:
        from urllib.parse import urlsplit

        split = urlsplit(args.public_url)
        if split.scheme != "http" or not split.hostname:
            print("error: --public-url must be a plain http:// URL with a host", file=sys.stderr)
            return 2
        http_host = split.hostname
        http_path = split.path or "/"
        if split.query:
            http_path = f"{http_path}?{split.query}"
    workloads: list[WorkloadSpec] = []
    if args.tier != "public":
        workloads = [
            _parse_chunked(
                item,
                chunk_bytes=args.chunk_bytes,
                in_flight=args.in_flight,
                timeout=args.timeout,
            )
            for item in _split_list(args.workloads)
        ]
    http_headers: list[tuple[str, str]] = []
    for raw_header in args.http_header or []:
        name, separator, value = raw_header.partition(":")
        if not separator or not name.strip():
            print(f"error: --http-header expects 'Name: value', got {raw_header!r}", file=sys.stderr)
            return 2
        http_headers.append((name.strip(), value.strip()))
    if args.tier == "public":
        workloads = [
            parse_workload_spec(
                item,
                chunk_bytes=args.chunk_bytes,
                in_flight=args.in_flight,
                timeout=args.timeout,
                http_host=http_host,
                http_path=http_path,
                http_headers=tuple(http_headers),
            )
            for item in _split_list(args.workloads)
        ]
    link_profile = None
    if args.profile:
        try:
            from ..network_impairment import DEFAULT_PROFILES  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            print(f"error: link profiles unavailable: {exc}", file=sys.stderr)
            return 2
        if args.profile not in DEFAULT_PROFILES:
            print(
                f"error: unknown profile {args.profile!r}; choose from {', '.join(sorted(DEFAULT_PROFILES))}",
                file=sys.stderr,
            )
            return 2
        link_profile = DEFAULT_PROFILES[args.profile]
        if args.tier != "emulated":
            print("error: --profile requires --tier emulated", file=sys.stderr)
            return 2
    elif args.tier == "emulated":
        print("error: --tier emulated requires --profile", file=sys.stderr)
        return 2

    socks_host, socks_port = _parse_socks(args.socks)
    arm_options: dict[str, dict[str, Any]] = {}
    if "aegis_telescope3" in [arm.name for arm in arms]:
        arm_options["aegis_telescope3"] = {
            "hop_count": args.aegis_hops,
            "window_update_batch_bytes": args.window_update_batch,
        }
    if "tor_socks" in [arm.name for arm in arms]:
        arm_options["tor_socks"] = {"socks_host": socks_host, "socks_port": socks_port}
    arms = [ArmSpec(name=arm.name, options=arm_options.get(arm.name, {}) or arm.options) for arm in arms]

    try:
        result = asyncio.run(
            run_suite(
                out_dir=Path(args.out),
                tier=args.tier,
                arms=arms,
                workloads=workloads,
                trials=args.trials,
                warmup_trials=args.warmup,
                seed=args.seed,
                public_url=args.public_url,
                link_profile=link_profile,
                notes=args.notes,
                timer_resolution_ms=args.timer_resolution_ms,
            )
        )
    except (FileExistsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    if args.no_derive:
        return 0
    data = load_run(result.out_dir)
    summary = summarize_run(data)
    summary_path = result.out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_path = write_report(summary_path, result.out_dir / "REPORT.md")
    print(f"wrote {summary_path} and {report_path}")
    return 0


def _resolve_summary(run_dir: Path) -> Path:
    return run_dir / "summary.json"


def _cmd_summarize(args: argparse.Namespace) -> int:
    data = load_run(Path(args.run_dir))
    summary = summarize_run(data)
    out = Path(args.out) if args.out else _resolve_summary(Path(args.run_dir))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    summary_path = Path(args.summary) if args.summary else _resolve_summary(Path(args.run_dir))
    out = Path(args.out) if args.out else Path(args.run_dir) / "REPORT.md"
    path = write_report(summary_path, out, title=args.title)
    print(f"wrote {path}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    data = load_run(Path(args.run_dir))
    summary_path = Path(args.summary) if args.summary else _resolve_summary(Path(args.run_dir))
    if not summary_path.is_file():
        print(f"error: {summary_path} not found; run summarize first", file=sys.stderr)
        return 2
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    checks = verify_run_digest(data, summary)
    print(json.dumps(checks, indent=2, ensure_ascii=False))
    return 0 if checks.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-thor-lab", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="report environment, revision, crypto and Tor availability")
    probe.add_argument("--socks", default="127.0.0.1:9050")
    probe.add_argument("--timeout", type=float, default=5.0)
    probe.set_defaults(handler=_cmd_probe)

    run = sub.add_parser("run", help="execute a new measurement suite into a fresh directory")
    run.add_argument("--out", required=True)
    run.add_argument("--tier", choices=sorted(TIERS), default="lab")
    run.add_argument("--arms", default="surface,relay3_plain,aegis_telescope3")
    run.add_argument("--workloads", default="bulk_echo:262144,small_rtt:1024x50")
    run.add_argument("--trials", type=int, default=5)
    run.add_argument("--warmup", type=int, default=1)
    run.add_argument("--seed", type=int, default=20261118)
    run.add_argument("--chunk-bytes", type=int, default=16 * 1024)
    run.add_argument("--in-flight", type=int, default=4)
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--profile", default=None, help="loopback link shaper profile (emulated tier)")
    run.add_argument("--public-url", default=None, help="plain http:// endpoint shared by all public arms")
    run.add_argument(
        "--http-header",
        action="append",
        default=None,
        help="extra HTTP header for http_get workloads, repeatable ('Range: bytes=0-262143')",
    )
    run.add_argument("--socks", default="127.0.0.1:9050")
    run.add_argument("--aegis-hops", type=int, default=3)
    run.add_argument("--window-update-batch", type=int, default=64 * 1024)
    run.add_argument("--notes", default="")
    run.add_argument(
        "--timer-resolution-ms",
        type=int,
        default=1,
        help="raise the OS timer resolution for the run (Windows; 0 disables)",
    )
    run.add_argument("--no-derive", action="store_true", help="skip writing summary.json and REPORT.md")
    run.set_defaults(handler=_cmd_run)

    summarize = sub.add_parser("summarize", help="recompute summary.json from a raw run")
    summarize.add_argument("run_dir")
    summarize.add_argument("--out", default=None)
    summarize.set_defaults(handler=_cmd_summarize)

    report = sub.add_parser("report", help="render REPORT.md from summary.json")
    report.add_argument("run_dir")
    report.add_argument("--summary", default=None)
    report.add_argument("--out", default=None)
    report.add_argument("--title", default=None)
    report.set_defaults(handler=_cmd_report)

    verify = sub.add_parser("verify", help="check raw and configuration digests")
    verify.add_argument("run_dir")
    verify.add_argument("--summary", default=None)
    verify.set_defaults(handler=_cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
