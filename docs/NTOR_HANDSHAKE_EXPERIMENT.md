# MALEBOLGE one-hop ntor-derived handshake experiment

**Status: research-only, local test harness. Not a production protocol.**

This experiment adds an ephemeral per-hop key agreement based on the Tor `ntor`
Curve25519/SHA-256 handshake transcript. It does **not** make MALEBOLGE
interoperable with Tor: the derived traffic keys use a MALEBOLGE-specific HKDF
`info` label because this lab protects its request/response envelopes with
ChaCha20-Poly1305, not Tor relay-cell ciphers and digest keys.

Reference specifications:

- Tor CREATE/CREATED and `ntor` specification: https://spec.torproject.org/tor-spec/create-created-cells.html#ntor
- Tor key derivation: https://spec.torproject.org/tor-spec/setting-circuit-keys.html
- Tor design proposal 216: https://spec.torproject.org/proposals/216-ntor-handshake.html
- Noise Framework for future comparison: https://noiseprotocol.org/noise.html

## Input trust model

The client must already possess an authenticated binding between the relay's
20-byte identity digest and its 32-byte static Curve25519 onion public key. In
the Tor architecture, these values are obtained through authenticated directory
metadata. This module accepts those inputs directly and therefore does not
implement or validate a signed relay directory, descriptor expiry, key rotation,
or identity-to-key certification. Substituting both values before the handshake
is outside the guarantees of this module.

The relay keeps a static X25519 onion private key and generates a new
ephemeral X25519 key for each handshake. The client likewise generates a fresh
ephemeral keypair. The server's authenticator binds the ephemeral DH result and
static DH result to the relay identity digest, static onion key, both ephemeral
public keys, protocol identifier, and server role. The client validates this
authenticator before accepting the derived keys. The client is intentionally
not authenticated: anonymous clients should not need a stable identity.

## Wire messages

The binary handshake is fixed-size in this experiment:

- Client request: `identity_digest (20) | relay_onion_public_key (32) | client_ephemeral_public_key (32)` — 84 bytes.
- Relay response: `relay_ephemeral_public_key (32) | ntor_authenticator (32)` — 64 bytes.

The relay rejects an identity digest that does not match its configuration, a
static onion key that does not match its private key, a malformed message, and
invalid/low-order Curve25519 public values. The client rejects an invalid
response authenticator or malformed response. Client handshake state is
one-shot.

## Key schedule

The DH transcript and relay authenticator use the `ntor-curve25519-sha256-1`
protocol identifier and the specified HMAC-SHA256 tags. After the transcript is
authenticated, this experiment derives 64 bytes with HKDF-SHA256, using the
ntor key-extraction tag as salt and a MALEBOLGE-specific information label. The
first 32 bytes are the request AEAD key and the second 32 bytes are the response
AEAD key. Separate keys reduce cross-direction nonce/key interaction. This
last expansion and 32/32 partition are **MALEBOLGE-specific**, not Tor's relay
key schedule.

The module intentionally does not claim secure erasure of ephemeral private
keys: Python objects and the underlying cryptographic library do not give this
prototype a verified zeroization guarantee. There is also no independent code
review or formal proof of this adaptation.

## Replay and denial-of-service limits

An optional process-local replay guard rejects reuse of the same
`(identity_digest, client_ephemeral_public_key)` pair and fails closed at its
configured capacity. The guard resets when the relay restarts, consumes memory,
and by itself is not a complete DoS control. A real relay needs admission
control, rate limits, bounded handshake concurrency, resource budgets, key
rotation, and a carefully reviewed replay policy.

## Benchmarks

`rea-anon-ntor-bench --rounds 100 --output experiments/ntor-loopback.json`
measures both in-process cryptographic work and a new TCP connection for each
one-hop handshake on `127.0.0.1`. The output records the environment, sample
counts, handshake bytes, p50/p95 times, and explicit limitations. These numbers
are not WAN measurements and do not measure bulk throughput, circuit extension,
traffic analysis, or browser navigation.

## What is not implemented

- Telescoping circuit extension that lets the client add later hops through the
  established circuit without giving the entry relay the complete path.
- An authenticated directory or relay-descriptor format and secure update flow.
- Integration of these ephemeral keys into the current protocol-v2 circuit.
- Bidirectional multiplexed streams, per-stream flow control, congestion control,
  cover traffic, mixing, padding, or defenses against timing correlation.
- Distributed relay selection, anti-Sybil admission, compromise recovery, or an
  independent cryptographic review.

**Do not expose the relay or use the handshake for sensitive communication.**
The next gate is a reviewed circuit-extension design that keeps downstream
relay identity information hidden from the entry hop, with transcript tests and
negative vectors. Directly handshaking with every relay from the client would
reveal the route and is not an acceptable shortcut.
