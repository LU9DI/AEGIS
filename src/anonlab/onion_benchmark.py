"""Measure an experimental encrypted one-shot onion path on loopback only."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import platform
import random
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .onion_protocol import MAX_FRAME_BYTES, build_request, frame, unwrap_response

HOST = "127.0.0.1"
SRC_ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def _benchmark_tempdir(prefix: str) -> Iterator[Path]:
    """Temporary directory that tolerates delayed handle release on Windows.

    Child relay processes write their logs into this directory. After the
    children are terminated and reaped, the operating system may still hold the
    inherited log handles for a moment (observed on Windows), so an immediate
    rmtree can raise PermissionError. Retry briefly instead of failing the
    benchmark after the measurement itself has already succeeded.
    """
    path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield path
    finally:
        for attempt in range(50):
            try:
                shutil.rmtree(path)
                break
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.02)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


async def _wait_ready(port: int, process: subprocess.Popen[bytes], deadline_s: float = 8.0) -> None:
    end = time.monotonic() + deadline_s
    last_error: Exception | None = None
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError(f"onion relay process exited early (exit code {process.returncode})")
        try:
            reader, writer = await asyncio.open_connection(HOST, port)
            writer.close()
            await writer.wait_closed()
            del reader
            return
        except (ConnectionError, OSError) as exc:
            last_error = exc
            await asyncio.sleep(0.025)
    raise TimeoutError(f"onion relay on {HOST}:{port} did not become ready: {last_error}")


async def _read_frame(reader: asyncio.StreamReader) -> bytes:
    length = int.from_bytes(await reader.readexactly(4), "big")
    if length > MAX_FRAME_BYTES:
        raise ValueError("response frame exceeds maximum size")
    return await reader.readexactly(length)


async def _onion_request(
    ingress_port: int,
    relay_ports: list[int],
    keys: list[bytes],
    destination_port: int,
    payload: bytes,
) -> tuple[bytes, float]:
    circuit_id = os.urandom(16)
    sequence = 0
    packet = build_request(
        payload, relay_ports, keys, destination_port, circuit_id=circuit_id, sequence=sequence
    )
    started = time.perf_counter()
    reader, writer = await asyncio.open_connection(HOST, ingress_port)
    try:
        writer.write(frame(packet))
        await writer.drain()
        response = await _read_frame(reader)
        for index, key in enumerate(keys):
            response = unwrap_response(
                key, f"relay-{index + 1}", response,
                circuit_id=circuit_id, expected_sequence=sequence,
            )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return response, elapsed_ms
    finally:
        writer.close()
        await writer.wait_closed()


async def _onion_exchange_persistent(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    relay_ports: list[int],
    keys: list[bytes],
    destination_port: int,
    payload: bytes,
    *,
    circuit_id: bytes,
    sequence: int,
) -> tuple[bytes, float]:
    packet = build_request(
        payload, relay_ports, keys, destination_port, circuit_id=circuit_id, sequence=sequence
    )
    started = time.perf_counter()
    writer.write(frame(packet))
    await writer.drain()
    response = await _read_frame(reader)
    for index, key in enumerate(keys):
        response = unwrap_response(
            key, f"relay-{index + 1}", response,
            circuit_id=circuit_id, expected_sequence=sequence,
        )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return response, elapsed_ms


def _start_process(args: list[str], log_path: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    with log_path.open("wb") as handle:
        return subprocess.Popen(args, stdout=handle, stderr=subprocess.STDOUT, env=env)


async def run_onion_benchmark(
    hop_count: int = 3,
    payload_bytes: int = 1_000_000,
    trials: int = 3,
    latency_samples: int = 20,
    seed: int = 20261009,
    persistent: bool = False,
) -> dict[str, Any]:
    if not 1 <= hop_count <= 4:
        raise ValueError("hop_count must be between 1 and 4 for the nested-frame research prototype")
    if payload_bytes < 1 or payload_bytes > 10_000_000:
        raise ValueError("payload_bytes must be between 1 and 10,000,000")
    if not 1 <= trials <= 20:
        raise ValueError("trials must be between 1 and 20")
    if not 3 <= latency_samples <= 200:
        raise ValueError("latency_samples must be between 3 and 200")

    ports = [_free_port() for _ in range(hop_count + 1)]  # destination first; relays follow
    keys = [os.urandom(32) for _ in range(hop_count)]
    rng = random.Random(seed)
    payload = rng.randbytes(payload_bytes)
    processes: list[subprocess.Popen[bytes]] = []

    with _benchmark_tempdir("rea-anon-onion-") as tmp_path:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        module_args = [sys.executable, "-m"]
        try:
            echo_proc = _start_process(
                module_args + ["anonlab.echo_server", "--host", HOST, "--port", str(ports[0])],
                tmp_path / "echo.log", env,
            )
            processes.append(echo_proc)
            await _wait_ready(ports[0], echo_proc)

            for relay_index in range(hop_count - 1, -1, -1):
                key_file = tmp_path / f"relay-{relay_index + 1}.key"
                key_file.write_bytes(keys[relay_index])
                try:
                    key_file.chmod(0o600)
                except OSError:
                    pass
                relay_port = ports[relay_index + 1]
                is_terminal = relay_index == hop_count - 1
                allowed_next_port = ports[0] if is_terminal else ports[relay_index + 2]
                relay_args = module_args + [
                    "anonlab.onion_relay", "--host", HOST, "--port", str(relay_port),
                    "--relay-id", f"relay-{relay_index + 1}", "--key-file", str(key_file),
                    "--allowed-next-port", str(allowed_next_port),
                ]
                if is_terminal:
                    relay_args.append("--terminal-relay")
                proc = _start_process(
                    relay_args,
                    tmp_path / f"relay-{relay_index + 1}.log", env,
                )
                processes.append(proc)
                await _wait_ready(relay_port, proc)

            ingress_port = ports[1]
            samples: list[float] = []
            transfer_results: list[dict[str, int | float | str]] = []
            persistent_reader: asyncio.StreamReader | None = None
            persistent_writer: asyncio.StreamWriter | None = None
            persistent_circuit_id = os.urandom(16) if persistent else None
            persistent_sequence = 0
            try:
                if persistent:
                    persistent_reader, persistent_writer = await asyncio.open_connection(HOST, ingress_port)

                async def exchange(request_payload: bytes) -> tuple[bytes, float]:
                    nonlocal persistent_sequence
                    if persistent and persistent_reader is not None and persistent_writer is not None:
                        if persistent_circuit_id is None:
                            raise RuntimeError("persistent circuit id was not initialized")
                        response, elapsed = await _onion_exchange_persistent(
                            persistent_reader, persistent_writer, ports[1:], keys, ports[0], request_payload,
                            circuit_id=persistent_circuit_id, sequence=persistent_sequence,
                        )
                        persistent_sequence += 1
                        return response, elapsed
                    return await _onion_request(ingress_port, ports[1:], keys, ports[0], request_payload)

                if persistent:
                    warmup_response, _ = await exchange(b"warmup-circuit")
                    if warmup_response != b"warmup-circuit":
                        raise RuntimeError("persistent-circuit warmup integrity check failed")

                for i in range(latency_samples):
                    request = f"probe-{i:08d}".encode("ascii")
                    response, latency_ms = await exchange(request)
                    if response != request:
                        raise RuntimeError("response integrity check failed for latency probe")
                    samples.append(latency_ms)

                for _ in range(trials):
                    response, elapsed_ms = await exchange(payload)
                    payload_hash = hashlib.sha256(payload).hexdigest()
                    response_hash = hashlib.sha256(response).hexdigest()
                    if response_hash != payload_hash:
                        raise RuntimeError("payload integrity check failed in onion benchmark")
                    elapsed_s = elapsed_ms / 1000.0
                    transfer_results.append({
                        "payload_bytes_each_direction": len(payload),
                        "elapsed_ms": round(elapsed_ms, 3),
                        "payload_goodput_mbps": round(len(payload) * 8 / elapsed_s / 1_000_000, 3),
                        "sha256": response_hash,
                    })
            finally:
                if persistent_writer is not None:
                    persistent_writer.close()
                    await persistent_writer.wait_closed()

            goodput = [float(item["payload_goodput_mbps"]) for item in transfer_results]
            return {
                "schema_version": 2,
                "measurement_type": "real_loopback_encrypted_onion_persistent_circuit" if persistent else "real_loopback_encrypted_onion_request_response",
                "is_live_internet_test": False,
                "is_anonymity_test": False,
                "cryptography": "ChaCha20-Poly1305 AEAD per hop; random pre-shared keys for this run; protocol v2 binary frames with circuit id and sequence checks",
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
                    "keys_persist_only_for_this_benchmark": True,
                    "persistent_circuit": persistent,
                    "latency_metric": "persistent_circuit_request_response" if persistent else "one_shot_request_response",
                },
                "environment": {"python": platform.python_version(), "platform": platform.platform()},
                "results": {
                    "request_response_latency_p50_ms": round(statistics.median(samples), 3),
                    "request_response_latency_p95_ms": round(_percentile(samples, 0.95), 3),
                    "payload_goodput_mbps_median": round(statistics.median(goodput), 3),
                    "payload_goodput_mbps_trials": [round(value, 3) for value in goodput],
                    "latency_samples_ms": [round(value, 3) for value in samples],
                    "transfer_trials": transfer_results,
                    "integrity_verified": True,
                },
                "limitations": [
                    "All relays run on one host and bind to loopback; no Internet/WAN behavior is measured.",
                    "The test supports request/response multiplexing only for the loopback echo destination; it is not a general bidirectional stream protocol or a browser circuit.",
                    "Keys are static pre-shared keys for each run; there is no authenticated key exchange, forward secrecy, key rotation, or authenticated relay directory.",
                    "Protocol v2 checks monotonic per-circuit sequence numbers and rejects duplicate circuit identifiers within each relay process; this bounded loopback-lab mechanism is not a general production replay solution.",
                    "A relay process and local host can inspect their own state. The destination relay sees the destination and plaintext payload; use end-to-end application encryption for content confidentiality.",
                    "The protocol has not been independently reviewed and is not safe for production or sensitive communications.",
                    "No batching/mixing, cover traffic, padding schedule, congestion control, peer discovery, multi-user anonymity set, or traffic-correlation defense is implemented.",
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
    parser.add_argument("--hops", type=int, default=3)
    parser.add_argument("--bytes", type=int, default=1_000_000)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--latency-samples", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--persistent-circuit", action="store_true", help="reuse one TCP onion circuit across all requests")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_onion_benchmark(args.hops, args.bytes, args.trials, args.latency_samples, args.seed, args.persistent_circuit))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
