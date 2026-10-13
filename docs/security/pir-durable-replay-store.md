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
