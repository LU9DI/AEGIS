# Local relay benchmark report — v0.3.0

**Purpose:** measure forwarding and per-hop AEAD costs before adding more complex network mechanisms. This report does not demonstrate anonymity, anti-correlation, or WAN performance.

## Setup

- Host: Linux x86-64, Python 3.13.5.
- All services bind to `127.0.0.1`; each destination/relay is a separate Python subprocess.
- Payload: 8,000,000 bytes each direction; 5 bulk trials and 50 small-message samples per scenario; seed `20261009`.
- Every bulk transfer reuses a persistent circuit. The raw path has plaintext TCP relays; the onion path authenticates one binary ChaCha20-Poly1305 layer per relay and adds one response-encryption layer on the way back.
- The first encrypted request warms the persistent circuit and is excluded from latency samples. Key files are random per run and temporary.
- All transfer responses passed SHA-256 integrity checks.

## Matched-hop-count results

| Relays | Raw TCP median payload goodput | Encrypted onion median payload goodput | Onion/raw ratio | Raw p50 RTT | Onion p50 request/response | Raw p95 RTT | Onion p95 request/response |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4,883.117 Mb/s | 1,890.747 Mb/s | 38.7% | 0.059 ms | 0.111 ms | 0.175 ms | 0.203 ms |
| 2 | 3,950.360 Mb/s | 1,275.633 Mb/s | 32.3% | 0.152 ms | 0.195 ms | 0.711 ms | 0.294 ms |
| 3 | 3,599.606 Mb/s | 789.116 Mb/s | 21.9% | 0.142 ms | 0.279 ms | 0.270 ms | 0.426 ms |

The three-hop path sustained about **789 Mb/s** in this local run, approximately **4.6× lower** than the raw three-hop TCP chain. The three-hop onion p95 request/response latency was 0.426 ms versus 0.270 ms for raw TCP. These are per-run microbenchmark figures, not a forecast of a public network.

All latency metrics are taken on warmed persistent circuits; raw measures warm-connection RTT while onion includes request-layer encryption at the client, per-hop authenticated decryption/encryption, and client response-layer decryption. An outlier in the raw two-hop p95 sample shows why repeated runs and host-load control matter. Do not interpret the table as a precise cryptographic cost measurement.

## What this tells us

1. A persistent circuit avoids opening a TCP connection at every hop for every request, which is an important prerequisite for browser-like workloads.
2. Compact binary envelopes avoid the repeated JSON/Base64 growth in the first internal draft. Each hop now adds bounded framing and AEAD overhead rather than re-encoding all inner bytes as text.
3. The Python encrypted implementation is still about 4.6× slower than raw forwarding at three hops on loopback. The measured gap includes crypto, Python scheduling, per-hop copies, framing, and response wrapping; it does **not** isolate the cryptographic primitive alone.
4. A loopback path has effectively no WAN propagation delay and can sustain gigabits per second. These numbers cannot be compared directly with live Tor or interpreted as expected Internet speed.
5. The benchmark says nothing about anonymity. All relays are on one host; traffic timing is visible; the exit knows its destination and payload; there is no key agreement, forward secrecy, replay defense, traffic mixing, or correlation defense.

## Next engineering tasks, in order

1. Specify circuit creation and authenticated ephemeral key agreement; bind keys to circuit identifiers and implement replay/reordering defense.
2. Keep the circuit persistent, but evolve the echo-specific frame protocol into bounded multiplexed streams with flow control, cancellation, deadlines, circuit teardown, and backpressure.
3. Profile CPU and allocations; benchmark AEAD, frame processing, and relay forwarding separately. Consider a Rust data plane only after establishing a reproducible Python baseline.
4. Add multi-client load tests and controlled delay/loss across isolated containers or hosts the operator controls.
5. Add multi-user traffic-analysis tests against an explicit adversary. Do not claim anonymity until a formal design and independent review support that claim.

## Raw evidence

- [`raw-1-hop-8mb.json`](raw-1-hop-8mb.json)
- [`raw-2-hop-8mb.json`](raw-2-hop-8mb.json)
- [`raw-3-hop-8mb.json`](raw-3-hop-8mb.json)
- [`onion-1-hop-8mb.json`](onion-1-hop-8mb.json)
- [`onion-2-hop-8mb.json`](onion-2-hop-8mb.json)
- [`onion-3-hop-8mb.json`](onion-3-hop-8mb.json)
- [`comparison-summary.json`](comparison-summary.json)
