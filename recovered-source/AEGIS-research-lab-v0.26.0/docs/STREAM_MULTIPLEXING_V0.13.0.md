# MALEBOLGE stream multiplexing — v0.13.0 (experimental)

## Scope

This change multiplexes concurrent **one-shot request/response exchanges** over one persistent three-hop loopback circuit. It is deliberately not described as general TCP forwarding or as browser-ready full-duplex streams.

## Wire and state model

- Stream ID `0` remains reserved for serialized circuit-extension operations.
- Each application exchange gets a nonzero 32-bit stream ID at every hop. The identifiers are independently allocated per hop and need not match across the circuit.
- Each hop preserves its own monotonic 64-bit command sequence. Response correlation uses the pair `(sequence, stream_id)`; this avoids associating an out-of-order response with another caller's future.
- The client uses one response-reader task to decode link-level response correlation metadata and dispatch payloads into registered futures.
- `TelescopingClient.start_echo()` sends a bounded request and returns a `CircuitStream`; `CircuitStream.result()` awaits the matching response. `request_echo()` remains as a convenience wrapper.
- `X` cancels an in-flight stream. Forwarding relays wrap the cancellation toward the next hop, cancelling the local task and waiting for the downstream acknowledgement.
- Client and relay active-stream limits are bounded (default 128; configured range is validated). Payloads and overall frames retain existing size limits.

## Ordering invariant

For a forwarded DATA command, the relay must register its child response future and enqueue the child packet before returning to its incoming command loop. Otherwise, a later CANCEL could be sent downstream before the earlier DATA command, violating the downstream hop's strict sequence space. A regression test cancels a stream with `max_active_streams=1`, then sends another request on the same circuit; successful completion demonstrates that the circuit was not sequence-desynchronized by this race.

## Local experiment

`rea-anon-stream-bench --streams 16 --payload-bytes 4096 --seed 20261009 --output experiments/stream-multiplex-v0.13.0.json` compares concurrent one-shot streams against serial requests on one persistent three-relay circuit. It checks byte integrity, a parsed-observation route-separation condition, zero active streams after completion and relay connection teardown.

The recorded local run on Linux x86-64 / Python 3.13.5 measured:

- Circuit build: 2.70 ms.
- Multiplexed p50/p95 per-stream time: 8.75 / 8.92 ms.
- Serial p50/p95 request time: 0.57 / 0.72 ms.
- Multiplexed goodput: 56.54 Mb/s; serial: 54.81 Mb/s.
- Direct client connections: 1; active streams after completion: 0; relay active connections after close: `[0, 0, 0]`.

These are one-host loopback measurements, not WAN results. They show functional concurrent multiplexing but not a compelling performance gain. The p50 is defined by this benchmark's placement of timers and includes per-stream scheduling and queueing costs.

## Explicit limitations

- A stream is one bounded request plus one response, not an arbitrary long-lived bidirectional byte stream.
- The exit still opens a fresh connection to an allowlisted loopback destination per request.
- Link-level response sequence/stream metadata is visible to the immediate neighboring relay.
- The protocol does not claim traffic-analysis resistance, global replay defense, production security, or parity with Tor.
- Cancellation is best-effort: if the response completes before cancellation acknowledgement, the completed result wins.
- No independent cryptographic or protocol audit has been performed.
