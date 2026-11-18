"""Isolated hot-path candidates for the AEGIS envelope path, with measurements.

Purpose: decide, with numbers, whether the micro-level costs that look wasteful
when reading the code (constructing an AEAD object per message, rebuilding the
AAD string per message, concatenating header+payload, copying the body on every
hop, building a dispatch dictionary per command) actually matter relative to the
dominant cost, which this module also measures end to end.

Every candidate here is **byte-compatible** with the current implementation: for
the same key, nonce, plaintext and AAD the ciphertext must be identical. The
benchmark asserts that before reporting any timing, so a faster candidate cannot
win by changing the bytes.

Nothing in this module is wired into the relay path. Integration is a separate,
evidence-gated step (see ``docs/research/thor/08-PROTOTYPE-RESULTS.md``).
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import statistics
import struct
import time
from collections.abc import Callable
from typing import Any

from ..onion_protocol import (
    NONCE_BYTES,
    REQUEST_PREFIX,
    _REQUEST_HEADER,
    frame,
    open_sealed,
    seal,
)

__all__ = ["run_fastpath_benchmark", "main"]


def _now_ns() -> int:
    return time.perf_counter_ns()


def _measure(operation: Callable[[], Any], *, repeats: int, warmup: int = 20) -> dict[str, float]:
    for _ in range(warmup):
        operation()
    samples: list[int] = []
    for _ in range(repeats):
        started = _now_ns()
        operation()
        samples.append(_now_ns() - started)
    samples.sort()
    return {
        "median_ns": float(statistics.median(samples)),
        "p95_ns": float(samples[min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))]),
        "min_ns": float(samples[0]),
    }


def _cipher_class():
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305  # noqa: PLC0415

    return ChaCha20Poly1305


def _benchmark_size(size: int, *, repeats: int, seed: int = 20261118) -> dict[str, Any]:
    import random  # noqa: PLC0415 - deterministic payload generation

    cipher_class = _cipher_class()
    rng = random.Random(seed)
    key = rng.randbytes(32)
    nonce = rng.randbytes(NONCE_BYTES)
    payload = rng.randbytes(size)
    aad_fresh = REQUEST_PREFIX + b"relay-2"

    fresh_cipher = cipher_class(key)
    shared_cipher = cipher_class(key)

    # Correctness gate: the shared cipher must produce identical bytes.
    reference = nonce + fresh_cipher.encrypt(nonce, payload, aad_fresh)
    candidate = nonce + shared_cipher.encrypt(nonce, payload, aad_fresh)
    if reference != candidate:
        raise AssertionError("shared AEAD object produced different ciphertext")
    envelope = reference
    if open_sealed(key, envelope, aad_fresh) != payload:
        raise AssertionError("reference envelope did not round-trip")

    header = _REQUEST_HEADER.pack(2, 0, 8080, len(payload), b"c" * 16, 7)
    plaintext = header + payload

    results: dict[str, dict[str, float]] = {}
    results["aead_object_construct"] = _measure(lambda: cipher_class(key), repeats=repeats)
    results["seal_uncached"] = _measure(
        lambda: nonce + cipher_class(key).encrypt(nonce, payload, aad_fresh), repeats=repeats
    )
    results["seal_shared_object"] = _measure(
        lambda: nonce + shared_cipher.encrypt(nonce, payload, aad_fresh), repeats=repeats
    )
    results["open_uncached"] = _measure(
        lambda: cipher_class(key).decrypt(nonce, envelope[NONCE_BYTES:], aad_fresh), repeats=repeats
    )
    results["open_shared_object"] = _measure(
        lambda: shared_cipher.decrypt(nonce, envelope[NONCE_BYTES:], aad_fresh), repeats=repeats
    )
    results["aad_encode_fresh"] = _measure(
        lambda: REQUEST_PREFIX + "relay-2".encode("ascii"), repeats=repeats
    )

    cached_aad = functools.lru_cache(maxsize=256)(
        lambda prefix, relay_id: prefix + relay_id.encode("ascii")
    )
    results["aad_encode_cached"] = _measure(
        lambda: cached_aad(REQUEST_PREFIX, "relay-2"), repeats=repeats
    )
    results["body_copy_slice"] = _measure(lambda: plaintext[_REQUEST_HEADER.size :], repeats=repeats)
    results["body_memoryview"] = _measure(
        lambda: memoryview(plaintext)[_REQUEST_HEADER.size :], repeats=repeats
    )
    results["frame_concat"] = _measure(lambda: frame(payload), repeats=repeats)
    results["frame_pack_only"] = _measure(lambda: struct.pack("!I", len(payload)), repeats=repeats)
    results["command_header_unpack"] = _measure(
        lambda: _REQUEST_HEADER.unpack_from(plaintext), repeats=repeats
    )
    operation_names = {
        ord("E"): "extend", ord("F"): "forward", ord("D"): "data", ord("O"): "open_stream",
        ord("B"): "start_stream", ord("W"): "write", ord("H"): "half_close",
        ord("V"): "window_update", ord("X"): "close_stream",
    }
    results["dispatch_dict_built"] = _measure(
        lambda: {
            ord("E"): "extend", ord("F"): "forward", ord("D"): "data", ord("O"): "open_stream",
            ord("B"): "start_stream", ord("W"): "write", ord("H"): "half_close",
            ord("V"): "window_update", ord("X"): "close_stream",
        },
        repeats=repeats,
    )
    results["dispatch_dict_cached"] = _measure(
        lambda: operation_names.get(ord("W"), "unknown"), repeats=repeats
    )

    # Full per-hop command cost: open one request layer, copy the body, re-frame
    # the response. This is the smallest repeatable unit of relay work.
    def one_hop_command() -> None:
        plain = shared_cipher.decrypt(nonce, envelope[NONCE_BYTES:], aad_fresh)
        body = plain[_REQUEST_HEADER.size :]
        reply_header = struct.pack("!QII", 7, 0, len(body))
        sealed = nonce + shared_cipher.encrypt(nonce, reply_header + body, aad_fresh)
        _ = frame(sealed)

    results["one_hop_command"] = _measure(one_hop_command, repeats=repeats)

    # Theoretical ceiling for a single-process serial relay chain: one hop cost
    # per hop per command, no event loop, no scheduling, no client.
    per_hop_ns = results["one_hop_command"]["median_ns"]
    return {
        "payload_bytes": size,
        "operations": results,
        "derived": {
            "one_hop_command_ns": per_hop_ns,
            "three_hop_chain_command_ns": per_hop_ns * 3,
            "commands_per_second_single_core_3hop": (
                None if per_hop_ns <= 0 else round(1e9 / (per_hop_ns * 3), 1)
            ),
            "predicted_goodput_mbps_3hop_serial": (
                None
                if per_hop_ns <= 0
                else round((size * 8) / (per_hop_ns * 3 / 1e9) / 1e6, 3)
            ),
        },
    }


def run_fastpath_benchmark(
    *, sizes: tuple[int, ...] = (1024, 16 * 1024, 256 * 1024), repeats: int = 2000
) -> dict[str, Any]:
    """Measure the candidate micro-optimisations and the per-hop command cost."""
    if not 100 <= repeats <= 200_000:
        raise ValueError("repeats must be within 100..200000")
    if not sizes or any(size < 1 for size in sizes):
        raise ValueError("sizes must be a non-empty tuple of positive byte counts")
    started = _now_ns()
    measurements = [_benchmark_size(size, repeats=repeats) for size in sizes]
    return {
        "schema_version": 1,
        "kind": "thor_lab_fastpath_microbenchmark",
        "generated_ns": started,
        "repeats": repeats,
        "note": (
            "Microbenchmark only. It measures the cost of individual operations in "
            "CPython on this host; it is not a protocol result and does not include "
            "event-loop, socket, or scheduling cost."
        ),
        "cryptography_version": _crypto_version(),
        "measurements": measurements,
    }


def _crypto_version() -> str:
    try:
        import cryptography  # noqa: PLC0415

        return str(cryptography.__version__)
    except Exception:  # noqa: BLE001
        return "unavailable"


def _summarize(measured: dict[str, Any]) -> str:
    lines = [
        "payload_bytes  operation                      median_ns      p95_ns",
        "-------------------------------------------------------------------------",
    ]
    for entry in measured["measurements"]:
        for name, values in entry["operations"].items():
            lines.append(
                f"{entry['payload_bytes']:>12}  {name:<28} {values['median_ns']:>10.1f} {values['p95_ns']:>11.1f}"
            )
        derived = entry["derived"]
        lines.append(
            f"{entry['payload_bytes']:>12}  predicted 3-hop serial Mb/s   {derived['predicted_goodput_mbps_3hop_serial']}"
        )
        lines.append(
            f"{entry['payload_bytes']:>12}  commands/s single core       {derived['commands_per_second_single_core_3hop']}"
        )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS fast-path microbenchmark (research only)")
    parser.add_argument("--repeats", type=int, default=2000)
    parser.add_argument("--sizes", default="1024,16384,262144")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    sizes = tuple(int(item) for item in args.sizes.split(",") if item.strip())
    result = run_fastpath_benchmark(sizes=sizes, repeats=args.repeats)
    print(_summarize(result))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
