# Write-batching security review — v0.15.0

## Change reviewed

Client-to-destination `WRITE` commands now carry at most 64 KiB instead of 16 KiB. Acknowledgement remains one per command. Response events remain capped at 16 KiB, the initial exit read-credit window stays at 64 KiB, and the maximum client command size is explicit. The circuit still uses per-hop AEAD, per-hop sequence validation, the existing hop-local stream mapping, and destination allowlists.

## Properties retained

- Payload is authenticated at each existing onion layer before the relay dispatches the command.
- Per-hop command sequence numbers still advance once per command; batching does not bypass sequencing.
- Relay/client stream limits and bounded response buffering are unchanged.
- Writes larger than 64 KiB are rejected locally and on the relay decoder boundary.
- The loopback-only endpoint restrictions remain in force.

## New trade-off

A larger accepted command increases transient bytes processed and retained in the command path. The cap limits an individual application write to 64 KiB, but aggregate memory still depends on the configured active streams and pending operations. This benchmark does not prove a complete global memory bound for arbitrary concurrent callers.

## Not established

This change does not provide end-to-end application encryption, cover traffic, mixing, traffic-correlation resistance, fairness, production congestion control, or Tor-equivalent anonymity. The exit still observes the application destination and plaintext supplied to the stream. All performance evidence is single-host IPv4 loopback. Independent cryptographic and implementation review remains required before any sensitive use.
