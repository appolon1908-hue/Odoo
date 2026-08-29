# ADR-003: Canonical identifiers require controlled migration

- Status: Accepted for staging implementation
- Date: 2026-08-28

## Decision

The 93 canonical campaign codes and their explicit VICIdial IDs in the supplied
authority are immutable controlled identifiers. Native length and uniqueness are
validated before use. The eight `*-CALLBACK-OUT` entries remain disabled technical
compatibility mappings with `agent_login_allowed=FALSE`; scheduled callbacks run
inside the source campaign and never create a shared callback team.

Existing hash-like IDs are not silently overwritten. Migration requires a
versioned desired/actual diff, collision classification, approval, disabled-state
adapter command, backup/rollback reference, read-back, and synthetic staging tests.

## Consequences

The current database snapshot has 93 identifier drifts and eight unmanaged mapping
records. Until migration evidence exists, identifier reconciliation is `PARTIAL`
and production provisioning is `PRODUCTION_BLOCKED`.
