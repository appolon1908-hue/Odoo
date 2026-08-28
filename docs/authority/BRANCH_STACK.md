# Contact-center implementation branch stack

All branches are stacked in the dependency order mandated by the authority. Each
branch is reviewable independently and remains unmerged until explicitly approved.
The stack begins at tested commit `6dc403350da71962af28603c0bdf2e73f7f6821e`.

| Order | Branch | Depends on | Scope | Current gate |
| ---: | --- | --- | --- | --- |
| 1 | `docs/odoo-contact-center-authority` | `fix/cc-11-production-readiness` | Authority, controlled inputs, access matrix, ADRs, inventory | PARTIAL — disposition catalog and complete authority ending are missing |
| 2 | `feat/cc-core-domain` | branch 1 | Business unit, campaign, channel, policy, scoped mixin | PASS — bounded staging implementation; draft and unmerged |
| 3 | `feat/cc-campaign-security` | branch 2 | Groups, ACLs, global rules, partial indexes, negative tests | PASS — bounded staging implementation; draft and unmerged |
| 4 | `feat/cc-identity-membership` | branch 3 | Membership, identity, SSO/session scope, lifecycle | PASS — bounded Odoo identity/session implementation; external adapters not tested |
| 5 | `feat/cc-campaign-mail` | branch 4 | Aliases, distribution, quarantine, chatter/attachment isolation | PASS — bounded staging implementation; draft and unmerged; provider read-back not tested |
| 6 | `feat/cc-crm-helpdesk-workspaces` | branch 5 | Campaign CRM, profiles, Helpdesk, activities, SLAs | PASS — bounded Community implementation; draft and unmerged; Enterprise adapter not tested |
| 7 | `feat/cc-vicidial-mapping` | branch 6 | Identifier catalog, desired state, middleware contract, read-back | BLOCKED pending branch 6 review, complete mapping fields, and controlled migration design |
| 8 | `feat/cc-scripts-dispositions` | branch 7 | Immutable scripts and campaign-owned dispositions | BLOCKED — controlled 2,677-row catalog is missing |
| 9 | `feat/cc-callback-transfer` | branch 8 | Callbacks, appointments, transfers, referrals | BLOCKED pending dispositions and scope |
| 10 | `feat/cc-recordings-quality` | branch 9 | Recording metadata/policy and QA | BLOCKED pending calls and scope |
| 11 | `feat/cc-wfm-reporting` | branch 10 | WFM, real-time views, KPI snapshots | BLOCKED pending normalized events |
| 12 | `feat/cc-compliance-audit` | branch 11 | Compliance, append-only audit, break-glass | BLOCKED pending all governed workflows |
| 13 | `feat/cc-bu-moy` | branch 12 | Moy Logistics overlay | BLOCKED pending reusable profiles |
| 14 | `feat/cc-bu-codestra` | branch 13 | Codestra overlay | BLOCKED pending prior stack |
| 15 | `feat/cc-bu-scp` | branch 14 | Senior Citizen Products overlay | BLOCKED pending prior stack |
| 16 | `feat/cc-bu-moneybee` | branch 15 | MoneyBee overlay | BLOCKED pending prior stack |
| 17 | `feat/cc-bu-rlp` | branch 16 | RLP overlay | BLOCKED pending prior stack |
| 18 | `feat/cc-bu-ftp` | branch 17 | For the People overlay | BLOCKED pending prior stack |
| 19 | `feat/cc-bu-tradex` | branch 18 | TradeX overlay | BLOCKED pending prior stack |
| 20 | `feat/cc-bu-calderon` | branch 19 | Calderon Farm overlay | BLOCKED pending prior stack |
| 21 | `test/cc-cross-campaign-certification` | branch 20 | Full negative, integration, migration, reconciliation, rollback evidence | BLOCKED pending implementation and test infrastructure |
| 22 | `docs/cc-production-gates` | branch 21 | Formal evidence packet and recommendation | PRODUCTION_BLOCKED; only STAGING-ONLY is authorized |

## Branch close-out contract

Every branch must end with implementation status, exact tests and results,
unresolved risks, rollback notes, and an update to the required evidence reports.
A missing integration endpoint or external system is reported as `BLOCKED` or
`NOT_TESTED`, never as `PASS`.
