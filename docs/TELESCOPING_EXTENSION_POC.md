# MALEBOLGE telescoping extension proof of concept (v0.6.0)

**Status: loopback-only implementation; not yet a production anonymity protocol.**

## What now runs

`src/anonlab/telescoping.py` builds a circuit by opening a single client TCP
connection to the guard and extending it one relay at a time. The client uses
the separate `ntor_experiment.py` module to create and authenticate a fresh
handshake for each intended hop. Earlier relays forward opaque encrypted
payloads after removing only their own authenticated command envelope.

Commands in this lab are:

- `E` (EXTEND): contains the next relay's loopback endpoint, identity digest,
  onion public key and client handshake. Only the current last relay decrypts
  this command.
- `F` (FORWARD): contains a length-prefixed inner ciphertext. A relay removes
  its own envelope, forwards the inner ciphertext and wraps the downstream
  response on return. It does not parse the target descriptor inside that
  ciphertext.

Each hop has independent request and response keys and its own monotonically
increasing command sequence. The control layer rejects malformed lengths,
wrong command sequence, repeated target hops on the client, and non-loopback
relay descriptors. This code path opens no client sockets to the second or
third relay; next-hop connections are initiated by the current relay.

## Reproducing the tests

```bash
python -m pip install -e '.[onion-lab]'
python -m unittest tests.test_telescoping -v
```

The integration test launches three separate TCP listeners on loopback, builds
a three-hop circuit, asserts one direct client connection, and checks the
observable command ledger:

- entry: `EXTEND(middle)`, then `FORWARD(opaque)`;
- middle: `EXTEND(exit)`;
- exit: no extension command during circuit construction.

The ledger is a test instrumentation of parsed command fields, not a formal
proof against side channels. In a network capture, the entry still sees the
client's address, the middle sees neighboring relays, and timings/lengths can
remain correlatable.

## Important security boundaries

This harness is deliberately limited to IPv4 loopback. Relay-to-relay links are
not mutually authenticated; the descriptors are caller-pinned in memory, not
loaded from a signed and revocable directory. The handshake's MALEBOLGE key
expansion is custom, not Tor wire-compatible, and requires independent review.
The implementation is intended to validate control flow and knowledge
separation, not establish production security.

Not yet implemented: application data streams, flow control, congestion control,
fragmentation, authenticated inter-relay transport, signed relay descriptors,
key rotation/revocation, distributed replay control, resource quotas, circuit
teardown races, traffic mixing/padding, or correlation-attack evaluation.
Never bind these relays to a public interface or use them for sensitive traffic.

## Exit criteria before proceeding to a distributed testbed

1. Independent review of the exact handshake/KDF and byte framing.
2. Signed descriptor format with expiry, key rotation and revocation.
3. Authenticated relay-to-relay transport bound to the target descriptor.
4. Fault-injection tests for timeout, partial extension, connection loss, replay,
   repeated extension, resource exhaustion and wrong peer identity.
5. Real bidirectional stream protocol with bounded buffering and congestion control.
6. An explicit attacker model and WAN test methodology before making anonymity
   or speed claims.
