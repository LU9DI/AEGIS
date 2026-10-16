# AEGIS prototype security review — path/anonymity components

Status: **internal source review for the loopback research lab.** This document is a
read-through with test-inventory support, not a formal audit, not third-party review, and
not proof that defects are absent. No component below is approved for production or for
non-loopback traffic.

Date: 2026-10-16. Branch: `perf/reproducible-baseline-plan`.

## Scope and method

- Source read-through of the path/anonymity prototypes: onion framing, handshake,
  circuit extension, relay, signed directory, offline route selection.
- Cross-check against the existing regression/negative test suite (names cited below).
- Scope boundary: the PIR/RPC/TLS subsystem is out of scope here; it has its own dated
  reports (`AEGIS-V0.26.0-*`, `AEGIS-V0.27.*`) and its own fail-closed tests.

| Component | Role | Primitives used |
| --- | --- | --- |
| `src/anonlab/onion_protocol.py` | v2 onion request/response envelopes, layered construction | ChaCha20-Poly1305, fresh per-envelope nonces, SHA-256 labels |
| `src/anonlab/ntor_experiment.py` | ntor-style link handshake, key derivation | X25519, HKDF-SHA256, HMAC, `cryptography` Ed25519 |
| `src/anonlab/telescoping.py` | telescoping circuit-extension PoC over loopback | ChaCha20-Poly1305 envelopes, Ed25519 link authentication, nonce replay guard |
| `src/anonlab/onion_relay.py` | loopback relay endpoint | optional directional AEAD keys (request/response separated) |
| `src/anonlab/directory.py` | signed relay descriptors, authority, revocation | Ed25519 (relay + authority), strict schema, SHA-256 digests |
| `src/anonlab/route_selection.py` | offline route selector (reference for AS policy) | pure Python constraints |

## Component findings

### 1. `onion_protocol.py` — onion envelopes (prototype)

Observed mitigations:
- ChaCha20-Poly1305 with a fresh random 12-byte nonce per envelope; envelopes are
  nonce‖ciphertext‖tag with a minimum-length check (16-byte tag), so truncated envelopes
  are rejected before decryption.
- Frame headers (version, circuit id, sequence, length fields) are **inside** the AEAD
  envelope; only a bounded outer length prefix is unauthenticated (size-capped at
  16 MiB, validated before body read). Direction prefix + hop identifier are bound as
  AAD (`_aad(direction, relay_id)`), so request/response confusion and relay-id swapping
  fail the tag.
- Sequence numbers are validated against the expected value with an explicit
  "replay, reordering, or circuit desynchronization" error path. `CircuitReplayGuard`
  rejects duplicate circuit ids and **fails closed when its registry is full**.
- The module docstring itself marks the replay handling as production-incomplete
  ("production should use fresh ephemeral circuit keys and a reviewed replay…").

Gaps:
- Replay registry is process-local and bounded; the fail-closed-full behavior is a
  deliberate availability tradeoff that needs a reviewed rate-limit/eviction strategy
  before any exposed deployment.
- Legacy v1 framing is retained for protocol compatibility; the v2/v1 mix must never be
  treated as a stable wire format.

Test evidence: `test_aead_detects_tampering`, `test_response_round_trip_binds_circuit_and_sequence`,
`test_request_layer_carries_authenticated_circuit_and_sequence`,
`test_replay_guard_rejects_duplicate_ids_and_fails_closed_when_full`,
`test_live_relay_rejects_replayed_first_frame_on_new_connection`,
`test_three_hop_encrypted_request_response_integrity`.

### 2. `ntor_experiment.py` — link handshake (prototype)

Observed mitigations:
- X25519 with explicit low-order point rejection on both sides; the relay claims replay
  state only **after** the static DH succeeds, so malformed low-order keys cannot consume
  replay slots.
- HKDF-SHA256 with a MALEBOLGE-specific `info` string (`…:key_expand:MALEBOLGE_AEAD_v1`),
  deliberately not Tor's, preventing cross-protocol key reuse between this lab and Tor.
- Client state is one-shot: discarded after `client_finish` succeeds or fails; server
  authentication failure is a distinct error path.
- `NtorReplayGuard`: bounded, fail-closed when full, keyed on
  (identity digest, client ephemeral). Docstring notes production needs a reviewed
  DoS/rate-limit strategy.

Gaps:
- The transcript/KDF is AEGIS-specific and **not wire-compatible with Tor**; no independent
  cryptographic review.
- The handshake is not yet wired end-to-end into the relay CLI: relay processes still take
  pre-shared key files (`--key-file`, `--response-key-file`), which the README labels "test
  inputs, **not** a secure key-distribution mechanism."

Test evidence: `test_client_rejects_tampered_server_authenticator`,
`test_client_state_is_one_shot`, `test_client_rejects_low_order_relay_ephemeral_key`,
`test_relay_rejects_wrong_identity_digest`, `test_relay_rejects_stale_or_wrong_onion_public_key`,
`test_relay_rejects_low_order_client_public_key`,
`test_replay_guard_rejects_reused_ephemeral_and_fails_closed`, `test_malformed_handshake_length_rejected`,
`test_each_handshake_derives_fresh_keys`.

### 3. `telescoping.py` — circuit extension PoC

Observed mitigations:
- Docstring states plainly: "not Tor-compatible or production-safe"; hop-local framing
  documentation explicitly says adjacent relays observe timing, sizes, stream identifiers
  and direction — i.e., the framing is **not** claimed to be an anonymity boundary.
- Relay-to-relay links authenticate with Ed25519 signatures over domain-separated payloads
  with a 32-byte nonce and a bounded `LinkReplayGuard` (replayed nonce → error);
  identity digests are `SHA-256("MALEBOLGE/relay-identity/v1\0" ‖ pubkey)[:20]` and every
  digest/signature comparison uses `hmac.compare_digest` or library verification.
- Extension requests are sealed from the last hop backwards through every hop (chained
  AEAD with per-hop AAD binding), so earlier relays see only FORWARD + opaque bytes;
  responses are unwrapped hop-by-hop with sequence and stream-id checks inside each
  envelope.
- Fail-closed behavior: any extension failure drops the pending reply and closes the
  circuit; duplicate relays are rejected before network writes; `MAX_HOPS` and an explicit
  command budget bound the work; verified-route freshness is re-asserted after extension.

Gaps:
- Same replay-registry and review caveats as above.
- Stream/flow metadata visible to adjacent relays is inherent to the current framing; it is
  documented but should be quantified before any anonymity claim (the synthetic
  privacy-eval harness does not exercise this path — see `experiments/PRIVACY-EVAL-SWEEP-REPORT.md`).

Test evidence: `test_relay_to_relay_link_requires_and_rejects_replayed_nonce`,
`test_guard_rejects_server_signature_from_wrong_identity`,
`test_relay_rejects_invalid_initiating_identity_signature`,
`test_client_rejects_duplicate_hop_before_network_write`,
`test_replayed_extension_frame_is_rejected`, `test_oversized_frame_is_rejected_before_body_read`,
`test_client_fails_closed_when_command_budget_is_exhausted`,
`test_descriptor_rejects_non_loopback_endpoint`, `test_exit_rejects_unallowlisted_loopback_destination`,
`test_relay_rejects_connections_above_configured_cap`.

### 4. `directory.py` — signed descriptors and revocation

Observed mitigations:
- Dual Ed25519 signatures (relay over its own descriptor, authority over relay-signed
  descriptor); verification failures raise. Domain-separated signing payloads per object
  type; strict key-set validation rejects missing **and** unknown fields.
- Rollback protection and revocation feeds are compared with `hmac.compare_digest`;
  conflicting same-sequence descriptors, expired/not-yet-valid descriptors, unsorted or
  duplicate revocations, and malformed persistent state all fail closed.
- JSON parsing rejects non-objects, duplicate fields and oversized input.

Gaps:
- Trust anchor is a single local authority key: authority compromise/leak equals full
  descriptor control. That is acceptable for a lab PKI, and must be redesigned (threshold
  or multi-authority model) before any multi-operator use.
- Key handling is file-based with no rotation ceremony beyond what tests exercise.

Test evidence: `test_endpoint_tampering_fails_relay_signature`,
`test_onion_key_tampering_fails_signatures`, `test_wrong_trust_anchor_fails_authority_signature`,
`test_conflicting_descriptors_same_sequence_rejected`, `test_revoked_relay_is_rejected`,
`test_revocation_snapshot_tampering_rejected`, `test_revocation_expiry_and_rollback_rejected`,
`test_strict_schema_rejects_unknown_fields`, `test_json_parser_rejects_duplicate_fields`,
`test_malformed_or_permissive_persistent_state_fails_closed`.

### 5. `onion_relay.py` — loopback relay

- Bind-address guard restricts endpoints to loopback (and DNS names/remote hosts are
  rejected in descriptor validation); changing this guard is explicitly not a deployment
  step. Optional response-direction key enables request/response key separation per relay.
- No per-client automatic key provisioning yet (pre-shared key files remain), matching the
  README's stated remaining gap.

### 6. `route_selection.py` — offline selector

- Enforces per-route constraints including at most one relay per ASN; the privacy-eval
  harness now mirrors that policy by default (see README §5.2, schema 2). Consistency
  between the two is covered by `tests/test_privacy_eval.py`.

## Cross-cutting assessment

Strengths:
- No hand-rolled primitives: all cryptography comes from `cryptography` (ChaCha20-Poly1305,
  X25519, Ed25519, HKDF-SHA256) plus stdlib SHA-256/HMAC for labels and digests.
- Consistent domain separation (MALEBOLGE-prefixed KDF info, AAD direction+hop binding,
  per-object signing domains) and consistent constant-time digest comparison.
- Fail-closed posture throughout (replay registries, frame limits, strict schemas,
  loopback-only bind, budget exhaustion closes circuits).
- Unusually honest scope labeling in docstrings and README; no prototype in this set
  presents itself as deployed crypto.

Ranked gaps (none exploitable as-is in the documented loopback scenario, all blocking for
anything beyond it):
1. **No independent cryptographic/protocol review** of the composed protocols
   (handshake + envelope + framing + circuit extension).
2. **Replay/DoS tradeoff**: process-local registries that fail closed when full; an
   unauthenticated flood can force rejection under a networked deployment.
3. **Key management not finished**: ntor not integrated into the relay CLI; pre-shared key
   files are lab inputs; single-authority PKI.
4. **Metadata exposure inherent to framing** (timing/sizes/stream ids to adjacent relays) is
   documented but unquantified.
5. **Wire format is lab-only** (not Tor-compatible) and must be versioned/reviewed as a
   protocol artifact before any external use.

## Review limitations

- This was a source read-through plus test inventory, not exhaustive line-by-line proof,
  not fuzzing beyond the unit suite, not formal verification.
- No confirmed exploitable defect was found in this pass; that is **not** evidence of
  absence of defects.
- Nothing here should be quoted as "the prototypes are secure." The accurate statement is:
  the prototypes implement standard primitives with documented fail-closed behavior and
  extensive negative tests, under documented loopback-only assumptions, and require
  independent cryptographic review before any deployment consideration.
