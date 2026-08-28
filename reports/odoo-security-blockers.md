# Odoo contact-center security blockers

## Compliance and audit branch

- All 93 campaign compliance policy seeds are absent; the generated compliance
  matrix therefore remains `PARTIAL` and external policy/provider read-back is
  `NOT_TESTED`.
- Consent grants and revocations, suppression, and pre-contact eligibility are
  append-only, hash-bound, campaign-scoped, and exact-replay protected. DNC and
  revocation block contact before the next click-to-call command.
- Calling hours use the protected customer time zone. Missing policy, missing
  consent, active suppression, predictive outreach, AI voice, and prerecorded
  voice all fail closed.
- Payment safety requires recording pause evidence before a tokenized provider
  handoff. Card, CVV, bank credential, authentication-secret, and payment URL
  values are rejected from governed notes and chatter.
- Audit events are capability-guarded, immutable, payload-hashed, and linked by
  actor-specific chains. Break-glass request, approval, activation, use,
  revocation, and expiry create retained evidence.
- Legal hold supersedes elapsed retention. This branch creates decisions only;
  it exposes no deletion, external compliance transport, or live outreach path.

## Workforce and reporting branch

- All 93 campaign workforce and reporting policy seeds are absent; the generated
  WFM matrix therefore remains `PARTIAL` and external state read-back is
  `NOT_TESTED`.
- The private event-service boundary accepts only normalized adherence and
  aggregate metrics. It has no public route, external writer, customer fields,
  or raw payload storage.
- Legacy company-only shift ACLs are closed and its menu is retired. Canonical
  schedules require immutable campaign and active agent-membership bindings.
- Agents see only their schedules, adherence, and agent-level KPI snapshots.
  Supervisor and WFM views are campaign-scoped; aggregate snapshots contain no
  customer or recording identifiers.
- Raw KPI export is blocked. The staging path creates a reason-hashed,
  checksummed, expiring manifest only and returns no business rows.

Assessment date: 2026-08-28

Recommendation: `STAGING-ONLY`

Production status: `PRODUCTION_BLOCKED`

| Priority | Finding | Evidence | Required resolution | Status |
| --- | --- | --- | --- | --- |
| Critical | Authoritative campaign membership model | `cc.campaign.membership`, scope versioning, partial indexes, identity approval, read-back, and server session resolution are installed and tested | Preserve the invariant in every dependent branch and rehearse controlled migration | RESOLVED_IN_STACK |
| Critical | Exact-one operational campaign authority | Active agents and supervisors resolve through exactly one canonical membership; browser campaign parameters are ignored | Complete migration/read-back against an approved staging snapshot | RESOLVED_IN_STACK |
| Critical | All 93 required native campaign IDs drift from the disposable database | Reconciliation result: 0 exact, 93 drift, 0 missing, 8 unmanaged | Run an approved disabled-state migration with collision checks, backup, read-back, and rollback | FAIL |
| Critical | Controlled 2,677-row disposition catalog is unavailable | Attachment and repository search found no catalog | Supply, hash, review, validate, and test the original catalog | BLOCKED |
| High | Target global record-rule contract is incomplete for later models | Canonical core, membership, identity, mail, CRM, Helpdesk, call, recording, QA, WFM, reporting, compliance, retention, payment, and audit surfaces now have fail-closed rules and focused negative tests | Preserve the invariant in business-unit overlays and complete the integrated branch-21 certification suite | RESOLVED_IN_STACK |
| High | Helpdesk boundary is absent | `cc.helpdesk.queue`, `cc.helpdesk.sla.policy`, and `cc.helpdesk.ticket` are installed and campaign-isolated in the Community runtime; Enterprise `helpdesk.ticket` remains absent | Preserve the canonical Community IDs/evidence and require a separately reviewed adapter if Enterprise Helpdesk is later installed | RESOLVED_IN_STACK |
| High | Campaign-script governance | Canonical script identity/version, separate approval, one-active-version constraint, hash-bound safe rendering, acknowledgements, and campaign rules are implemented | Reconcile/adopt approved legacy scripts in a reviewed staging migration; no external publication is authorized | RESOLVED_IN_STACK |
| High | Canonical fail-closed flags are incomplete | Email, campaign provisioning, agent sync, VICIdial writes, live call control, warm transfer, and callback publication flags install and read back false | Add lead publication, IVR routing, recording playback, AI assist, and production dialing flags on their owning branches | PARTIAL |
| High | Cross-campaign suite is incomplete | Canonical ORM/search/report/export plus membership, session, mail, CRM, Helpdesk, call, recording, QA, WFM, reporting, compliance, payment, retention, and audit isolation paths are covered | Execute the full combined persona/model/communication-path matrix on branch 21 | PARTIAL |
| High | Public/service endpoints need ownership review | 65 routes exist; several `auth=none` routes rely on custom service authentication | Classify every route, enforce signed identity/scope/replay protection, and retain tests | PARTIAL |
| High | Privileged ORM/SQL paths need model-level review | Raw inventory found 205 `.sudo(` and 47 cursor references | Prove least privilege, revalidation, parameterization, and non-bypass behavior per path | PARTIAL |
| High | No integration endpoint is configured in the snapshot | Integration endpoint count is zero | Configure authenticated staging middleware and read-back without secrets in source | BLOCKED |
| Medium | Full human isolation certification is incomplete | Synthetic Campaign A/B agents, supervisors, QA, WFM, Compliance, administrators, auditors, and private service boundaries have focused coverage | Execute the consolidated branch-21 identity and stale-session certification | PARTIAL |
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

## Recording and quality controls

- `codestra_cc_recordings` now binds legacy metadata to one canonical campaign,
  controlled telephony mapping, active agent membership, customer profile, and
  approved recording-policy hash. It stores no audio binary or object URL.
- `CC_ENABLE_RECORDING_PLAYBACK=false` and `CC_ENABLE_AI_ASSIST=false` are
  installed as fail-closed defaults. The legacy playback action is also guarded
  before it can request a signed external URL.
- Recording access and retention evidence is append-only. Legal hold changes
  state and evidence but never expands campaign visibility.
- `codestra_cc_quality` now enforces campaign program versions, author/approver
  separation, QA author/finalizer separation, signed answer hashes, correction by
  superseding version, agent acknowledgement/dispute, calibration, and coaching.
- Approved policy/program seeds and authoritative storage/Middleware read-back
  remain unavailable, so the 93 campaign rows remain `PARTIAL` and production is
  blocked.

## Compliance and audit controls

- `codestra_cc_compliance` enforces versioned jurisdiction/campaign/channel
  policy, separate approval, active-policy uniqueness, immediate suppression,
  customer-local calling hours, and pre-contact evidence.
- `CC_ENABLE_AUTOMATED_OUTREACH=false`,
  `CC_ENABLE_PREDICTIVE_DIALING=false`,
  `CC_ENABLE_PRERECORDED_VOICE=false`, and
  `CC_ENABLE_PAYMENT_DELIVERY=false` install as closed defaults. Existing live
  dialing, AI, callback, transfer, email, and provider flags remain false.
- Payment workflows retain only protected hashes and ordered pause/tokenization
  evidence. No card field, payment URL, direct provider call, or delivery worker
  is present.
- `codestra_cc_audit` provides immutable actor-chain evidence and controlled
  campaign/auditor visibility. Technical users see only their own events unless
  a separately approved break-glass grant is active.
- Campaign policy seeds, external legal/provider validation, authoritative
  suppression read-back, and jurisdictional approval are unavailable. Every one
  of the 93 compliance rows remains `PARTIAL`; production stays blocked.
