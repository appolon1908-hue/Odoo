# Automated Production Gates

This repository may support automated pull-request promotion without a mandatory human code-review count, while preserving deterministic production safety gates and a separate independent production-activation approval.

## Pull-request merge policy

- Required approving pull-request reviews: 0, only when the active repository ruleset is intentionally configured for this model.
- Required Code Owner pull-request reviews: optional under that same ruleset.
- Required exact-head and merge-result status checks: on.
- Strict/up-to-date branch requirement: on.
- Conversation resolution: on.
- Force pushes and protected-branch deletion: blocked.
- Auto-merge: permitted only after every required check and conversation gate passes.
- Administrator bypass is not part of the normal release path.

Removing a mandatory pull-request review count does not waive security ownership, risk acceptance, environment protection, deployment approval, or production activation approval.

## Production release policy

A source merge does not authorize deployment or external effects. Production promotion still requires all repository release-policy gates, including:

- source authority and exact source SHA;
- immutable image digest and artifact provenance;
- migration validation;
- security and dependency checks;
- database and filestore backup/restore evidence where applicable;
- staging and synthetic certification;
- rollback rehearsal and rollback identity;
- production read-only canary;
- zero unexpected live-effect movement;
- an independent production-activation approval bound to the exact candidate, evidence set, and deployment change.

The independent production-activation approver must not be replaced by CI success, the pull-request author, the deployment operator, auto-merge, or an administrator bypass. All live-effect flags remain disabled until that separate approval and every runtime gate pass.

For server `65.109.65.169`, preserve Odoo migration state, Middleware/Odoo API contract evidence, source SHA, image digest, rollback state, audit, tenancy, safety read-back, and the independent production-activation record. SSH access controls must not be changed.
