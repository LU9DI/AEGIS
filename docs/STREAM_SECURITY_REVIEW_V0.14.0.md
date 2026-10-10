# Security review — full-duplex streams v0.14.0

## Implemented controls

- Per-hop AEAD remains required for all client commands and all event layers.
- Strict per-hop command sequence numbers remain in use; event sequences are separate, monotonic per stream and per relay.
- Stream IDs are unique among locally active streams at allocation time and remapped on every hop.
- Stream OPEN is routed through the existing circuit; the exit's allowlist remains the only path to a destination socket.
- The exit emits no events before START. Intermediate relays gate child events until their START acknowledgement has been propagated.
- Initial read credit (64 KiB), maximum credit (256 KiB), 16 KiB maximum chunks, a bounded event queue, and relay/client stream caps limit application data buffering.
- Consumed data returns credit to the exit; invalid or excessive credit updates fail the affected circuit closed.
- HALF_CLOSE preserves the response direction; CLOSE cancels the reader and closes the destination socket.
- Tests cover simultaneous streams, half-close/EOF ordering, server push beyond the initial window, data integrity and cleanup.

## Known gaps and risks

1. **Not independently audited.** This is a custom experimental protocol and its composition, sequence-space use, cancellation races and crypto transcript need external review.
2. **No production cryptographic profile.** Existing ntor-derived handshake/KDF adaptations and message framing are MALEBOLGE-specific and are not Tor-compatible.
3. **Exit visibility.** The exit learns destination address/port and sees application plaintext. This lab does not add end-to-end TLS or application protocol policy.
4. **Traffic analysis remains possible.** Timing, packet sizes, stream counts and link-local correlation identifiers remain visible to adjacent relays. No defense against global passive observers is implemented.
5. **No WAN/censorship test.** The testbed binds only to IPv4 loopback and has not been tested under real network loss, jitter, congestion, NAT or hostile peers.
6. **Flow-control fairness not proven.** Credit is per stream, but command acknowledgements share one circuit send lock and one response dispatcher. A stream with many writes/window updates can create head-of-line delay for other streams. There is no scheduler fairness proof or congestion-control algorithm.
7. **Failure semantics need further review.** Abrupt failures can close the whole circuit; stream-local error recovery and reconnect/resume are not implemented. Close/event races have unit coverage but not model checking.
8. **DoS hardening incomplete.** Per-stream credits and queue limits bound normal data paths, but there is no distributed rate limiting, authenticated admission policy for every fallback test fixture, or memory/CPU stress testing on separate machines.
9. **Exit stream policy is intentionally narrow.** Only explicitly allowlisted IPv4 loopback destinations are supported. Do not remove this guard to deploy publicly.

## Release decision

Research-only milestone. Do not use this code to protect sensitive traffic or expose relay listeners to non-loopback networks. The next work should target batched writes/window updates, shared-circuit fairness, fault injection over multiple machines, formal state-machine properties, and independent protocol review—not deployment.
