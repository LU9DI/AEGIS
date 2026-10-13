# PIR durable replay store: security and deployment boundaries

The SQLite replay store is an opt-in, local durability mechanism. It is not, by itself, a complete defense against privileged rollback or hostile filesystem mutation.

## Required deployment conditions

- Provision the database directory before starting the service. It must be owned by the service identity and not group/world writable.
- Keep the database on a local filesystem with documented SQLite locking and durability semantics. Do not assume network filesystems or container overlay filesystems provide equivalent crash guarantees without validation.
- Restrict write access to the database, its directory, and any containing volume to the service identity and trusted operators.
- Persist the database independently of ephemeral container layers. Backups and restores must be treated as security-sensitive operations.
- Do not delete, replace, or restore the database while the service is running. After any restore or suspected rollback, keep admission disabled until an operator re-establishes trusted state.

## Snapshot rollback limitation

The `wall_high_water` value and nonce rows live in the same SQLite database. Restoring an older copy can therefore roll back both the nonce history and the high-water mark. The database cannot independently prove that it is the newest copy.

Production deployment must choose and validate an independent anti-rollback mechanism before claiming protection against snapshot restoration. Suitable architecture options include a remote trusted monotonic/version anchor, an append-only external witness, or storage/platform controls that cryptographically or operationally prevent rollback. The anchor must be updated atomically with admission semantics, survive the same failure domain as the replay database, and have a defined recovery protocol. Merely moving another copy of the high-water mark into the same snapshot domain does not solve rollback.

Until such a mechanism is implemented and tested, the threat model must explicitly exclude an attacker or operator capable of restoring old database snapshots. This limitation is not resolved by the in-process `_untrusted` latch, because a process restart creates a new instance and a restored database may appear internally consistent.

## Filesystem race limitation

The store checks path type, owner, and mode before SQLite opens the path by name. Those checks and SQLite's open are separate operations; an attacker able to mutate the directory concurrently may exploit a time-of-check/time-of-use race. Mode and ownership checks reduce exposure but do not eliminate it.

Use a service-owned, non-writable parent directory and a deployment model that prevents untrusted path replacement. Stronger guarantees require an implementation/platform design that binds validation to the same opened file identity used by SQLite; do not claim that a pathname check alone provides that guarantee.

## External replay authority: required contract for a production successor

The current repository has no independent trusted-time or anti-rollback service configured. The SQLite high-water mark is therefore only a rollback detector within the currently observed database history, not a trusted clock. Do not add a nominal `TimeProvider` abstraction and treat that alone as a security fix: an interface cannot create a trust boundary or atomicity that the deployment does not provide.

A production successor should place the authoritative admission decision behind an independently operated, durable authority with a documented trust boundary. Its operation must be equivalent to:

```text
admit(server_id, nonce_digest, issued_at, policy_id)
  -> committed receipt | reject
```

The authority must atomically and durably:
1. Validate the caller/service identity and the canonical nonce digest.
2. Obtain time from its explicitly trusted time policy, not from a caller-supplied timestamp or the application host's unchecked wall clock.
3. Check the signed request timestamp against the configured freshness interval using that trusted time.
4. Enforce nonce uniqueness for the entire validity/retention interval, across all workers and restarts.
5. Persist the reservation before returning a committed receipt.
6. Reject on unavailable storage, uncertain commit, clock-health failure, stale authority state, version rollback, or policy mismatch; never fall back to local memory.

The successful receipt should bind the server identity, nonce digest, policy/version, trusted-time observation, and unique authority transaction/version. It must not contain the raw nonce or request payload unless the threat model explicitly permits that. Receipt semantics must be idempotent for retry after a lost response: a retry may learn that its exact reservation committed, but must not create a second admission or cause a second PIR execution. The application must not begin protected work until it has a valid committed receipt.

**Atomicity requirement:** do not split “check an external clock” and “insert nonce in SQLite” into two independent calls and claim the combined operation is atomic. A crash between those operations leaves an ambiguity. Either the authority itself owns the nonce reservation as the source of truth, or the design must specify a reviewed distributed transaction/recovery protocol that prevents duplicate admission under every partial-failure ordering.

**Clock policy:** define how the authority detects its own time rollback, large forward steps, restart, failover, and loss of synchronization. A monotonic counter alone orders events but does not establish elapsed real time; a wall clock alone does not establish rollback resistance. If the authority cannot establish the validity decision, it must reject. If its trusted time is unavailable for longer than the protocol can safely tolerate, availability is sacrificed rather than silently extending or shortening nonce validity.

**Rollback domain:** the authority's anti-rollback state must not be restorable from the same snapshot or backup domain as the application database. Specify who can restore it, how the newest committed version is verified after recovery, and how service admission remains disabled until reconciliation completes. A remote service is not automatically independent if its database, credentials, backups, and restore operators share the same failure/security domain.

**Deployment gate:** before integration, identify the actual authority product/service, its consistency and durability guarantees, identity/authentication model, failure modes, time source and monitoring, retention/capacity model, backup/restore procedure, and operator ownership. No such backend is currently wired into this repository, so this section is a target contract, not an implemented guarantee.

## Failure handling and recovery

- Admission must commit the nonce reservation before the protected PIR operation proceeds.
- The observed wall-clock high-water mark is committed in a separate SQLite transaction before request-specific timestamp and duplicate-nonce rejection, so those rejections cannot roll back the already persisted clock observation. Nonce insertion remains serialized and transactional.
- Unexpected ordinary exceptions during connection setup, initialization, or admission latch the current store instance as untrusted.
- A rollback or close failure is treated conservatively; the caller must not infer that admission definitely did or did not commit.
- A partial database artifact is preserved for operator inspection rather than automatically removed or reset.
- Recovery must be explicit: stop admission, preserve evidence, validate the database and deployment state, and provision a fresh trusted state only under an approved procedure. Do not silently reinitialize an existing database.

## Validation still required before production

- Test abrupt process termination and power-loss behavior on the actual target filesystem and volume configuration.
- Exercise concurrent admission from multiple processes and across service restarts.
- Validate the chosen independent anti-rollback control, including backup restoration, failover, and recovery.
- Review ownership, permissions, mount options, backup policy, and container lifecycle in the deployment environment.
- Obtain an independent security review. The durable replay store does not address the separate PIR answer-verifiability/correctness question.
