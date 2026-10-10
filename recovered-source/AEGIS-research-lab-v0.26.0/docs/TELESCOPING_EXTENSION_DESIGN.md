# MALEBOLGE telescoping circuit-extension design

**Status: design basis partially implemented by the loopback-only v0.6.0 proof of concept. It is not a production circuit protocol. See [the POC notes](TELESCOPING_EXTENSION_POC.md) and [measured benchmark](../experiments/TELESCOPING_BENCHMARK_V0.6.0.md).**

## Decision

Extend a circuit one hop at a time through its current last relay. Never have
the client open independent control connections to every relay to negotiate its
keys: that would disclose the complete route to the client's network observer
and create a direct correlation point. The client must already have the
intended relay descriptors from an authenticated source, but only transmit the
next hop's endpoint and handshake payload through the existing circuit.

This follows the general circuit-extension shape used by Tor (EXTEND/EXTEND2
and CREATE/CREATE2), but this document is not a compatible implementation of
Tor cells and does not claim equivalence with Tor's full protocol.

## Example: client C, guard G1, middle G2, exit G3

1. **Build G1.** C establishes a TCP/TLS transport to G1 and completes a
   one-hop handshake. C obtains the identity digest and static onion key for G1
   from authenticated relay metadata. The experimental `ntor_experiment.py`
   covers the handshake transcript only; link authentication and descriptor
   validation are not part of the current code.
2. **Extend to G2 through G1.** C sends an authenticated circuit command to G1
   that contains G2's network endpoint, expected identity digest, static onion
   key ID, and an ntor client handshake. G1 must only learn its immediate next
   hop. It opens an authenticated relay-to-relay channel to G2 and forwards the
   handshake bytes. G2 responds with its ephemeral public key and ntor
   authenticator; C validates the response against G2's descriptor before
   accepting G2's independent traffic keys.
3. **Extend to G3 through G2.** C sends the next extension command inside the
   circuit so that G2 receives the G3 endpoint/handshake data. G1 must see only
   opaque bytes at this stage, not the G3 address, identity digest, or onion
   key. C validates G3's response and derives a third set of directional keys.
4. **Transfer data.** Each relay removes only its own authenticated envelope.
   Request keys and response keys are independently derived for every hop. The
   circuit's stream layer must keep route-extension control messages distinct
   from application streams and must not leak later-hop descriptor fields in
   outer-layer plaintext, errors, logs, metrics, or frame lengths.

## Intended knowledge boundary

| Participant | Expected routing knowledge | Explicitly not given by protocol plaintext |
|---|---|---|
| Client | Full selected route and all keys | No relay can be trusted to prove global anonymity alone |
| G1 | Its peer (client) and G2, the next hop it must contact | G3 descriptor and later path suffix |
| G2 | Previous relay G1 and next hop G3 | Later suffix beyond G3 |
| G3 | Previous relay G2 and exit destination for opened streams | Client's actual network address, unless extra design failures expose it |
| Destination | The exit connection and application request | Client address, subject to application identifiers and traffic correlation |

This table is a protocol intent, not a guarantee against collusion or timing
analysis. G1 and G3 may be able to correlate traffic; each hop can observe local
traffic timing, volume, peer addresses, and circuit lifetime. Padding, mixing,
congestion, and an explicit global-observer model remain separate research
requirements.

## Message-level requirements

- Extension commands are authenticated and encrypted under the current circuit's
  last-hop keys; the target descriptor appears only after that layer is removed.
- The request binds protocol version, current circuit ID, next-hop identity,
  onion-key ID, handshake bytes, and a fresh extension transaction ID.
- The v0.6.0 loopback harness lets G1 initiate a TCP connection to G2, but does
  not yet authenticate the relay-to-relay transport peer. Production code must
  bind the authenticated peer to the signed descriptor.
- C verifies the target identity and handshake response before adding the hop's
  keys to the circuit state.
- Each new hop has independent request/response keys and a distinct nonce or
  sequence space. Retrying an extension uses a new ephemeral key and new
  transaction ID; failed partial extensions are destroyed, not silently
  re-used.
- Errors are intentionally generic on the wire. Detailed causes are local and
  must not leak future-hop metadata through remote diagnostics.
- Per-relay connection limits, handshake concurrency, extension rate limits,
  maximum hops, timeouts, and circuit teardown must be explicit.

## Open decisions before distributed use

1. **Authenticated directory:** descriptor format, signing root, expiration,
   key rotation, and revocation. The harness takes descriptors from memory; the
   handshake does not authenticate arbitrary directory metadata.
2. **Relay links:** mutual transport authentication and target identity binding.
3. **Circuit-control format:** add explicit circuit and extension transaction IDs,
   version/capability negotiation, retry policy, and unknown-command handling.
4. **Key integration:** create independent implementation/test vectors for the
   custom KDF and obtain a cryptographic review; key erasure and rekey behavior
   remain unspecified.
5. **Isolation:** define stream multiplexing and per-stream sequence scopes.
6. **Failure/resource model:** timeouts, partial extension rollback, concurrency
   caps, rate limits, memory bounds and deterministic teardown.
7. **Threat analysis:** entry-only, exit-only, colluding entry+exit, and broad
   passive observer. Route parsing separation does not prevent timing/volume
   correlation or collusion.

## Acceptance gates

The v0.6.0 three-relay loopback code now exists, with tests that G1 sees only
`EXTEND(middle)` followed by `FORWARD(opaque)` when the exit is added, and with
no direct client socket to G2/G3. Before distributed testing:

- Obtain independent review of the sequence diagram, byte-level schema, exact
  KDF and AEAD usage; publish stable positive and negative test vectors.
- Add explicit transaction IDs and tests for identity mismatch, replayed
  extension transactions, malformed lengths, duplicate extension, timeout,
  partial failure, disconnect and resource exhaustion.
- Implement signed descriptors and authenticated relay links with identity
  binding, rotation, expiry and revocation.
- Preserve the loopback-only data destination guard until abuse resistance,
  threat analysis and safe exit policy are defined.

The first distributed testbed remains a controlled experiment, not a public
anonymity network.
