# Branch close-out: feat/cc-crm-helpdesk-workspaces

Status: `PASS` for the bounded campaign CRM and Community Helpdesk scope

Overall recommendation: `STAGING-ONLY`

Production: `PRODUCTION_BLOCKED`

## Implemented

- Added `codestra_cc_crm` as the canonical owner of campaign customer profiles
  and contact-center CRM lead ownership while composing the existing campaign
  CRM operating-system module.
- Restricted authoritative contacts to the CRM service/global administrator,
  exposed only masked contact hints to operational users, and stored a SHA-256
  partner reference on the campaign projection.
- Derived CRM campaign authority from the authenticated membership or selected
  customer profile, synchronized canonical ownership to reviewed legacy fields,
  and blocked browser/context scope switching, rebinding, copy, and agent export.
- Adapted both legacy global CRM rules to canonical administrator, service,
  break-glass, and membership-derived scopes without broadening legacy-only
  users.
- Added `codestra_cc_helpdesk` with campaign queues, separately approved and
  immutable-version SLA policies, campaign tickets, governed state transitions,
  immutable deadlines, escalation, breach, resolution, FCR, and CSAT evidence.
- Derived ticket ownership from the authenticated membership, profile, queue,
  assignee, supervisor membership, and approved SLA; rejected cross-campaign
  relationships and unsafe sensitive-note keys.
- Applied global campaign isolation plus assignment/supervisor rules to CRM,
  profiles, queues, SLAs, tickets, chatter, followers, activities, and
  attachments.
- Wired the Customer 360 and agent-desktop facades to the canonical CRM and
  Helpdesk modules and documented controlled, non-destructive migration policy.
- Preserved the Community/Enterprise boundary: the tested runtime has no
  Enterprise `helpdesk.ticket`, so no unavailable dependency or untested adapter
  is claimed.

## Tests and read-back

| Evidence | Result | Status |
| --- | --- | --- |
| Source CI | 63 manifests; strict review 0 errors/warnings; all source gates; 3 contract tests | PASS |
| Focused CRM/Helpdesk/legacy CRM run | Odoo aggregate 41 tests; module counters 7/8/34; 0 failed; 0 errors | PASS |
| Clean 63-module Odoo install | 388 tests; 0 failed; 0 errors | PASS |
| Clean database ownership | 13 units; 111 campaigns; 102 channels | PASS |
| Clean transactional state | 0 profiles, queues, SLA policies, or tickets | PASS |
| CRM/Helpdesk schema | 4 tables; 67 indexes; 12 module-owned rules | PASS |
| Canonical module versions | CRM/helpdesk `19.0.1.0.0`; Customer 360/agent desktop `19.0.1.1.0` | PASS |
| Enterprise Helpdesk adapter | Enterprise `helpdesk.ticket` absent from the tested runtime | NOT_TESTED |
| External ticket/provider read-back | No reviewed staging endpoint or transport exists | NOT_TESTED |
| Calendar/reminder/scheduler pop-outs | Headless Chrome returned `test successful` | PASS |

## Unresolved risks

- Enterprise Helpdesk was not available. A future adapter must preserve the
  canonical IDs, campaign rules, immutable SLA deadlines, and migration evidence
  rather than replacing this boundary silently.
- Existing partners, CRM leads, activities, and external tickets were not bulk
  adopted. Migration requires exact campaign mapping, duplicate/ambiguity
  rejection, dry-run counts, rollback mappings, and post-migration isolation
  read-back on a restored staging snapshot.
- No external support inbox, notification provider, knowledge system, middleware
  endpoint, or ticket transport was configured or exercised.
- The controlled 2,677-row disposition catalog and complete authority ending
  remain unavailable and continue to block later certification.
- Later calls, transfers, recordings, QA, WFM, reporting, and business-unit
  overlay models still require their own global rules and cross-campaign tests.

## Rollback

The branch is stacked on `feat/cc-campaign-mail` and remains unmerged. On a
disposable restored database, disable dependent UI facades, export only approved
immutable ticket/SLA evidence, confirm no external adapter is active, remove the
facade dependencies, then uninstall `codestra_cc_helpdesk` followed by
`codestra_cc_crm`. Reinstalling the preceding module versions restores the
facade manifests. No provider rollback is required because this branch performs
no network I/O or external ticket creation.
