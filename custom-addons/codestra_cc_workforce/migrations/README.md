# Migration policy

This is an initial additive schema. Future migrations must be restartable and idempotent, preserve employee, attendance, schedule, and telephony references, reconcile before/after counts, and retain rollback evidence.

No destructive migration, record deletion, table truncation, business-table drop, or unreviewed column removal is permitted.
