# Branch close-out: feat/cc-identity-membership

Status: `PASS` for the bounded identity and membership scope

Overall recommendation: `STAGING-ONLY`

Production: `PRODUCTION_BLOCKED`

## Implemented

- Converted `codestra_cc_identity` from a dependency facade into the canonical,
  fail-closed campaign identity lifecycle.
- Added separate request and approval, deterministic desired-state versions, an
  immutable transactional outbox, and exact Odoo, Keycloak, email, Middleware,
  and VICIdial read-back requirements before activation.
- Added server-derived, SHA-256-only Odoo session and OIDC-subject bindings to
  exactly one active membership, campaign, and campaign scope version.
- Added a global per-request session check for operational users. Missing,
  revoked, expired, or stale scope logs the browser session out.
- Added suspension, expiry, revocation, and security-event session revocation
  through Odoo's reviewed device mechanism plus immutable deprovisioning events.
- Added governed, separately approved campaign reassignment that suspends and
  revokes the source before provisioning and activating the destination.
- Added role-aware agent and supervisor landing routes that ignore browser
  campaign parameters and resolve authority only from the authenticated user.
- Added scoped ACLs, global record rules, database constraints, immutable
  evidence controls, administrative views, and compatibility coverage for the
  underlying campaign-security test suite.

## Tests and read-back

| Evidence | Result | Status |
| --- | --- | --- |
| Source CI | 60 manifests; strict review 0 errors/warnings; all source gates; 3 contract tests | PASS |
| Focused identity upgrade | 9 methods / 13 counters; 0 failed; 0 errors | PASS |
| Security regression | 12 methods / 14 counters; 0 failed; 0 errors | PASS |
| Clean 60-module Odoo install | 366 tests; 0 failed; 0 errors | PASS |
| Identity runtime | 13 identity counters, including authenticated HTTP session pinning | PASS |
| Security runtime | 14 security counters in the clean stack | PASS |
| Clean database ownership | 13 units; 111 campaigns; 102 channels | PASS |
| Clean database identity state | 0 memberships; 0 identity outbox rows; 0 session scopes; 0 reassignments after rollback | PASS |
| Identity schema | 3 identity tables; 3 identity global rules; 52 membership/identity indexes | PASS |
| Production/live state | 0 active memberships; 0 production-enabled identity envelopes | PASS |
| Forged browser campaign | `/contact-center/agent?campaign_id=999999` returned 303 to the server-derived landing target | PASS |
| Calendar/reminder/scheduler browser tour | Included in the 366-test clean run | PASS |

## Unresolved risks

- The outbox is a staging contract only. No worker, network transport, Keycloak,
  mail, Middleware, or VICIdial adapter was enabled or externally exercised.
- External OIDC login and IdP session termination require a configured staging
  Keycloak environment; this branch tests Odoo session pinning and hashed subject
  binding without storing tokens or raw identifiers.
- Every later campaign-owned model still requires its own global rule and
  negative cross-campaign tests.
- The controlled 2,677-row disposition catalog remains unavailable and blocks
  the later scripts/dispositions branch and production certification.
- The supplied authority text ends mid-sentence, so the full controlled source
  still must be provided and hashed before production approval.

## Rollback

The branch is stacked on `feat/cc-campaign-security` and remains unmerged. On a
disposable restored database, revoke every active membership, verify all Odoo
devices and pinned scopes are revoked, retain/export immutable outbox evidence,
remove dependent modules, and uninstall `codestra_cc_identity`. Never uninstall
against production while external accounts remain provisioned; external
read-back and compensating deprovisioning must complete first.
