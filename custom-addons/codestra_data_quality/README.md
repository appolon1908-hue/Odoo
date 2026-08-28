# Codestra Data Quality

A company-scoped review queue for invalid phone or email values, incomplete records, duplicate candidates, conflicting identities, and cross-reference mismatches. It complements the existing normalization and lead-validation engines without automatically merging or deleting business records.

Every issue has a deterministic idempotency key, bounded model type, source and duplicate record references, severity, assignment, and reviewed resolution. Merge and ignore decisions remain human-controlled and auditable.
