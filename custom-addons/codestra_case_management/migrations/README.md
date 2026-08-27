# Migration policy

The initial module creates only new case-management records and does not rewrite existing customer, lead, campaign, call, consent, or audit records. Every future migration must be restartable and idempotent, reconcile before/after counts, retain external IDs, and provide rollback evidence.

No destructive migration, record deletion, table truncation, business-table drop, or unreviewed column removal is permitted.
