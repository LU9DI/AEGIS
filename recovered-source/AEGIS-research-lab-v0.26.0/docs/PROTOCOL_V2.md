# MALEBOLGE experimental envelope protocol v2

**Status:** loopback-only research format; not reviewed for production security.

## Goals

Protocol v2 adds message ordering and narrow replay defenses to the v0.3 loopback circuit. It does not try to solve traffic analysis and does not define a deployable network protocol.

## Cryptographic envelope

Each hop uses a 32-byte pre-shared ChaCha20-Poly1305 key for the duration of a benchmark run. Each envelope includes a fresh 96-bit AEAD nonce. Associated data identifies the protocol version's request/response direction and the configured relay identity. The relay identifier and direction are authenticated but not concealed from a relay that handles its own layer.

### Request plaintext header

| Field | Size | Meaning |
|---|---:|---|
| version | 1 byte | `2` |
| flags | 1 byte | `1` only for terminal relay; otherwise `0` |
| next port | 2 bytes | loopback-only next-hop port in network byte order |
| payload length | 4 bytes | exact number of following payload bytes |
| circuit ID | 16 bytes | random identifier chosen by the client for one TCP circuit |
| sequence | 8 bytes | unsigned, strictly increasing request number, starting at zero |
| payload | variable | inner encrypted layer or destination payload |

The fields are encoded in network byte order. Because the whole header is inside AEAD ciphertext, the circuit ID and sequence are integrity-protected and hidden from observers outside the relay that decrypts that layer.

### Response plaintext header

| Field | Size | Meaning |
|---|---:|---|
| version | 1 byte | `2` |
| circuit ID | 16 bytes | must match the active client circuit |
| sequence | 8 bytes | must match the response expected for the request |
| payload length | 4 bytes | exact number of following payload bytes |
| payload | variable | destination response, wrapped once per relay on the way back |

The client removes response layers in route order and checks circuit ID and sequence at each layer before accepting the final bytes.

## Relay state machine

1. A new TCP connection must begin with sequence `0`.
2. The first decrypted request claims its circuit ID in that relay process's replay guard. Reusing a seen ID is rejected.
3. Every later request on the same connection must carry the same circuit ID and the exact expected sequence.
4. Each successful request produces a response layer carrying the same circuit ID and sequence.
5. The relay increments its expected request sequence only after the response was written successfully.
6. A gap, duplicate, changed circuit ID, malformed frame, authentication failure, or sequence exhaustion closes the circuit.

The benchmark uses one sequential request/response at a time. This sequence model is not designed for concurrent multiplexed streams.

## Replay limitations

The process-local registry stores every circuit ID until process exit and fails closed when its configured capacity is reached. It has no eviction, expiration, distributed coordination, persistence, or recovery protocol. Restarting a relay resets it. This makes exact first-frame replay on a second connection fail during a benchmark run, but does not constitute a generalized replay defense for a public network. The static pre-shared keys also mean a captured valid envelope can remain cryptographically valid; production work must define a reviewed ephemeral-key and key-rotation lifecycle.

## Security properties and non-properties

Intended properties tested locally:

- integrity and authenticity of each AEAD envelope under its pre-shared key;
- request sequence continuity on a live circuit;
- response binding to the expected circuit ID and sequence;
- duplicate circuit ID rejection within one live relay process;
- explicit payload lengths and size limits.

Not provided:

- authenticated ephemeral key agreement or forward secrecy;
- anonymous relay discovery, relay identities/certificates, or path selection;
- global or distributed replay protection;
- confidentiality of the payload from the exit relay;
- concealment of timing, packet sizes, direction, destination at the exit, or circuit lifetime;
- traffic mixing, cover traffic, congestion control, general TCP/QUIC stream semantics, or multi-user isolation;
- resistance to a global passive observer, active probing, Sybil nodes, compromised relays, or intersection attacks.

## Required next gate

Before expanding beyond loopback, specify relay identity authentication and ephemeral key agreement against a named threat model, define forward secrecy and key lifetimes, test state-exhaustion behavior, add a general bidirectional stream state machine, and request independent cryptographic review. Do not deploy this protocol on public interfaces.

## Prior art to evaluate before key-exchange implementation

Do not invent a new Diffie–Hellman handshake for MALEBOLGE. Compare a circuit-creation design with the Tor Project's deployed `ntor` handshake specification ([Tor proposal 216](https://spec.torproject.org/proposals/216-ntor-handshake.html)) and vetted patterns from the [Noise Protocol Framework](https://noiseprotocol.org/noise.html). These references are inputs to protocol design, not drop-in replacements: we must still specify peer authentication, how the client obtains/pins relay identity keys, how handshake messages are telescoped through an onion circuit without revealing the full path to the first relay, and how key material is derived and rotated independently per hop.

The implementation gate should require test vectors, transcript binding, explicit rejection behavior for malformed/low-order public keys, key erasure where practical, and independent review before any public-network experiment.
