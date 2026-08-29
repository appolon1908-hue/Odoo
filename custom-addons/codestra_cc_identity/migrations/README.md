# Identity migration contract

This release adds new immutable identity-outbox, pinned-session, and
reassignment records plus additive links on campaign membership and the existing
provisioning request. It does not activate, rewrite, or delete any external
identity.

Before a later production upgrade, migration rehearsal must detect non-draft
memberships that lack a canonical identity UUID or governed desired-state
history, classify them for manual read-back, and keep them denied until all
required systems match. Rollback must preserve membership, outbox, read-back,
session-revocation, and reassignment evidence. No rollback may reactivate an old
membership or restore a revoked session.
