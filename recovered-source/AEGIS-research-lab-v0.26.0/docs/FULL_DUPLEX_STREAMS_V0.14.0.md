# MALEBOLGE full-duplex byte streams — origin v0.14.0, write batching v0.15.0 (experimental)

## Scope

The loopback telescoping testbed now includes an experimental byte-stream API:

- `TelescopingClient.open_stream(host, port)` creates an allowlisted loopback TCP stream through the existing telescoping circuit.
- `DuplexCircuitStream.write(data)` accepts up to 64 KiB and waits for an acknowledgement; response events remain limited to 16 KiB.
- `DuplexCircuitStream.write_eof()` half-closes the client-to-destination direction while leaving the response direction open.
- `DuplexCircuitStream.read_chunk()` returns up to 16 KiB of response bytes, or `b""` once peer EOF has been consumed.
- `DuplexCircuitStream.close()` explicitly closes the destination socket and removes the stream mapping.

This is a proof of concept, not a browser-ready HTTP/TLS transport and not a production anonymity protocol.

## Wire/control model

Stream IDs are independently assigned at every hop. Commands from the client use the existing authenticated per-hop AEAD layer and strict command sequence numbers. The added inner commands are:

- `O`: open an allowlisted destination stream at the exit.
- `B`: start the exit-to-client reader after the OPEN acknowledgement is fully propagated.
- `W`: write a bounded chunk to the destination.
- `H`: half-close the client-to-destination direction.
- `V`: grant read credit after the application consumes data.
- `X`: close the stream.

Intermediate relays forward opaque child commands, maintaining only a mapping between the stream ID on their upstream link and the child stream ID. Reverse-direction data and EOF are unsolicited per-link event frames. At each relay, the child event envelope is wrapped in a new response AEAD layer; the client authenticates and unwraps the layers in route order. Each stream has an independent event sequence at each hop.

The `B` start command and per-relay readiness gate prevent a peer-data event from overtaking the stream-start acknowledgement. Relays queue a small bounded number of early events. The testbed closes the circuit on invalid/unmatched event correlation rather than guessing which stream should receive data.

## Flow control and resource limits

- Response/event data chunk maximum: 16 KiB.
- Client-to-destination write batch maximum: 64 KiB (one acknowledgement per batch).
- Initial exit-to-client read credit: 64 KiB per stream.
- Read-credit maximum: 256 KiB per stream.
- A read-credit update is accepted only in the range 1..16 KiB and is rejected if it would exceed the maximum window.
- Local relay and client active-stream limits continue to apply.
- The exit reserves read credit before awaiting socket reads and refunds unused credit if a read returns fewer bytes than requested.
- The client returns credit only after `read_chunk()` consumes bytes. If the bounded per-stream event queue is exhausted, the implementation fails closed rather than buffer without bound.
- `write()` waits for a destination-write acknowledgement, creating producer-side backpressure. The per-batch request/ack design is deliberately simple and still adds one round trip per 64 KiB at the default setting; this remains a throughput limitation. The 64 KiB write cap bounds transient command payload memory.

## Validation and measurement

The tests exercise two-way data flow, half-close, peer EOF, multiple streams sharing one circuit, a 192 KiB server push that exceeds the initial window, invalid oversized writes, destination allowlists, stream cleanup, and the fact that only the exit records the destination port. A smoke benchmark compares full-duplex loopback goodput and latency with direct TCP to the same echo service.

Benchmark interpretation must be conservative:

- All relays and destination run on one host over IPv4 loopback.
- Direct TCP is an unencrypted, one-hop baseline; it is not a Tor comparison.
- The direct endpoint and application data are visible at the exit; intermediate relays still see timing, sizes, and their link-local stream IDs.
- The protocol has not been independently audited.
- No claim is made about global traffic-analysis resistance, WAN performance, or anonymity parity with Tor.

Across three repeated trials on the same host, median useful-payload goodput was 130.56 Mb/s for the full-duplex circuit and 2,324.10 Mb/s for direct TCP. This gap is expected to be one of the main optimization targets. See [`DUPLEX_BENCHMARK_REPORT_V0.14.0.md`](../experiments/DUPLEX_BENCHMARK_REPORT_V0.14.0.md), [`STREAM_SECURITY_REVIEW_V0.14.0.md`](STREAM_SECURITY_REVIEW_V0.14.0.md), the benchmark JSON under `experiments/`, and `tests/test_telescoping.py`.

## v0.15.0 write batching

Client writes may now contain up to 64 KiB, reducing command/ack count for bulk transfers while retaining the 16 KiB response event chunk and the 64 KiB read-credit window. Use the paired benchmark to compare 16 KiB and 64 KiB writes with the same workload. This optimization must be judged by repeated measurements; fewer acknowledgements does not guarantee higher WAN throughput or fairness.
