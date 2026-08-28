# Odoo contact-center security blockers

Assessment date: 2026-08-28

Recommendation: `STAGING-ONLY`

Production status: `PRODUCTION_BLOCKED`

| Priority | Finding | Evidence | Required resolution | Status |
| --- | --- | --- | --- | --- |
| Critical | Authoritative campaign membership model | `cc.campaign.membership`, scope versioning, partial indexes, identity approval, read-back, and server session resolution are installed and tested | Preserve the invariant in every dependent branch and rehearse controlled migration | RESOLVED_IN_STACK |
| Critical | Exact-one operational campaign authority | Active agents and supervisors resolve through exactly one canonical membership; browser campaign parameters are ignored | Complete migration/read-back against an approved staging snapshot | RESOLVED_IN_STACK |
| Critical | All 93 required native campaign IDs drift from the disposable database | Reconciliation result: 0 exact, 93 drift, 0 missing, 8 unmanaged | Run an approved disabled-state migration with collision checks, backup, read-back, and rollback | FAIL |
| Critical | Controlled 2,677-row disposition catalog is unavailable | Attachment and repository search found no catalog | Supply, hash, review, validate, and test the original catalog | BLOCKED |
| High | Target global record-rule contract is incomplete for later models | Canonical core, membership, outbox, session, and reassignment surfaces have fail-closed rules and negative tests | Add a global membership rule and negative tests to every later campaign-owned model | PARTIAL |
| High | Helpdesk boundary is absent | Disposable snapshot has no Helpdesk table/module | Install or provide compatible Helpdesk dependency and test campaign isolation | MISSING |
| High | No campaign scripts exist in the snapshot | Script count is zero | Implement immutable versioned scripts with approval and acknowledgement | MISSING |
| High | Canonical fail-closed flags are incomplete | `CC_ENABLE_EMAIL_SEND` and `CC_ENABLE_EMAIL_INBOUND_MUTATION` now install and read back as false; the other eleven canonical flags do not yet exist | Add the remaining eleven flags on their owning branches with global/campaign gates | PARTIAL |
| High | Cross-campaign suite is incomplete | Canonical ORM/search/report/export plus membership and session paths are covered; later mail/helpdesk/transfer/reporting surfaces do not yet exist | Extend the same negative suite on every dependent branch | PARTIAL |
| High | Public/service endpoints need ownership review | 65 routes exist; several `auth=none` routes rely on custom service authentication | Classify every route, enforce signed identity/scope/replay protection, and retain tests | PARTIAL |
| High | Privileged ORM/SQL paths need model-level review | Raw inventory found 205 `.sudo(` and 47 cursor references | Prove least privilege, revalidation, parameterization, and non-bypass behavior per path | PARTIAL |
| High | No integration endpoint is configured in the snapshot | Integration endpoint count is zero | Configure authenticated staging middleware and read-back without secrets in source | BLOCKED |
| Medium | Full human isolation certification is incomplete | Synthetic Campaign A/B agents, supervisors, administrators, integration service, and forged-route tests now pass | Add QA/WFM/mail/helpdesk/call personas as their owning branches land | PARTIAL |
| Medium | Authority attachment is incomplete | Supplied text ends mid-sentence | Obtain the complete signed/controlled authority and record its hash | PARTIAL |
| Medium | Required evidence packet is incomplete | Only inventory/module/blocker reports are created on the authority branch | Update all 23 required reports across the implementation stack | PARTIAL |

## Non-negotiable safe state

Provisioning transport, agent sync, email send, inbound email mutation, lead
publication, VICIdial writes, live call control, warm transfer, callback
publication, IVR routing, recording playback, AI assist, and production dialing
remain disabled. The identity branch creates only transactional staging outbox
evidence; it has no worker, network transport, production endpoint, or live flag.
The campaign-mail branch additionally materializes both canonical email flags at
false, hard-locks all route/sender/distribution live switches off, and contains
no public mail controller or transport worker.
