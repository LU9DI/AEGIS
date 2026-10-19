# MALEBOLGE encrypted onion — loopback stage

## Purpose

This stage tests whether per-hop authenticated encryption and relay processing can be measured independently from WAN latency. It uses ChaCha20-Poly1305 from the `cryptography` package and puts an authenticated encrypted binary envelope around each hop's routing instruction. The binary header prevents the repeated JSON/base64 expansion used by the first internal draft. The return path is onion-wrapped in reverse: the exit wraps the destination response, and each preceding relay adds its own response layer; the client removes the layers in route order.

## How to run

Install the optional crypto dependency:

```bash
python -m pip install -e '.[onion-lab]'
PYTHONPATH=src python -m anonlab.onion_benchmark \
  --hops 3 --bytes 1000000 --trials 5 --latency-samples 30 \
  --persistent-circuit --output experiments/onion-3-hop.json
```

Use only the loopback testbed. The benchmark starts the echo destination and each relay in a separate subprocess, creates random per-run symmetric key files, static for that benchmark run, with owner-only permissions where supported, checks returned bytes by SHA-256, and terminates the child processes when done.

## Properties exercised

- ChaCha20-Poly1305 authenticates each relay's own routing layer.
- Associated data binds a request/response layer to its direction and relay identifier.
- Protocol v2 binds a random 128-bit circuit identifier and a 64-bit monotonic sequence into each encrypted request/response envelope.
- Each live relay connection rejects a changed circuit ID or unexpected sequence; a process-local fail-closed registry rejects circuit-ID reuse across new connections.
- Relays validate the configured next-hop port and whether they are the terminal relay; they cannot act as arbitrary loopback proxies through a correctly configured benchmark process.
- The reverse response is wrapped independently at every hop.
- Length-prefixed frames have a maximum size; connection and read operations have deadlines.
- Tampering causes AEAD authentication failure; unit tests assert that behavior.

## Explicitly missing

This is not a production protocol. It has no authenticated ephemeral key exchange, forward secrecy, key rotation, authenticated relay directory, user/circuit isolation, general stream multiplexing, congestion control, padding, batching/mixing, distributed relay discovery, path selection, or defense against traffic correlation. Its sequence checks and process-local circuit-ID guard cover only narrow replay cases in this harness; the registry is not shared across relays, is reset on restart, has a finite capacity, and never evicts entries. Keys are pre-shared by local test orchestration, not negotiated securely. The exit relay sees the destination and application payload. The host can inspect every local process and socket. The benchmark is not a substitute for protocol review or a WAN deployment.

The prototype currently supports a persistent loopback circuit carrying repeated length-known echo request/response frames, not a general browser stream. Do not send sensitive or third-party traffic through it.

## Decision rule

Treat the benchmark as evidence about local serialization, frame expansion, AEAD overhead, and relay code paths only. No anonymity or real-world latency claim follows from a successful test. Before any network deployment, the protocol needs an authenticated ephemeral key exchange, independently specified circuit/key lifecycle, reviewed replay protection, independent cryptographic review, misrouting and state-exhaustion tests, and adversarial traffic-analysis evaluation.
