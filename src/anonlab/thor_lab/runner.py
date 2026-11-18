"""Trial orchestrator: one directory per run, raw records append-only.

Design constraints, in priority order:

1. **No silent drops.** A failed, timed-out or warmup trial is written as a
   record with its status. Arms that cannot start are recorded in
   ``availability.json`` with a machine-readable reason, and the run manifest is
   marked ``partial`` — the summary then says "insufficient data" instead of
   quietly comparing two of three arms.
2. **Interleaving.** Arms are measured round-robin with a rotation per trial, so
   a slow thermal or background-load drift does not land only on one arm.
3. **One ratio, one tier.** The runner refuses to mix tiers in one run, and
   records the tier in every record.
4. **Derived data is separate.** ``trials.jsonl`` is raw; ``summary.json`` and
   ``REPORT.md`` are regenerated from it by the ``summarize``/``report``
   commands and never edited by hand.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import SCHEMA_VERSION, TIERS
from .backends import ARMS, Backend, BackendUnavailable
from .counting_proxy import CountingProxy
from .provenance import canonical_digest, manifest as build_manifest
from .resources import delta as resource_delta, snapshot as resource_snapshot
from .timers import begin_high_resolution_timer, end_high_resolution_timer
from .workloads import PayloadFactory, WorkloadSpec, run_workload

__all__ = ["ArmSpec", "RunResult", "run_suite", "TRIAL_SCHEMA_VERSION"]

TRIAL_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ArmSpec:
    """One arm plus the constructor options that distinguish it."""

    name: str
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.name not in ARMS:
            raise ValueError(f"unknown arm {self.name!r}; known arms: {', '.join(sorted(ARMS))}")
        if not isinstance(self.options, dict):
            raise ValueError("options must be a mapping")


@dataclass(slots=True)
class RunResult:
    out_dir: Path
    run_id: str
    trials_written: int
    arms_measured: list[str]
    arms_unavailable: list[dict[str, object]]
    partial: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "out_dir": str(self.out_dir),
            "run_id": self.run_id,
            "trials_written": self.trials_written,
            "arms_measured": list(self.arms_measured),
            "arms_unavailable": list(self.arms_unavailable),
            "partial": self.partial,
        }


def _sanitize_error(exc: BaseException) -> dict[str, object]:
    message = str(exc)
    if len(message) > 400:
        message = message[:400] + "..."
    return {"type": type(exc).__name__, "message": message}


def _parse_public_url(url: str) -> tuple[str, int, str]:
    split = urlsplit(url)
    if split.scheme not in {"http"}:
        raise ValueError("public tier currently supports plain http:// endpoints only")
    host = split.hostname
    if not host:
        raise ValueError("public URL must contain a host name")
    port = split.port or (80 if split.scheme == "http" else 443)
    path = split.path or "/"
    if split.query:
        path = f"{path}?{split.query}"
    return host, port, path


def _build_backend(
    arm: ArmSpec,
    *,
    tier: str,
    target_host: str,
    target_port: int,
    link_profile: Any | None,
) -> Backend:
    options = dict(arm.options)
    backend_class = ARMS[arm.name]
    if arm.name == "surface":
        backend = backend_class(target_host, target_port, tier=tier, name=arm.name)
    elif arm.name == "relay3_plain":
        backend = backend_class(target_host, target_port, tier=tier, name=arm.name, **options)
    elif arm.name == "aegis_telescope3":
        backend = backend_class(target_host, target_port, tier=tier, name=arm.name, **options)
    elif arm.name == "tor_socks":
        backend = backend_class(target_host, target_port, tier=tier, name=arm.name, **options)
    else:  # pragma: no cover - guarded by ArmSpec validation
        raise ValueError(f"unsupported arm {arm.name!r}")
    backend.set_link_profile(link_profile)
    return backend


def _edge_delta(before: dict[str, int] | None, after: dict[str, int] | None) -> dict[str, int] | None:
    if before is None or after is None:
        return None
    return {name: after[name] - before[name] for name in before}


async def _run_single_trial(
    backend: Backend,
    spec: WorkloadSpec,
    factory: PayloadFactory,
    *,
    trial_index: int,
    warmup: bool,
    tier: str,
    seed: int,
) -> dict[str, object]:
    before = resource_snapshot()
    edge_before = backend.edge_snapshot()
    setup_calls: list[dict[str, object]] = []
    outcome = None
    error: dict[str, object] | None = None
    started_ns = time.perf_counter_ns()

    async def connector():
        connection = await backend.connect(timeout=min(spec.timeout_s, 120.0))
        setup_calls.append(
            {
                "steps": [step.to_dict() for step in connection.setup_steps],
                "setup_ms": connection.setup_ms,
                "meta": dict(connection.meta),
            }
        )
        return connection

    try:
        outcome = await run_workload(connector, spec, factory, proxy=backend.edge)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, never dropped
        error = _sanitize_error(exc)

    wall_ms = (time.perf_counter_ns() - started_ns) / 1e6
    # Teardown is charged to the trial but excluded from the reported wall time,
    # so an arm that leaks circuits is visible in CPU/RSS instead of silently
    # inflating another arm's throughput.
    with contextlib.suppress(Exception):
        await backend.after_trial()
    after = resource_snapshot()
    edge_after = backend.edge_snapshot()
    edge = _edge_delta(edge_before, edge_after)
    payload_bytes = 0 if outcome is None else int(outcome.payload_bytes)
    overhead: dict[str, float | None] = {"wire_up_ratio": None, "wire_down_ratio": None}
    if edge is not None and payload_bytes > 0:
        overhead = {
            "wire_up_ratio": round(edge["client_to_upstream_bytes"] / payload_bytes, 6),
            "wire_down_ratio": round(edge["upstream_to_client_bytes"] / payload_bytes, 6),
        }
    first_setup_ms = None
    if setup_calls:
        first_setup_ms = sum(float(step["ms"]) for step in setup_calls[0]["steps"])  # type: ignore[index]
    record: dict[str, object] = {
        "schema_version": TRIAL_SCHEMA_VERSION,
        "trial": trial_index,
        "warmup": warmup,
        "arm": backend.name,
        "family": backend.family,
        "tier": tier,
        "workload": spec.to_dict(),
        "workload_label": spec.label,
        "seed": seed,
        "status": "ok" if error is None else "error",
        "error": error,
        "outcome": None if outcome is None else outcome.to_dict(),
        "setup_calls": setup_calls,
        "setup_ms": None if first_setup_ms is None else round(first_setup_ms, 4),
        "edge": edge,
        "overhead": overhead,
        "wall_ms": round(wall_ms, 4),
        "resources": resource_delta(before, after).to_dict(),
    }
    return record


async def run_suite(
    *,
    out_dir: Path | str,
    tier: str,
    arms: list[ArmSpec],
    workloads: list[WorkloadSpec],
    trials: int = 5,
    warmup_trials: int = 1,
    seed: int = 20261118,
    public_url: str | None = None,
    link_profile: Any | None = None,
    notes: str = "",
    timer_resolution_ms: int = 1,
) -> RunResult:
    """Run one measurement suite and write an immutable artifact directory."""
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {sorted(TIERS)}")
    if not arms:
        raise ValueError("at least one arm must be selected")
    if not workloads:
        raise ValueError("at least one workload must be selected")
    if not 1 <= int(trials) <= 200:
        raise ValueError("trials must be within 1..200")
    if not 0 <= int(warmup_trials) <= 10:
        raise ValueError("warmup_trials must be within 0..10")
    names = [arm.name for arm in arms]
    if len(set(names)) != len(names):
        raise ValueError("arm names must be unique")

    needs_public = any(workload.kind == "http_get" for workload in workloads)
    if needs_public and not public_url:
        raise ValueError("http_get workloads require public_url")
    if needs_public and tier != "public":
        raise ValueError("http_get is only defined for the public tier")
    if not needs_public and tier == "public":
        raise ValueError("the public tier currently supports http_get workloads only")
    if link_profile is not None and tier != "emulated":
        raise ValueError("a loopback link profile requires tier='emulated' (lab means no shaping)")
    if link_profile is None and tier == "emulated":
        raise ValueError("tier='emulated' requires a link profile")

    destination = Path(out_dir)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(
            f"{destination} already contains artifacts; runs are immutable, choose a new directory"
        )
    destination.mkdir(parents=True, exist_ok=True)
    if int(timer_resolution_ms) <= 0:
        timer_state: dict[str, object] = {"applied": False, "period_ms": None, "reason": "disabled"}
    else:
        timer_state = begin_high_resolution_timer(timer_resolution_ms)

    if needs_public:
        assert public_url is not None
        target_host, target_port, _path = _parse_public_url(public_url)
        assert link_profile is None, "public tier cannot use the loopback shaper"
    else:
        from .appproto import start_echo_server  # local import keeps the module import cheap

        echo = await start_echo_server()
        target_host, target_port = echo.host, echo.port

    configuration = {
        "tier": tier,
        "arms": [{"name": arm.name, "options": arm.options} for arm in arms],
        "workloads": [workload.to_dict() for workload in workloads],
        "trials": trials,
        "warmup_trials": warmup_trials,
        "seed": seed,
        "public_url": public_url,
        "link_profile": None if link_profile is None else link_profile.name,
        "notes": notes,
    }
    run_id = time.strftime("%Y%m%dT%H%M%S", time.localtime()) + f"-{tier}-{seed}"
    run_manifest = build_manifest(
        configuration=configuration,
        seed=seed,
        tier=tier,
        extra={
            "run_id": run_id,
            "runner": "anonlab.thor_lab.runner",
            "configuration_digest_short": canonical_digest(configuration)[:16],
            "timer_resolution": timer_state,
        },
    )
    (destination / "manifest.json").write_text(
        json.dumps(run_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    started_backends: dict[str, Backend] = {}
    unavailable: list[dict[str, object]] = []
    factory = PayloadFactory(seed)
    trials_path = destination / "trials.jsonl"
    written = 0

    try:
        for arm in arms:
            backend = _build_backend(
                arm,
                tier=tier,
                target_host=target_host,
                target_port=target_port,
                link_profile=link_profile,
            )
            try:
                await backend.start()
            except BackendUnavailable as exc:
                unavailable.append(exc.to_dict())
                with contextlib.suppress(Exception):
                    await backend.close()
                continue
            except Exception as exc:  # noqa: BLE001 - a broken arm must not abort the suite
                unavailable.append(
                    {"backend": arm.name, "reason": "start_failed", "detail": f"{type(exc).__name__}: {exc}"}
                )
                with contextlib.suppress(Exception):
                    await backend.close()
                continue
            started_backends[arm.name] = backend

        (destination / "availability.json").write_text(
            json.dumps(unavailable, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        measured = [arm.name for arm in arms if arm.name in started_backends]
        rotation = len(measured)
        with trials_path.open("w", encoding="utf-8") as handle:
            for warmup_round in range(warmup_trials):
                for spec in workloads:
                    for offset in range(rotation):
                        name = measured[offset] if rotation else None
                        if name is None:
                            continue
                        record = await _run_single_trial(
                            started_backends[name],
                            spec,
                            factory,
                            trial_index=-(warmup_round + 1),
                            warmup=True,
                            tier=tier,
                            seed=seed,
                        )
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                        handle.flush()
                        written += 1
            for trial_index in range(trials):
                order = [measured[(trial_index + offset) % rotation] for offset in range(rotation)] if rotation else []
                for spec in workloads:
                    for name in order:
                        record = await _run_single_trial(
                            started_backends[name],
                            spec,
                            factory,
                            trial_index=trial_index,
                            warmup=False,
                            tier=tier,
                            seed=seed,
                        )
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                        handle.flush()
                        written += 1
    finally:
        for backend in started_backends.values():
            with contextlib.suppress(Exception):
                await backend.close()
        if not needs_public:
            with contextlib.suppress(Exception):
                await echo.close()
        end_high_resolution_timer()

    measured_names = [arm.name for arm in arms if arm.name in started_backends]
    result = RunResult(
        out_dir=destination,
        run_id=run_id,
        trials_written=written,
        arms_measured=measured_names,
        arms_unavailable=unavailable,
        partial=bool(unavailable),
    )
    (destination / "run.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "result": result.to_dict(),
                "record_schema_version": TRIAL_SCHEMA_VERSION,
                "target": {"host": target_host, "port": target_port},
                "claims": "Raw measurement artifact; see docs/research/thor/04-THREAT-MODEL.md for scope.",
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return result
