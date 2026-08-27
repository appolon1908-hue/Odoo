# Migration policy

The initial module creates only new case-management records and does not rewrite existing customer, lead, campaign, call, consent, or audit records. Any future migration must be restartable, idempotent, count-reconciled, and independently reviewed.
