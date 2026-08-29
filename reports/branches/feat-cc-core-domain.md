# Branch close-out: feat/cc-core-domain

Status: `PASS` for the bounded core-domain scope

Overall recommendation: `STAGING-ONLY`

Production: `PRODUCTION_BLOCKED`

## Implemented

- Converted `codestra_cc_core` from a dependency facade to a concrete module.
- Added `cc.business.unit` and `cc.campaign` as one-to-one delegated canonical
  scopes over compatible legacy owners.
- Added `cc.campaign.channel` with idempotent legacy mapping adoption and strict
  disabled handling for the eight callback compatibility records.
- Added immutable campaign ownership through `cc.campaign.scoped.mixin`.
- Added versioned, hashed `cc.campaign.policy` envelopes; policy approval remains
  reserved for the later security/approval module.
- Added the full staging lifecycle and rejected active/production state.
- Added manager/system ACLs and configuration views; agents receive no access on
  this branch.
- Added idempotent data-load adoption and automatic adoption for compatible legacy
  records created after module installation.

## Tests and read-back

| Evidence | Result | Status |
| --- | --- | --- |
| Source CI | 59 manifests; strict review 0 errors/warnings; all source gates; 3 contract tests | PASS |
| Focused Odoo upgrade | 8 methods; 0 failed; 0 errors | PASS |
| Full clean Odoo install | 346 tests across 59 modules; 0 failed; 0 errors | PASS |
| Upgrade database ownership | 13/13 units; 112/112 campaigns; 102/102 channels; 0 duplicate links | PASS |
| Clean database ownership | 13/13 units; 111/111 campaigns; 102/102 channels | PASS |
| Safety read-back | 0 live; 0 production eligible; 0 active workspaces | PASS |
| Callback compatibility | 8 disabled; 0 agent-login enabled | PASS |

## Unresolved risks

- Campaign membership and global record rules are intentionally not part of this
  branch. Non-manager human access is denied until `feat/cc-campaign-security` and
  `feat/cc-identity-membership` land.
- The controlled 2,677-row disposition catalog remains unavailable.
- The 93 explicit native identifier migrations remain unapplied; legacy mappings
  are adopted without rename.
- No middleware, VICIdial, mail, n8n, or production read-back was attempted.

## Rollback

Disable or uninstall `codestra_cc_core` only in a disposable rehearsal after
downstream canonical modules are removed. The canonical tables contain wrappers,
channels, and policy envelopes; legacy business-unit, campaign, and mapping tables
remain the adopted owners and are not rewritten by rollback. Production rollback
requires a database backup and tested module downgrade plan before any deployment.
