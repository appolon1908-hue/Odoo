# Odoo contact-center security blockers

Assessment date: 2026-08-28

Recommendation: `STAGING-ONLY`

Production status: `PRODUCTION_BLOCKED`

| Priority | Finding | Evidence | Required resolution | Status |
| --- | --- | --- | --- | --- |
| Critical | No authoritative campaign membership model | No `cc.campaign.membership`, scope version, or membership partial indexes exist | Implement the membership domain, indexes, lifecycle, fail-closed session resolution, and migration | FAIL |
| Critical | Current campaign assignments can span multiple campaigns | Security is based on legacy `authorized_user_ids`/`supervisor_ids` relations rather than exact-one membership | Migrate and make membership the only operational authorization source | FAIL |
| Critical | All 93 required native campaign IDs drift from the disposable database | Reconciliation result: 0 exact, 93 drift, 0 missing, 8 unmanaged | Run an approved disabled-state migration with collision checks, backup, read-back, and rollback | FAIL |
| Critical | Controlled 2,677-row disposition catalog is unavailable | Attachment and repository search found no catalog | Supply, hash, review, validate, and test the original catalog | BLOCKED |
| High | Target global record-rule contract does not exist | Existing rules are distributed across legacy group/company/BU scopes | Implement uniform membership rules on all campaign-owned surfaces and negative tests | FAIL |
| High | Helpdesk boundary is absent | Disposable snapshot has no Helpdesk table/module | Install or provide compatible Helpdesk dependency and test campaign isolation | MISSING |
| High | No campaign scripts exist in the snapshot | Script count is zero | Implement immutable versioned scripts with approval and acknowledgement | MISSING |
| High | Canonical fail-closed flags are absent | Only legacy configuration keys exist | Add all thirteen `CC_ENABLE_*` flags at false defaults with global/campaign gates | MISSING |
| High | Cross-campaign suite is incomplete | Existing negative contract contains only ten JSON scenarios | Implement the full model/route/mail/report/export/transfer/session suite | PARTIAL |
| High | Public/service endpoints need ownership review | 65 routes exist; several `auth=none` routes rely on custom service authentication | Classify every route, enforce signed identity/scope/replay protection, and retain tests | PARTIAL |
| High | Privileged ORM/SQL paths need model-level review | Raw inventory found 205 `.sudo(` and 47 cursor references | Prove least privilege, revalidation, parameterization, and non-bypass behavior per path | PARTIAL |
| High | No integration endpoint is configured in the snapshot | Integration endpoint count is zero | Configure authenticated staging middleware and read-back without secrets in source | BLOCKED |
| Medium | Human isolation cannot be exercised on the snapshot | Only the administrator is active | Create synthetic Campaign A/B users, supervisor, QA/WFM roles, data, mail, and calls | BLOCKED |
| Medium | Authority attachment is incomplete | Supplied text ends mid-sentence | Obtain the complete signed/controlled authority and record its hash | PARTIAL |
| Medium | Required evidence packet is incomplete | Only inventory/module/blocker reports are created on the authority branch | Update all 23 required reports across the implementation stack | PARTIAL |

## Non-negotiable safe state

Provisioning, agent sync, email send, inbound email mutation, lead publication,
VICIdial writes, live call control, warm transfer, callback publication, IVR
routing, recording playback, AI assist, and production dialing remain disabled.
The current branch contains documentation only and performs no live action.
