"""Run a real TCP relay-chain benchmark using loopback-only subprocesses.

Measurements cover forwarding overhead on this host. There is no encryption,
Internet route, anonymity layer, or defense against an observer in this testbed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import random
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HOST = "127.0.0.1"
CHUNK = 64 * 1024
SRC_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


async def _wait_ready(port: int, process: subprocess.Popen[bytes], deadline_s: float = 8.0) -> None:
    end = time.monotonic() + deadline_s
    last_error: Exception | None = None
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError(f"testbed process exited early (exit code {process.returncode})")
        try:
            reader, writer = await asyncio.open_connection(HOST, port)
            writer.close()
            await writer.wait_closed()
            del reader
            return
        except (ConnectionError, OSError) as exc:
            last_error = exc
            await asyncio.sleep(0.025)
    raise TimeoutError(f"service on {HOST}:{port} did not become ready: {last_error}")


async def _round_trip(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, payload: bytes) -> float:
    started = time.perf_counter()
    writer.write(payload)
    await writer.drain()
    echoed = await reader.readexactly(len(payload))
    if echoed != payload:
        raise RuntimeError("echo data mismatch during latency probe")
    return (time.perf_counter() - started) * 1000.0


async def _measure_rtt(port: int, samples: int) -> list[float]:
    reader, writer = await asyncio.open_connection(HOST, port)
    try:
        # Small unframed messages are safe because this loop knows exact lengths.
        await _round_trip(reader, writer, b"rea-warmup")
        result = [await _round_trip(reader, writer, b"rea-probe-000001") for _ in range(samples)]
        return result
    finally:
        writer.close()
        await writer.wait_closed()


async def _transfer_persistent(
    port: int, payload: bytes, trials: int
) -> list[dict[str, float | str | int]]:
    """Measure multiple payloads on one open raw TCP relay circuit."""
    reader, writer = await asyncio.open_connection(HOST, port)
    results: list[dict[str, float | str | int]] = []
    expected_digest = hashlib.sha256(payload).hexdigest()
    try:
        for _ in range(trials):
            started = time.perf_counter()

            async def send_all() -> None:
                view = memoryview(payload)
                for offset in range(0, len(view), CHUNK):
                    writer.write(view[offset : offset + CHUNK])
                    await writer.drain()

            async def receive_all() -> bytes:
                chunks: list[bytes] = []
                remaining = len(payload)
                while remaining:
                    data = await reader.read(min(CHUNK, remaining))
                    if not data:
                        raise RuntimeError(f"echo stream ended with {remaining} bytes missing")
                    chunks.append(data)
                    remaining -= len(data)
                return b"".join(chunks)

            send_task = asyncio.create_task(send_all())
            receive_task = asyncio.create_task(receive_all())
            _, echoed = await asyncio.gather(send_task, receive_task)
            elapsed_s = time.perf_counter() - started
            digest = hashlib.sha256(echoed).hexdigest()
            if digest != expected_digest:
                raise RuntimeError("persistent echo data SHA-256 mismatch")
            results.append({
                "payload_bytes_each_direction": len(payload),
                "elapsed_ms": round(elapsed_s * 1000, 3),
                "echo_goodput_mbps": round(len(payload) * 8 / elapsed_s / 1_000_000, 3),
                "sha256": digest,
            })
        return results
    finally:
        writer.close()
        await writer.wait_closed()


def _start_process(args: list[str], log_path: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    log_handle = log_path.open("wb")
    try:
        process = subprocess.Popen(args, stdout=log_handle, stderr=subprocess.STDOUT, env=env)
    finally:
        log_handle.close()
    return process


async def run_local_benchmark(
    hop_count: int = 3,
    payload_bytes: int = 4_000_000,
    trials: int = 3,
    latency_samples: int = 30,
    seed: int = 20261009,
) -> dict[str, Any]:
    if not 1 <= hop_count <= 8:
        raise ValueError("hop_count must be between 1 and 8 for this local testbed")
    if payload_bytes < 1024:
        raise ValueError("payload_bytes must be at least 1024")
    if not 1 <= trials <= 20:
        raise ValueError("trials must be between 1 and 20")
    if not 3 <= latency_samples <= 500:
        raise ValueError("latency_samples must be between 3 and 500")

    ports = [_free_port() for _ in range(hop_count + 1)]
    # Index 0 is destination; relay i listens on ports[i + 1].
    processes: list[subprocess.Popen[bytes]] = []
    rng = random.Random(seed)
    payload = rng.randbytes(payload_bytes)
    with tempfile.TemporaryDirectory(prefix="rea-anon-lab-") as tmp:
        tmp_path = Path(tmp)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        module_args = [sys.executable, "-m"]
        try:
            echo_proc = _start_process(
                module_args + ["anonlab.echo_server", "--host", HOST, "--port", str(ports[0])],
                tmp_path / "echo.log",
                env,
            )
            processes.append(echo_proc)
            await _wait_ready(ports[0], echo_proc)

            # Start from the exit side so each relay's upstream already exists.
            for relay_index in range(hop_count - 1, -1, -1):
                listen_port = ports[relay_index + 1]
                upstream_port = ports[relay_index]
                proc = _start_process(
                    module_args + [
                        "anonlab.relay", "--host", HOST,
                        "--listen-port", str(listen_port),
                        "--upstream-host", HOST,
                        "--upstream-port", str(upstream_port),
                    ],
                    tmp_path / f"relay-{relay_index + 1}.log",
                    env,
                )
                processes.append(proc)
                await _wait_ready(listen_port, proc)

            ingress_port = ports[hop_count]
            rtt_samples = await _measure_rtt(ingress_port, latency_samples)
            transfers = await _transfer_persistent(ingress_port, payload, trials)
            throughputs = [float(item["echo_goodput_mbps"]) for item in transfers]
            return {
                "schema_version": 1,
                "measurement_type": "real_loopback_tcp_relay_benchmark",
                "is_live_internet_test": False,
                "is_anonymity_test": False,
                "encryption": "none; intentionally measures raw relay forwarding only",
                "topology": {
                    "host": HOST,
                    "relay_count": hop_count,
                    "path": ["client", *[f"relay-{i}" for i in range(1, hop_count + 1)], "echo-destination"],
                },
                "config": {
                    "payload_bytes_each_direction": payload_bytes,
                    "trials": trials,
                    "latency_samples": latency_samples,
                    "seed": seed,
                    "chunk_bytes": CHUNK,
                    "persistent_circuit_for_latency_and_bulk_transfers": True,
                },
                "environment": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                },
                "results": {
                    "rtt_p50_ms": round(statistics.median(rtt_samples), 3),
                    "rtt_p95_ms": round(_percentile(rtt_samples, 0.95), 3),
                    "echo_goodput_mbps_median": round(statistics.median(throughputs), 3),
                    "echo_goodput_mbps_trials": [round(value, 3) for value in throughputs],
                    "rtt_samples_ms": [round(value, 3) for value in rtt_samples],
                    "transfer_trials": transfers,
                    "integrity_verified": True,
                },
                "limitations": [
                    "All sockets terminate on loopback; results measure this host's local TCP stack.",
                    "Relays forward plaintext. No confidentiality, onion encryption, anonymity, or traffic-analysis defense is implemented.",
                    "TCP echo goodput is payload goodput for one direction; each byte is echoed back and therefore traverses the relay chain twice. Bulk trials reuse a persistent relay circuit.",
                    "These measurements cannot predict WAN performance or compare directly to live Tor without an equivalent controlled setup.",
                ],
            }
        finally:
            for process in reversed(processes):
                process.terminate()
            for process in reversed(processes):
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hops", type=int, default=3, help="number of loopback TCP relays (1-8)")
    parser.add_argument("--bytes", type=int, default=4_000_000, help="payload bytes per direction per trial")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--latency-samples", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    args = parser.parse_args()
    result = asyncio.run(run_local_benchmark(args.hops, args.bytes, args.trials, args.latency_samples, args.seed))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
