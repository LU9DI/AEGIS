# PIR RPC durable replay protection: design and validation plan

Status: opt-in prototype implemented on the associated draft PR; deployment validation and independent security review are still required.

Related findings:
- [Issue #30: persist replay protection across process restarts](https://github.com/LU9DI/AEGIS/issues/30)
- [Issue #26: wall-clock discontinuities](https://github.com/LU9DI/AEGIS/issues/26)
- [Issue #23: rate limits versus replay-cache capacity](https://github.com/LU9DI/AEGIS/issues/23)
- [Issue #9: verifiable PIR answers](https://github.com/LU9DI/AEGIS/issues/9)

## Security invariant

For a given server identity and accepted nonce, no second request using that nonce may be admitted during the entire period in which the original signed request can be valid. This must remain true across restarts, crashes, multiple workers sharing the store, and overlapping old/new processes. If the service cannot establish the invariant, it rejects new requests.

This mechanism prevents replay only. It does not establish that a PIR answer was computed correctly; issue #9 is independent.

## Proposed storage boundary

The current prototype uses Python's standard-library SQLite implementation behind a small replay-store class, and the RPC server can opt into it with explicit configuration. Do not silently select this backend for remote deployments until configuration, migration, and operational requirements are explicit.

The database must be provisioned at a configured absolute path in a service-owned directory. The current prototype checks that the immediate parent is a non-symlink directory owned by the effective service identity and is not group/world-writable on POSIX. On POSIX it also requires the database file itself to be owned by the effective service identity and have mode 0600. It rejects symlink/non-regular database paths. These checks still have a path-replacement/TOCTOU gap and do not validate every ancestor directory; they are defense-in-depth, not a race-free open primitive. Document platform-specific limits rather than claiming identical guarantees on every OS. A local SQLite file is not a defense against a privileged attacker who can replace or restore the entire state directory.

Suggested schema:

- `metadata(key PRIMARY KEY, value)`: schema version and persisted wall-clock high-water mark.
- `seen_nonces(server_id, nonce, first_seen_wall, expires_at_wall, PRIMARY KEY(server_id, nonce))`: durable replay records.

Nonce strings must be validated to the protocol's exact expected representation and size before storage. Use bound SQL parameters only. Set an explicit busy timeout and verify database/schema health at startup. Do not use an in-memory fallback if storage is unavailable.

## Atomic admission transaction

Every worker must use the same database file. Each admission performs one write transaction (for SQLite, use `BEGIN IMMEDIATE` or an equivalent serialized write transaction):

1. Read and validate schema metadata and the persisted clock high-water mark.
2. Compare current wall time against the high-water mark. If it regresses beyond a narrowly documented tolerance, abort and latch the service into fail-closed mode. Update the high-water mark in the same transaction.
3. Check request timestamp freshness against the current wall clock and the configured skew window.
4. Delete only records whose expiry is safely in the past under the accepted clock-trust policy.
5. Insert the nonce with its unique key. A uniqueness conflict means replay and must be rejected.
6. Enforce capacity and configured rate/burst constraints without deleting live entries. If capacity cannot be guaranteed, roll back and reject.
7. Commit before executing the expensive PIR operation or sending a successful response.

Any database exception, lock timeout, integrity failure, schema mismatch, uncertain initialization, or commit failure must reject the request. Never catch such failures and continue with memory-only replay checks.

## Time, expiry, and rollback limits

A monotonic clock is appropriate for measuring elapsed time within one process, but its origin is not portable across reboot or process lifetime. Durable expiry therefore needs an explicit wall-clock trust policy, with a persisted high-water mark and fail-closed behavior on detected rollback. The original signed timestamp remains subject to the protocol freshness window.

A high-water mark stored only in the same SQLite file cannot detect restoration of an older database snapshot: both the nonce table and high-water mark can be rolled back together. Strong protection against snapshot/VM/host rollback requires an independent monotonic anchor (for example, a separately protected external service or hardware-backed counter) or an operational guarantee that such rollback is excluded. If neither is available, document that limitation prominently and do not claim rollback-resistant replay protection.

Do not use SQLite row count alone as an unbounded capacity policy. The configured maximum request rate, burst, retention duration, and memory/disk budget must be mutually consistent. Refuse unsafe configuration at initialization and never evict unexpired entries to recover capacity.

## Failure and lifecycle behavior

- Database missing on a previously initialized deployment: do not silently create an empty store; require explicit provisioning/recovery.
- New deployment: initialize only in a trusted, private directory, with exclusive creation and schema validation.
- Corruption or failed integrity check: fail closed; recovery requires an explicit operator procedure that cannot silently reset replay history.
- Process crash: SQLite transaction recovery must leave either the committed nonce or no successful admission; no response may be treated as successful before commit.
- Concurrent processes: uniqueness and transaction serialization must prevent duplicate admission.
- Backup restore: reject or require an independently verified freshness anchor; a restored file alone is not evidence that replay history is current.
- Disk full, read-only filesystem, permission changes, lock contention, or I/O errors: reject admissions and surface a sanitized operational error without logging nonce contents or request secrets.
- Cleanup: run transactionally and delete only expired records; do not expose nonce values in logs or metrics.

## Required tests before merge

1. Accept a nonce, close/reopen the store, and reject the same nonce.
2. Race multiple store instances/processes attempting the same nonce; exactly one admission may succeed.
3. Kill a worker around transaction/commit boundaries and verify recovery is fail-closed and consistent.
4. Test timestamps at both freshness-window boundaries and expiry boundaries.
5. Simulate forward and backward wall-clock changes, including restart, and confirm no old request becomes admissible.
6. Corrupt the database, alter schema version, make the file unavailable/read-only, exhaust disk space where practical, and verify no memory-only fallback occurs.
7. Verify symlink/path replacement and unsafe permissions are rejected on supported platforms.
8. Fill capacity with live nonces and verify new requests are rejected without evicting any live nonce.
9. Test configured request rate/burst against maximum retention and capacity; reject unsafe configurations.
10. Simulate restoring a stale database snapshot. If no independent freshness anchor exists, assert the documented limitation rather than a false pass.
11. Ensure no successful response is emitted before the nonce transaction commits.
12. Verify logs, exceptions, and metrics do not disclose nonce values, query indices, shared keys, or request payloads.

## Deployment and review gates

- Keep remote production use disabled until the persistence path and lifecycle are explicitly configured.
- Document filesystem, process model, backup, restore, container/VM snapshot, and host trust assumptions.
- Run the full PIR RPC regression suite and relevant workflow checks, plus the new multi-process tests.
- Review the transaction boundaries, error handling, schema migration, path hardening, and rollback assumptions independently.
- Do not close issue #30 until acceptance criteria pass and the limitations are accepted.
- Do not claim production readiness while issue #9 remains unresolved; transport authentication and replay resistance do not prove PIR answer correctness.

## Implementation note

The draft PR implements an opt-in SQLite nonce store and connects it to the RPC server when explicitly supplied. This is not enabled by default and is not production-ready. Tests cover persistence across reopen, thread/process races, clock sampling under the write lock, simulated process death before commit, exact timestamp-window boundaries, conservative future-edge nonce retention, expiry cleanup, capacity, extreme timestamps, clock rollback, corruption, schema mismatch, symlinks, foreign-owned database rejection, unsafe parent permissions, SQLite setup-failure cleanup, rollback-failure latching, connection-close failure latching, and explicit initialization. Still outstanding are broader crash/fault injection (including real power loss and commit failure), race-free filesystem/path handling, deployment configuration and recovery validation, and an independent review. The same-database high-water mark cannot detect stale snapshot restoration.
