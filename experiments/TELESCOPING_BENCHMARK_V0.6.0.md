# MALEBOLGE telescoping benchmark — v0.6.0

**Status: local transport experiment only. This is not a WAN benchmark, an anonymity test, or a security audit.**

## Configuration

- Host: Linux x86-64, Python 3.13.5.
- Three IPv4 loopback relay listeners and one loopback echo destination, all in a single Python process.
- Five independent circuit builds and 65,536-byte echo requests; seed `20261009`.
- The client opened one TCP connection to the guard per circuit. Later relay connections were opened by the current last relay during extension.
- Both direct and telescoping paths opened a fresh TCP connection to the echo endpoint for each request. The reported goodput is useful echo-response payload divided by round-trip time, not aggregate bidirectional wire throughput.
- All responses were byte-for-byte verified. The command-observation assertion passed in every trial.

## Measurements

| Metric | Direct loopback echo | Three-hop telescoping echo |
|---|---:|---:|
| RTT p50 | 0.222 ms | 1.068 ms |
| RTT p95 | 0.343 ms | 1.614 ms |
| Useful response goodput | Not used as a comparable headline | 490.94 Mb/s median |

Circuit construction (guard handshake plus two extensions) was 2.082 ms at p50 and 2.712 ms at p95. The client made exactly one direct connection in each of the five circuit builds. The benchmark reported integrity verified and `route_knowledge_separation_check: true`.

The observed latency and throughput are host-local results. They cannot predict performance across real networks, and the measured relay processes share one machine, clock, kernel and failure domain.

## Parsed command visibility

For each trial, the in-memory observation ledger recorded:

- Entry relay: `EXTEND(middle)`, `FORWARD(opaque)` to add the exit, then `FORWARD(opaque)` for the data request.
- Middle relay: `EXTEND(exit)`, then `FORWARD(opaque)` for the data request.
- Exit relay: `DATA(loopback-echo-endpoint)`.

The exit address is not present in the entry/middle *parsed command fields*. This proves only the intended knowledge boundary for this implementation's message parser. It does not prove indistinguishability under packet capture: timing, frame sizes, connection lifetime and traffic volume still expose metadata, and relays can collude.

## Reproduction

From the project root:

```bash
python -m pip install -e '.[onion-lab]'
PYTHONPATH=src python -m anonlab.telescoping_benchmark --bytes 65536 --trials 5 --seed 20261009 --output experiments/telescoping-benchmark-v0.6.0.json
PYTHONPATH=src python -m unittest discover -s tests -v
```

Raw per-trial summary and parsed observations: [`telescoping-benchmark-v0.6.0.json`](telescoping-benchmark-v0.6.0.json).

## Security gaps

The relays are not mutually authenticated on transport links; local descriptors are in memory and are not signed, expired or revocable. The ntor-derived MALEBOLGE KDF is custom and unreviewed. The data plane is a one-shot loopback echo command capped at 1 MiB, not a general stream implementation. Flow control, congestion control, resource quotas, robust partial-failure recovery, distributed replay state, padding/mixing and traffic-correlation evaluation remain unimplemented. No relay should be exposed to a public interface and no sensitive traffic should be sent through this harness.
