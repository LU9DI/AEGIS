# Write-batching security review — v0.16.0

## Reviewed change

The maximum client-to-destination write payload rose from 64 KiB to 256 KiB. A per-write acknowledgement remains mandatory. Response-side data events stay at 16 KiB and the initial read-credit window remains 64 KiB.

## Checks

- The client API rejects writes larger than the configured maximum before sending them.
- The relay decoder applies the same payload cap after authenticated framing is opened.
- Per-hop AEAD and command sequencing are unchanged.
- The three-way benchmark verifies payload equality, relay-observability invariants, and that all streams/connections have been cleaned up.
- The full-duplex integration test now sends exactly 256 KiB in a single write and validates the complete echoed payload plus trailing response bytes.

## Risk introduced

Each active write may retain up to 256 KiB of payload, a 4× increase versus the prior release. At 128 concurrent streams this is 32 MiB of payload in the simplified worst case, excluding the application buffers and transport copies. This is not a strict RSS bound. A future pipelined design must introduce explicit per-circuit and per-process in-flight byte budgets before allowing multiple unacknowledged writes per stream.

## Not covered

This change does not add pipelining, coalesced acknowledgements, production congestion control, fairness, WAN testing, or anonymity guarantees. The protocol is custom, loopback-only, unaudited, and not Tor-compatible. Do not use for sensitive communications.
