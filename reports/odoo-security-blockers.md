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
| High | Target global record-rule contract is incomplete for later models | Canonical core, membership, identity, mail, CRM, customer-profile, queue, SLA, Helpdesk, callback, appointment, reminder, transfer, referral, event, and outbox surfaces have fail-closed rules and negative tests | Add the same global rule and negative tests to recording, QA, WFM, compliance, and reporting models | PARTIAL |
| High | Helpdesk boundary is absent | `cc.helpdesk.queue`, `cc.helpdesk.sla.policy`, and `cc.helpdesk.ticket` are installed and campaign-isolated in the Community runtime; Enterprise `helpdesk.ticket` remains absent | Preserve the canonical Community IDs/evidence and require a separately reviewed adapter if Enterprise Helpdesk is later installed | RESOLVED_IN_STACK |
| High | Campaign-script governance | Canonical script identity/version, separate approval, one-active-version constraint, hash-bound safe rendering, acknowledgements, and campaign rules are implemented | Reconcile/adopt approved legacy scripts in a reviewed staging migration; no external publication is authorized | RESOLVED_IN_STACK |
| High | Canonical fail-closed flags are incomplete | Email, campaign provisioning, agent sync, VICIdial writes, live call control, warm transfer, and callback publication flags install and read back false | Add lead publication, IVR routing, recording playback, AI assist, and production dialing flags on their owning branches | PARTIAL |
| High | Cross-campaign suite is incomplete | Canonical ORM/search/report/export plus membership, session, mail, CRM, customer-profile, Helpdesk, callback, appointment, reminder, live-transfer rejection, and asynchronous referral isolation paths are covered | Extend the same negative suite to recording, QA, WFM, compliance, and reporting surfaces | PARTIAL |
| High | Public/service endpoints need ownership review | 65 routes exist; several `auth=none` routes rely on custom service authentication | Classify every route, enforce signed identity/scope/replay protection, and retain tests | PARTIAL |
| High | Privileged ORM/SQL paths need model-level review | Raw inventory found 205 `.sudo(` and 47 cursor references | Prove least privilege, revalidation, parameterization, and non-bypass behavior per path | PARTIAL |
| High | No integration endpoint is configured in the snapshot | Integration endpoint count is zero | Configure authenticated staging middleware and read-back without secrets in source | BLOCKED |
| Medium | Full human isolation certification is incomplete | Synthetic Campaign A/B agents, supervisors, administrators, integration service, mail, CRM, and Helpdesk tests now pass | Add QA/WFM/call personas as their owning branches land | PARTIAL |
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
no public mail controller or transport worker. The scripts/dispositions branch
adds no transport or controller and keeps disposition review blocked while the
controlled catalog is missing. The call-operations branch materializes callback
publication and warm-transfer flags at false, retains only held desired-state
events, rejects cross-campaign live transfers, and creates cross-campaign work
only through a destination-isolated minimum-data referral service.
