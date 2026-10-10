# AEGIS v0.27.0 design note — verifiable two-server PIR

Status: **design and threat-model artifact only**. This document does not implement a proof system and does not change the security claims of v0.26.0.

## 1. Problem statement

The current two-server XOR PIR client computes `answer_a XOR answer_b`. TLS authenticates each endpoint and protects each connection, but neither TLS nor the current snapshot fingerprint proves that an endpoint computed its answer from the committed database. A malicious authenticated replica can return a modified answer and the current client may reconstruct corrupted data.

The design objective is to let a client reject an incorrect answer without downloading the database and without disclosing the target index to either replica. It must not silently fall back to unverified responses.

## 2. Existing protocol model

For a database of `N` fixed-width records, the client creates masks `q_a` and `q_b` such that `q_a XOR q_b` is the one-hot vector for the target index. Each server returns the XOR of the records selected by its own mask. The client XORs the two responses.

The index-hiding property is per-server and assumes the replicas do not collude. If both replicas collude, they can XOR their masks and recover the target index. Verifiable computation does not remove this collusion limitation.

## 3. Required proof statement

For each replica, the verifier must validate a statement equivalent to:

- `root` is the approved commitment to the exact dataset snapshot and schema;
- `q` is the exact query mask sent to this replica, with canonical length and zero padding bits;
- `y` equals the bytewise XOR of every fixed-width record `D[i]` for which bit `q[i]` is set;
- `N`, record width, dataset epoch/version and protocol version match the request;
- the proof is bound to the response and cannot be replayed as a response to a different query or snapshot.

The proof must not reveal unselected record contents or require the client to disclose the other replica's query mask. Query masks are client-generated; each replica already sees only its own mask.

## 4. Candidate constructions to evaluate

### A. Succinct proof of computation

A proof system can prove that the response is the result of the specified XOR computation over a dataset committed by `root`. The circuit must bind the dataset commitment, query mask, dimensions, epoch and output. A naive circuit that recomputes a Merkle root over the entire dataset for every query may be prohibitively expensive; benchmark proving time, verification time, proof size, memory, and setup assumptions before selecting it.

### B. Vector/polynomial commitment with a linear-query proof

Investigate a commitment scheme that supports proving the required aggregate over committed records without revealing the records. The algebra must match the protocol's bytewise XOR semantics; a generic additive commitment cannot simply be assumed to preserve XOR. Specify field encoding, binding/hiding properties, proof soundness, setup assumptions, and how updates change the commitment.

### C. Replication or spot checks

Extra replicas, majority voting, random spot checks, or signed snapshot metadata may help availability or detect some faults, but are not by themselves a proof that an answer is correct. They must not be labeled verifiable PIR unless the malicious-server soundness argument is explicit and quantified.

## 5. Snapshot lifecycle

A snapshot identifier must be derived from canonical dataset bytes plus schema/protocol metadata. A trusted publisher or authenticated update channel must authorize the commitment and monotonically increasing epoch. The client must reject unknown roots, rollback epochs, malformed proofs, proof/response mismatches, and version disagreement between replicas. TLS certificate identity and dataset authorization are separate trust domains.

A signed hash alone authenticates the publisher's statement about a snapshot; it does not prove that a server used that snapshot to compute a particular response.

## 6. Fail-closed client behavior

The eventual API should return a verified record only after both individual response proofs and cross-replica metadata checks pass. Any invalid or missing proof must raise a distinct verification error and must not return the reconstructed bytes as a successful result. Logging must exclude target indices, query masks, record contents, and stable per-query identifiers by default.

The unverified v0.26.0 path must remain explicitly marked experimental and must never be presented as equivalent to the verified path. Do not silently enable a mock verifier or a test-only proof in production-facing code.

## 7. Red-team acceptance matrix

The implementation phase must include at least these cases:

1. Honest replicas and matching committed snapshot — verification succeeds.
2. One replica flips one output bit — verification fails.
3. Replica returns arbitrary output but the expected snapshot identifier — verification fails.
4. Proof generated for a different query mask — verification fails.
5. Proof generated for a different snapshot root, schema, record width, or epoch — verification fails.
6. Truncated, malformed, oversized, or non-canonical proof — rejected within explicit resource bounds.
7. Replay of a prior response/proof against a different request — rejected by statement binding.
8. One replica is stale while the other is current — client fails closed rather than mixing epochs.
9. Invalid proof does not leak query material in logs or error output.
10. Test harness confirms that tampering with proof, response, public inputs, or commitment independently is detected.

## 8. Performance and privacy measurements

Measure proof-generation latency and peak memory at several database sizes, verification latency, proof bytes, request/response bytes, and throughput under the existing aggregate token bucket. Report both cold and warm runs and include hardware/runtime details. Verify that per-server query-mask distributions remain independent of the target index. Include explicit tests and documentation for replica collusion, traffic metadata leakage, and database confidentiality assumptions.

## 9. Release gate

Do not call the feature “verifiable PIR” until a reviewed construction is selected, the proof statement and assumptions are documented, a real cryptographic implementation is integrated, tampering tests pass, and performance costs are reported. Until then, v0.26.0 remains the last validated implementation release and this note is a design artifact only.
