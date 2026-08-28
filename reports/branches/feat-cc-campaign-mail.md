# Branch close-out: feat/cc-campaign-mail

Status: `PASS` for the bounded campaign-mail scope

Overall recommendation: `STAGING-ONLY`

Production: `PRODUCTION_BLOCKED`

## Implemented

- Added `codestra_cc_mail` as the canonical owner of campaign routes, fixed
  sender identities, distribution groups and membership read-back, governed
  inbound events, quarantine evidence, and campaign mail threads.
- Derived campaign ownership from the server-resolved alias and linked business
  resource. Browser values, raw message content, sender choice, and thread tokens
  are never campaign authority.
- Enforced separate request and approval, immutable approved route identity,
  unique address and route class, and staging-only route states.
- Fixed From, Reply-To, signature, footer, and tracking-domain projection to the
  approved campaign sender identity; external delivery remains unavailable.
- Quarantined unknown aliases, stale events, replays, integrity failures,
  cross-campaign thread tokens, executable/oversized attachments, and missing
  scan evidence while storing only bounded hashes and metadata.
- Tagged chatter, followers, activities, and attachments with canonical campaign
  ownership and applied global read/write/delete isolation. Generic creation
  rechecks access to the linked business record so mail cannot bypass its rules.
- Preserved legacy campaign chatter by mapping `call.center.campaign` ownership
  to its immutable canonical `cc.campaign` tag.
- Materialized `CC_ENABLE_EMAIL_SEND=false` and
  `CC_ENABLE_EMAIL_INBOUND_MUTATION=false`; route, sender, and distribution live
  switches are independently immutable at false.
- Added scoped ACLs, eleven global rules, administrative views, migration notes,
  and a 93-row campaign email readiness matrix without inventing aliases.

## Tests and read-back

| Evidence | Result | Status |
| --- | --- | --- |
| Source CI | 61 manifests; strict review 0 errors/warnings; all source gates; 3 contract tests | PASS |
| Focused mail upgrade | 11 methods / 13 counters; 0 failed; 0 errors | PASS |
| Legacy integration regression | 144 tests; 0 failed; 0 errors | PASS |
| Clean 61-module Odoo install | 377 tests; 0 failed; 0 errors | PASS |
| Clean database ownership | 13 units; 111 campaigns; 102 channels | PASS |
| Clean database mail state | 0 routes, senders, groups, memberships, threads, inbound events, or quarantine rows after rollback | PASS |
| Mail schema | 7 mail tables; 72 mail-table indexes; 11 module-owned global rules | PASS |
| Global feature flags | `CC_ENABLE_EMAIL_SEND=false`; `CC_ENABLE_EMAIL_INBOUND_MUTATION=false` | PASS |
| Model live switches | 0 enabled route, sender, or distribution switches | PASS |
| Authority email catalog | 93/93 `email_alias_key=MISSING`; 0 routes provisioned | BLOCKED |
| External/provider read-back | No mail server, provider, transport worker, or staging endpoint configured | NOT_TESTED |
| Calendar/reminder/scheduler browser tour | Included in the 377-test clean run | PASS |

## Unresolved risks

- All 93 controlled campaign rows lack an approved email alias. No route or
  provider alias was seeded, guessed, or provisioned.
- Inbound parsing and outbound preparation are staging-domain contracts only.
  No external email was received or sent and no provider read-back was possible.
- Attachment acceptance validates supplied scan evidence; a production scanner,
  object-store boundary, retention job, and provider adapter remain required.
- Existing legacy mail records are not bulk retagged by this branch. Migration
  must be rehearsed on a restored staging snapshot with ownership reconciliation.
- The controlled 2,677-row disposition catalog and the complete authority ending
  remain unavailable and continue to block later certification.

## Rollback

The branch is stacked on `feat/cc-identity-membership` and remains unmerged. On a
disposable restored database, confirm both global email flags and all model live
switches are false, export immutable event/quarantine evidence, remove dependent
facades, then uninstall `codestra_cc_mail`. No provider rollback is required for
this branch because it creates no provider objects and performs no network I/O.
