# Migration policy

Version `19.0.2.0.0` adds only additive onboarding assignment, identity,
provisioning, and outbox-link fields. Existing readiness records are preserved
and remain non-executable until their new assignment fields are completed.

Every future migration must be restartable and idempotent, preserve employee,
membership, provisioning-request, and outbox links, reconcile state counts, and
retain rollback evidence.

No destructive migration, record deletion, table truncation, business-table
drop, or unreviewed column removal is permitted. Rollback disables new workflow
entry points and restores the previous module artifact; it never deletes
accepted audit, membership, provisioning, or delivery evidence.
