# Odoo contact-center read-only inventory

Inventory date: 2026-08-28

Repository commit: `6dc403350da71962af28603c0bdf2e73f7f6821e`

Database: disposable local PostgreSQL snapshot
`odoo_cc_pr21_upgrade_20260828` on `127.0.0.1:55432`

Recommendation: `STAGING-ONLY`

No repository, database, middleware, VICIdial, mail, n8n, or production setting was
mutated during this inventory.

## Repository inventory

| Check | Observed | Status |
| --- | ---: | --- |
| Custom Odoo modules | 59 | PASS |
| Target modules in the new 38-module architecture | 6 names present | PARTIAL |
| Target modules with complete target responsibility | 0 | MISSING |
| Existing `codestra_cc_*` modules | 17 | PASS |
| Dependency-only `codestra_cc_*` facades | 16 | PARTIAL |
| Concrete `codestra_cc_*` modules | 1 (`codestra_cc_workforce`) | PARTIAL |
| Declared model classes across custom addons | 231 | PARTIAL |
| ACL CSV files | 35 | PARTIAL |
| Custom ACL rows | 418 | PARTIAL |
| Record-rule XML files | 31 | PARTIAL |
| Custom record rules | 150 | PARTIAL |
| HTTP routes | 65 | PARTIAL |
| Odoo test files | 85 | PARTIAL |
| Python test methods | 351 | PARTIAL |
| Last full local Odoo 19/PostgreSQL result at this base | 339 passed; 0 failed/errors | PASS |
| Required authority report directory before this branch | Absent | MISSING |

Raw source search found 205 `.sudo(` occurrences and 47 cursor references. These
are audit leads, not automatic findings: each path must be classified by actor,
data scope, authorization revalidation, query parameterization, and test evidence.
The existing strict source checks pass, but they do not prove the new membership
boundary.

## Disposable database inventory

| Object | Observed | Status |
| --- | ---: | --- |
| Installed modules | 137 | PASS |
| Registered models | 729 | PASS |
| Security groups | 164 | PARTIAL |
| ACL records | 1,086 | PARTIAL |
| Record rules | 336 | PARTIAL |
| Active users | 1 (administrator only) | BLOCKED |
| Companies | 2 | PASS |
| Business-unit records | 13 (the required eight plus legacy/test records) | PARTIAL |
| CRM teams | 12 | PARTIAL |
| Helpdesk | Table/module absent | MISSING |
| Mail aliases | 50 | PARTIAL |
| CRM stages | 23 | PARTIAL |
| Mail activities | 0 | NOT_TESTED |
| Campaign scripts | 0 | MISSING |
| Dispositions | 74 | PARTIAL |
| Campaign records | 112 | PARTIAL |
| Campaign mapping records | 102 | PARTIAL |
| Calls | 0 | NOT_TESTED |
| Callbacks | 1 synthetic migration fixture | PARTIAL |
| Attachments | 810 | PARTIAL |
| Recordings | 0 | NOT_TESTED |
| Integration endpoints | 0 | MISSING |

All canonical campaign records in the disposable snapshot are inactive/draft,
not production eligible, and have inactive desired state. This is safe for
inventory but does not demonstrate staging functionality.

## Campaign mapping reconciliation

The supplied identifier authority contains 93 unique canonical/native pairs. The
existing database has 101 staging mapping rows in scope for comparison.

| Result | Count | Status |
| --- | ---: | --- |
| Exact canonical/native matches | 0 | FAIL |
| Canonical records with a different native ID | 93 | FAIL |
| Missing required canonical records | 0 | PASS |
| Existing unmanaged mapping records | 8 | PARTIAL |
| Native identifiers over eight characters in supplied matrix | 0 | PASS |
| Duplicate supplied canonical or native identifiers | 0 | PASS |

The drift is expected to require controlled adoption/migration. It must not be
resolved through silent rename or direct database edits.

## Security-boundary inventory

Current authorization uses legacy campaign relations such as
`authorized_user_ids` and `supervisor_ids`. The following target controls do not
exist at this base:

- `cc.campaign.membership`;
- one-active-campaign partial unique index for agents/senior agents;
- one-active-campaign partial unique index for supervisors;
- one-primary-supervisor partial unique index per active campaign;
- session scope version and fail-closed membership resolution;
- a uniform campaign-owned mixin and global record-rule contract;
- the complete 23-scenario cross-campaign negative suite.

The current relations can permit multiple campaign assignments. Consequently,
legacy tests passing does not satisfy the new hard-isolation authority.

## Feature-flag inventory

Existing legacy provisioning, calls, transfers, callbacks, n8n, outbound event,
and VICIdial-write flags in the disposable database are false. The thirteen new
canonical `CC_ENABLE_*` flags are not yet implemented:

`CC_ENABLE_CAMPAIGN_PROVISIONING`, `CC_ENABLE_AGENT_SYNC`,
`CC_ENABLE_EMAIL_SEND`, `CC_ENABLE_EMAIL_INBOUND_MUTATION`,
`CC_ENABLE_LEAD_PUBLICATION`, `CC_ENABLE_VICIDIAL_WRITES`,
`CC_ENABLE_LIVE_CALL_CONTROL`, `CC_ENABLE_WARM_TRANSFER`,
`CC_ENABLE_CALLBACK_PUBLICATION`, `CC_ENABLE_IVR_ROUTING`,
`CC_ENABLE_RECORDING_PLAYBACK`, `CC_ENABLE_AI_ASSIST`, and
`CC_ENABLE_PRODUCTION_DIALING`.

Status: `PRODUCTION_BLOCKED` until canonical flags exist, default false, fail
closed at global and campaign scope, and have negative tests.

## Core-domain branch update

Branch `feat/cc-core-domain` converts `codestra_cc_core` from a dependency facade
to a concrete canonical adoption layer. Disposable upgrade read-back reconciles 13
legacy/canonical business units, 112 legacy/canonical campaigns, and 102
legacy/canonical mapping/channel records with zero duplicate ownership links.
Clean-install read-back reconciles 13 units, 111 campaigns, and 102 channels after
the full test data lifecycle. Two noncanonical synthetic identifiers are retained
as blocked legacy exceptions rather than renamed. Status: `PASS` for the bounded
core-domain responsibility and `PRODUCTION_BLOCKED` for the overall system.

## Campaign-security branch update

Branch `feat/cc-campaign-security` adds the previously missing canonical
membership and authorization layer. It installs ten stable authority roles,
four membership partial unique indexes, one break-glass partial unique index,
and six global fail-closed record rules. Agents resolve to one operational
campaign, supervisors resolve to one campaign and one primary supervisor slot,
and technical administrators resolve to no canonical campaign unless a separate
time-bounded break-glass grant is active.

The clean 60-module database completed 358 tests with zero failures/errors and
retained zero live-enabled, production-eligible, or active campaign workspaces.
This closes the base inventory gaps for membership, database uniqueness, and the
canonical core record-rule contract. Server-side OIDC session pinning,
deprovisioning, and the remaining campaign-owned model rules are still open.
