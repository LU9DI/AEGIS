# PIR durable replay store: operator recovery runbook

Status: interim procedure for the opt-in SQLite prototype. This runbook does not establish trusted time or snapshot rollback resistance and is not authorization to reset replay state.

## Non-negotiable safety rules

- If replay admission is disabled or the store is marked untrusted, stop routing protected PIR requests to that instance and keep admission fail-closed.
- Never delete nonce rows, edit `wall_high_water`, downgrade the schema, replace the database with an unverified backup, or recreate the database just to restore service.
- Preserve the database file, its containing volume/snapshot metadata, service logs, deployment revision, and relevant timestamps before any recovery action. Restrict access to the evidence.
- Do not copy nonce values into tickets, logs, shell history, chat, or incident reports. Record hashes/metadata only where needed and approved.
- A process restart or a new `DurablePirReplayStore` object does not establish that the persisted state is trustworthy.

## Triage by failure class

### 1. Capacity exhausted

The prototype retains every committed nonce for the lifetime of the database. `max_entries` is therefore a lifetime admission budget, not a rolling cache capacity.

1. Remove the instance from service or leave admission disabled; do not repeatedly restart it hoping to clear capacity.
2. Preserve a read-only copy of the database and collect non-secret diagnostics: configured `max_entries`, row count for the affected `server_id`, disk health, deployment version, and time of the first failure.
3. Confirm that the failure is genuinely capacity exhaustion rather than corruption, permissions, lock contention, or clock distrust.
4. Do not delete old rows or raise the limit without a reviewed capacity and migration plan. Raising the limit does not replenish the lifetime budget or solve time-trust limitations; only a carefully reviewed configuration change may permit more admissions if the database and threat model remain valid.
5. Restore service only after an approved change and documented risk acceptance. If the safe capacity cannot be established, keep admission disabled.

### 2. Clock rollback, invalid clock, or metadata mismatch

1. Keep the affected instance out of service and do not try to repair the database by manually editing its high-water mark.
2. Check host time synchronization, virtualization/snapshot events, boot history, and whether other workers observed the same condition.
3. Preserve the original database and diagnostics. A backward-clock latch indicates that the local trust assumptions no longer hold; fixing the host clock does not automatically make the existing object or state trustworthy.
4. Require an explicit security/operator decision before reprovisioning. Reprovisioning a blank database without an independent freshness anchor can erase replay history and is not a safe automatic recovery.

### 3. Corruption, I/O error, uncertain commit, or close/rollback failure

1. Assume the outcome of the last admission may be uncertain. Do not retry protected work automatically and do not infer that the nonce was definitely not committed.
2. Keep the instance disabled; preserve the database and underlying storage evidence.
3. Inspect filesystem capacity, read-only/remount events, SQLite integrity, volume health, and logs using a controlled copy where possible.
4. Do not run an automatic repair or reset against the only evidence copy. Any repair must preserve the original and be reviewed.
5. Before resuming service, reconcile whether the last request may have been admitted and whether duplicate work is possible. If that cannot be established, keep service disabled until the operator selects a safe recovery boundary.

### 4. Suspected snapshot, VM, host, or backup rollback

1. Treat the replay history as potentially stale and immediately disable admission.
2. Preserve the restored state and backup/snapshot identifiers; do not overwrite evidence with another restore.
3. Compare against an independently protected version/receipt/witness if one exists. The current SQLite prototype has no such configured anchor, so the database alone cannot prove freshness.
4. If no independent anchor exists, do not claim rollback-safe recovery. The service must remain disabled until a separately reviewed recovery procedure establishes a new trust boundary and explicitly accepts the replay implications.

## Preconditions for returning to service

All of the following must be recorded by the responsible operator:

- Cause of failure and affected server identity/instances are identified.
- Original evidence and recovery artifacts are preserved with access restricted.
- The database is structurally valid and permissions/ownership match deployment requirements.
- The recovery action did not silently discard nonce history or alter the high-water mark.
- Capacity is sufficient under an explicit workload plan; the lifetime-budget trade-off is understood.
- Clock and storage health are verified, and the rollback threat model is explicitly addressed.
- Any uncertain prior admission has been reconciled or protected work remains disabled.
- A second reviewer approves the recovery record.

If any precondition cannot be demonstrated, do not resume protected admission.

## Production gate

This runbook is interim guidance for the prototype, not a substitute for an actual incident-response process. Before production use, implement and validate an independently operated admission authority that atomically enforces trusted-time freshness and nonce uniqueness, supplies idempotent committed receipts, and has a rollback domain independent of the application database. Validate crash/power-loss behavior and obtain an independent security review. Keep issue #30 open until its acceptance criteria are met.
