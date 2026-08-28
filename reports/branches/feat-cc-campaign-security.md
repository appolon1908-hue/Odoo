# Branch close-out: feat/cc-campaign-security

Status: `PASS` for the bounded campaign-security scope

Overall recommendation: `STAGING-ONLY`

Production: `PRODUCTION_BLOCKED`

## Implemented

- Added `codestra_cc_security` as a concrete fail-closed security module.
- Added the ten stable authority roles plus one reusable campaign-scoped base
  group; the new roles do not inherit the legacy broad CRM/sales roles.
- Added `cc.campaign.membership` with immutable campaign ownership, approval
  separation, matched read-back gating, and revoke/suspend workflows.
- Added migration-managed PostgreSQL partial unique indexes for one active
  agent campaign, one active supervisor campaign, one primary supervisor per
  campaign, and one active operational role per user.
- Added a canonical primary-supervisor link on the campaign and scope-version
  increments for activation, suspension, and revocation.
- Added global fail-closed rules for canonical business units, campaigns,
  channels, policies, memberships, and break-glass evidence.
- Added a governed, separately approved, four-hour maximum break-glass grant.
- Added negative tests for search, direct ID, name search, grouped reporting,
  export, copy, create, write, membership visibility, supervisor isolation,
  partial indexes, and technical-admin denial.

## Tests and read-back

| Evidence | Result | Status |
| --- | --- | --- |
| Source CI | 60 manifests; strict review 0 errors/warnings; all source gates; 3 contract tests | PASS |
| Focused Odoo upgrade | 12 methods / 14 counters; 0 failed; 0 errors | PASS |
| Clean 60-module Odoo install | 358 tests; 0 failed; 0 errors | PASS |
| Security schema | 5 partial unique security indexes; 6 global contact-center rules | PASS |
| Clean database ownership | 13 units; 111 campaigns; 102 channels | PASS |
| Clean database access state | 0 memberships; 0 break-glass grants after transactional tests | PASS |
| Production/live state | 0 live-enabled; 0 production-eligible; 0 active workspaces | PASS |
| Callback compatibility | 8 disabled; 0 agent-login enabled; 0 active | PASS |
| Calendar/reminder/scheduler browser tour | Included in the 358-test clean run | PASS |

## Unresolved risks

- OIDC login, server-side session pinning, external desired state, and
  deprovisioning belong to `feat/cc-identity-membership` and are not yet built.
- The global rules cover the canonical domain introduced so far. Every later
  campaign-owned model still requires its own global rule and negative suite.
- Expired break-glass grants require the later identity/audit lifecycle to
  revoke sessions and close grants automatically; manual revocation is tested.
- The controlled 2,677-row disposition catalog remains unavailable.
- No middleware, VICIdial, mail, n8n, or production read-back was attempted.

## Rollback

The module is stacked on `feat/cc-core-domain` and remains unmerged. Rehearse
rollback only on a disposable backup: revoke active memberships and break-glass
grants, remove dependent identity modules, uninstall `codestra_cc_security`, and
verify that no canonical scope is live. The module never rewrites or deletes the
legacy campaign owners.
