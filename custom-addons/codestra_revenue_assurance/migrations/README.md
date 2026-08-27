# Migration policy

This is an initial additive schema. Future migrations must be restartable and idempotent, preserve rate-plan ranges, usage idempotency keys, source identities, immutable cost and revenue snapshots, invoice links, reconcile totals, and retain rollback evidence.

No destructive migration, record deletion, table truncation, business-table drop, or unreviewed column removal is permitted.
