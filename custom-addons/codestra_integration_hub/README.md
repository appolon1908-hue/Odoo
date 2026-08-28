# Codestra Integration Hub

## Purpose and ownership

This addon is the durable, Odoo-local, redacted integration ledger. Odoo stays
the business system of record. Contact Center Middleware owns future transport,
cross-system retry, adapter execution, and reconciliation. n8n may orchestrate
approved workflows but is not the authoritative event, audit, or idempotency
store.

The addon extends the compatibility-owned event, dead-letter, mapping, and
audit models without moving or renaming their tables or XML IDs. It adds
delivery-attempt history, scoped idempotency, and logical endpoint references.

## Lifecycle and idempotency

Events follow `new -> validated -> queued -> processing -> processed`, with
explicit retry, failure, dead-letter, and ignored states. Scoped SHA-256 key
fingerprints prevent raw idempotency keys from being stored. Equal replays
return the existing event; changed-payload reuse records a controlled conflict.

## Redaction and security

Payloads are recursively redacted before storage, canonicalized, bounded to
64 KiB, and content-hashed. Integration Administrators manage Hub records.
Managers have operational read access. Agents, Closers, Supervisors, QA
Reviewers, and Compliance Officers receive no Hub access by default. Audit and
idempotency records are immutable and dead letters cannot be deleted.

## Disabled delivery

There is no HTTP client, socket, public controller, delivery action, or active
retry processor. Endpoints default disabled and test-only. The only cron is an
inactive reporting-only count and performs no delivery.

## Installation and testing

Install only in an approved test database with `--test-enable`, explicit
database settings, and `--stop-after-init`. The compatibility ledger currently
exists through the installed `codestra_vicidial_crm`; this addon intentionally
does not declare a dependency on that domain-specific addon.

## Known limitations

Transport, reconciliation, signed cross-system audit, executable replay,
endpoint secret resolution, and production migration are deferred to
middleware and later gated phases.

## Rollback

Uninstall only in the disposable test database if validation permits, or
restore the validated pre-edit custom-format dump. Restore source from the
validated Phase 4A archive. Production needs no rollback because this phase
does not modify it.
