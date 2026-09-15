# Odoo Unified Campaign Control Plane and Application Workspace Design

## Document control

| Field | Value |
| --- | --- |
| Repository | `appolon1908-hue/Odoo` |
| Baseline | `main` at `1bad5819889ec83f0c5ab261f2d2fad3be2a4720` |
| Date | 2026-09-15 |
| Status | Approved conversational design; pending written-spec review |
| Target platform | Self-hosted Odoo 19 |
| Release posture | Staging-first, fail-closed, production activation not authorized |
| Specification path | `docs/superpowers/specs/2026-09-15-odoo-unified-campaign-control-plane-design.md` |

## 1. Purpose

This specification defines the missing hierarchy and ownership needed to make
Odoo the unified operational workspace for every Codestra call-center campaign
without turning Odoo into a duplicate of Beyvra, Breero, Booked4Seasons,
Transportation, MoneyBee, LARIM-A, Restaurant, Kyqra, Klyrow, Telnexa,
VICIdial, or n8n.

An authenticated agent must land in exactly one active campaign workspace and
see only that campaign's customers, fields, scripts, workflow, tasks, calls,
email, SMS, knowledge, dispositions, and application-safe actions. A Platform
Admin must be able to create a new campaign from a published template, add
controlled fields and layout rules, review the resulting configuration, and
provision disabled resources through Middleware. No visible action may bypass
the authoritative Odoo service layer or the Middleware integration boundary.

This document adds an application registry, reusable versioned campaign
templates, a controlled typed field/layout builder, and a coherent native Odoo
workspace hierarchy. It preserves the existing campaign isolation,
provisioning, compliance, communications, audit, and monitoring controls.

## 2. Relationship to existing authority

The following repository documents and contracts remain binding:

- `CODESTRA_ODOO19_CAMPAIGN_CRM_MASTER_SPEC_V2.md`;
- `docs/authority/ODOO_19_TOP_TIER_CALL_CENTER_CAMPAIGN_ISOLATION_SPEC.md`;
- `docs/authority/PLATFORM-RBAC-IMPLEMENTATION.md`;
- `AUTOMATIC_CAMPAIGN_PROVISIONING.md`;
- `docs/INTEGRATION-BOUNDARY.md` and `config/integration-boundary.json`;
- `api/contracts/campaign-configuration-v1.json`;
- `custom-addons/call_center_campaign/docs/ODOO-ENDPOINT-CATALOG.yaml`.

This design is additive. If a future implementation discovers a conflict with
a safety or authority requirement in those sources, the stricter fail-closed
requirement applies until a reviewed architecture decision changes it. This
document does not authorize live email, live SMS, external PSTN dialing,
production n8n activation, production campaign activation, trading, lending,
payments, or direct writes to another system.

## 3. Baseline findings

The baseline already provides substantial canonical structure:

- `codestra_cc_core` owns `cc.business.unit`, `cc.campaign`,
  `cc.campaign.scoped.mixin`, `cc.campaign.channel`, and
  `cc.campaign.policy`, while adopting legacy `call.center.*` records through
  delegated inheritance.
- `codestra_cc_security` owns `cc.campaign.membership`, one-active-operational-
  membership enforcement, one active primary supervisor, specialized campaign
  roles, computed user scope, approval evidence, and break-glass controls.
- `codestra_identity_provisioning` owns `codestra.tenant`,
  `codestra.platform.user`, `codestra.tenant.membership`, platform roles,
  agent channels, identity provisioning, and desired/effective access.
- `codestra_cc_crm` owns the masked campaign-scoped `cc.customer.profile` and
  governed projection creation.
- `codestra_campaign_crm_os` owns the current configurable workflow/status,
  operational activity, appointment, automation, KPI, timeline, QA, work queue,
  and performance models, but its installation hook still seeds five fixed
  workflow families.
- `codestra_staging_campaign_design` owns the fixed
  `codestra.campaign.design.profile` and hard-coded `crm.lead` application
  fields used by the staging campaign fixtures.
- `codestra_cc_campaign` and `codestra_campaign_publishing` are existing
  configuration and publishing facades. They are the correct extension points
  for missing configuration ownership; another campaign-builder addon is not
  required.
- `codestra_admin_agent_workspace` already supplies native Odoo Agent
  Workspace and Admin Console screens over the existing platform, tenant, and
  campaign scopes. A second workspace shell is prohibited.
- `call_center_campaign` already owns transactional integration outbox flows,
  automatic design requests, immutable `call.center.campaign.design.revision`
  evidence, Middleware manifest validation, readback, and the canonical private
  `/api/v1/integration/*` endpoint catalog.
- Provider webhooks are not accepted by Odoo. Middleware returns normalized
  results through `/api/v1/integration/results`.
- Code search at the baseline did not find canonical owners named
  `cc.application`, `cc.campaign.template`, `cc.field.definition`,
  `cc.workspace.section`, or `cc.integration.binding`.

## 4. Resolved design contradictions

| Earlier ambiguity | Binding resolution |
| --- | --- |
| A new business-unit model might be needed | `cc.business.unit` already exists and is reused. No duplicate is created. |
| Applications were shown as children of business units | `cc.application` is a registry. A campaign links one business unit and one application; an application may support campaigns in multiple business units. |
| Odoo and an application could both be described as system of record | Odoo owns CRM interactions, tasks, campaign configuration, consent/communication evidence, and its projections. Each business application owns its domain transactions. A projection never transfers domain authority. |
| Odoo might own a new manifest model | Middleware owns the canonical provisioning manifest. Odoo keeps its approved configuration revision and the existing immutable returned design-revision evidence. No `cc.manifest.version` is created. |
| A new workspace application might be built | `codestra_admin_agent_workspace` is extended. Its phone panel continues to delegate to existing call-control models. |
| A simplified lifecycle might replace the implemented lifecycle | `cc.campaign.lifecycle_state` remains the canonical operational lifecycle. Template/configuration publication and Middleware design-revision states are separate, explicitly mapped lifecycles. |
| Workflow `ACTIVE` could imply a live campaign | Workflow publication only makes that workflow version effective in Odoo. It never enables providers or changes `cc.campaign.live_enabled`. |
| Odoo could accept application/provider webhooks | Provider and application webhooks terminate at Kong/Middleware. Odoo accepts only normalized Middleware results through the existing private integration contract. |
| Tenant, company, business unit, and campaign might be inferred by names | All mappings are explicit and fail closed. Browser payloads cannot select or override the authenticated campaign scope. |
| New `/platform/v1` Odoo routes could be added beside current routes | Odoo preserves `/api/v1/integration/*` as its private Middleware contract. New browser APIs are added only where a native model service cannot satisfy the client, and never duplicate an existing operation. |
| Business-unit Admin and Closer were treated as established roles | They are not added. Existing platform, tenant, and campaign roles remain canonical. Closing capability is an explicit skill/policy assigned to an existing campaign role, not an implicit new security tier. |

## 5. Goals

1. Provide one native Odoo operational workspace that changes by campaign
   template while preserving a common shell.
2. Allow a Platform Admin or authorized Campaign Configuration Manager to
   create a new campaign from a published application template without writing
   Python, SQL, XML, or arbitrary expressions.
3. Reuse existing canonical records and facades instead of creating parallel
   campaign, identity, workflow, CRM, channel, provisioning, or dashboard
   domains.
4. Enforce the intersection of platform, tenant/company, business-unit,
   campaign, role, membership state, product entitlement, and environment
   policy on every operation.
5. Publish versioned desired configuration through the existing Odoo outbox;
   receive authoritative readback and evidence through the existing results
   ingress.
6. Make every visible button traceable to one service method and, when it has an
   external effect, one allowlisted Middleware command.
7. Supply real-time operational dashboards without sending secrets, message
   bodies, recordings, or unnecessary PII into monitoring systems.

## 6. Non-goals

- Replacing the business databases or workflows inside connected applications.
- Creating a generic external CRUD/model/method API for Odoo.
- Creating another identity, campaign membership, telephony, communications,
  audit, workflow, reporting, integration outbox, or provisioning engine.
- Reimplementing VICIdial/WebRTC call-control logic inside workspace UI code.
- Using n8n as a system of record, authorization authority, public gateway, or
  event bus.
- Accepting provider webhooks directly in Odoo.
- Making live trading, underwriting, funding, payment, payout, booking,
  dispatch, or order-fulfillment decisions in Odoo.
- Authorizing production activation through installation of these features.

## 7. Organizational and authorization hierarchy

The hierarchy contains related authorization axes rather than one unsafe tree:

1. **Global platform:** `codestra.platform.user.platform_role` provides
   Platform Admin or Platform Operator authority.
2. **Tenant:** `codestra.tenant` and `codestra.tenant.membership` identify the
   external customer/organization boundary.
3. **Legal company:** `res.company` remains Odoo's legal and accounting scope.
4. **Business unit:** `cc.business.unit` represents the internal contact-center
   operational division and belongs to a company through the canonical adopted
   record.
5. **Application:** `cc.application` identifies the business application and
   authoritative backend capability set. It is not a user-access grant.
6. **Campaign:** `cc.campaign` belongs to one business unit and one application.
7. **Membership:** `cc.campaign.membership` grants one specialized role in one
   campaign.
8. **Record:** every operational CRM, task, call, message, attachment, timeline,
   workflow, QA, reporting, or integration record carries immutable campaign
   ownership directly or through a verified parent.

Effective permission is always the intersection of assigned role, explicit
tenant/company mapping, campaign membership, account and membership state,
product entitlement, environment policy, record ownership, and action-specific
approval. No axis can broaden another axis.

The role vocabulary remains the implemented vocabulary:

- global Platform Admin and Platform Operator;
- Tenant Admin;
- campaign Agent, Senior Agent/SME, Supervisor, QA, Workforce, Compliance,
  Configuration Manager, and Auditor;
- non-interactive integration service identities.

Platform Admin is not automatically a business-data reader merely because the
user can administer infrastructure. Cross-campaign operational access continues
to require the explicit global contact-center capability or time-bounded
break-glass evidence.

## 8. Domain and model design

### 8.1 Existing owners to extend

| Owner | Design use |
| --- | --- |
| `cc.business.unit` | Existing operational division and company boundary |
| `cc.campaign` | Canonical campaign identity and operational lifecycle |
| `cc.campaign.membership` | Campaign role and active assignment |
| `cc.customer.profile` | Campaign-scoped masked customer projection |
| `codestra.campaign.workflow` and status models | Runtime workflow assets, migrated from fixed fixtures to template-linked versions |
| `cc.campaign.channel` | Campaign telephony/channel identity |
| `codestra.agent.channel` | Per-person phone/WebRTC/email/SMS desired/effective access |
| Existing script/disposition/policy models | Campaign-owned versioned assets |
| `call.center.campaign.design.revision` | Immutable Middleware manifest response and validation evidence |
| Existing outbox/result/audit models | Commands, results, trace, reconciliation, and immutable evidence |

### 8.2 New canonical owners

#### `cc.application`

Physical owner: `codestra_cc_core`.

Purpose: one registry row for each authoritative application integration, such
as Beyvra, Breero, Booked4Seasons, Transportation, MoneyBee, LARIM-A,
Restaurant, Kyqra, Klyrow, Telnexa, and VICIdial.

Required data:

- immutable uppercase code and UUID;
- display name;
- authoritative service key;
- domain-authority classification (`odoo`, `external`, or `transport`);
- supported projection and command capability identifiers;
- active/deprecated state;
- data classification and masking-policy reference;
- no credentials, tokens, URLs containing credentials, or secret values.

`cc.campaign.application_id` is required for newly created campaigns. Migration
adds it as nullable, backfills every existing campaign from reviewed fixture and
integration evidence, blocks ambiguous mappings, and only then makes it
required for non-archived campaigns. Application code is not inferred from a
campaign name at runtime.

#### `cc.campaign.template`

Physical owner: `codestra_cc_campaign`.

Purpose: stable logical template identity for an application and campaign type.
It contains identity and ownership only; editable content lives in versions.

#### `cc.campaign.template.version`

Physical owner: `codestra_cc_campaign`.

Purpose: immutable reusable package of field definitions, layout, workflow
references, scripts, dispositions, policy defaults, channel requirements,
reporting definitions, and integration capability bindings.

Lifecycle uses the existing campaign-configuration contract vocabulary:
`draft`, `in_review`, `approved`, `published`, `superseded`, and `rolled_back`.
Only a published version may seed a new campaign. Approved and published
content is immutable; a change clones a new draft version.

#### `cc.campaign.configuration.version`

Physical owner: `codestra_cc_campaign`; publication actions are implemented by
the existing `codestra_campaign_publishing` facade.

Purpose: immutable campaign-specific instantiation of one published template
version plus reviewed overrides. It owns the Odoo desired configuration, not
the provider manifest. It records a canonical JSON snapshot and SHA-256 hash,
review/approval evidence, predecessor, publication evidence, and the link to the
existing returned `call.center.campaign.design.revision` where available.

Exactly one published configuration version may be effective for a campaign.
Publication never enables email, SMS, callbacks, n8n, PSTN, provider resources,
or `cc.campaign.live_enabled`.

#### `cc.field.definition`

Physical owner: `codestra_cc_campaign`.

Purpose: safe custom-field metadata owned by one template version. The initial
allowlist is short text, long text, integer, decimal, currency, boolean, date,
datetime, email, phone, URL, single selection, multiple selection, address,
approved attachment reference, read-only application projection, and
controlled computed value.

Every definition records an immutable technical key, label, help text, type,
required/default rules, normalized validation constraints, PII classification,
masking policy, editable and visible role sets, searchable/reportable flags,
conditional-visibility rule, and ordering. The rule language is a closed
declarative grammar over fields in the same published schema. Python, SQL,
XML, `safe_eval`, arbitrary Odoo model relations, and secret access are
prohibited.

#### `cc.profile.field.value`

Physical owner: `codestra_cc_crm`.

Purpose: typed campaign-specific value associated with one
`cc.customer.profile` and one compatible `cc.field.definition`.

Values use typed columns rather than an unvalidated JSON bag. A database/Odoo
constraint enforces exactly the column appropriate to the definition type,
unique `(profile_id, field_definition_id)`, matching campaign application and
published schema, field-level write authority, size limits, and masking. Values
cannot change campaign ownership. Stable high-volume fields remain normal
version-controlled Odoo fields; the builder is not a runtime PostgreSQL schema
generator.

#### `cc.workspace.section` and `cc.workspace.item`

Physical owner: `codestra_cc_campaign`.

Purpose: ordered presentation metadata for a template version. A workspace
item references either an allowlisted stable field/action or one custom field
definition, never both. Sections/items can express role visibility,
read-only/edit state, column span, required-state indicator, and closed
conditional-visibility rules. They cannot execute code.

No persistent `cc.workspace` business model is created. Runtime workspace data
is a service projection over membership, campaign configuration, CRM, calls,
tasks, timeline, and application projections.

#### `cc.integration.binding`

Physical owner: `codestra_cc_campaign`.

Purpose: versioned campaign-to-capability intent. It stores service key,
capability key, required/optional classification, desired enabled state,
effective state returned by Middleware, public external reference, last
readback time, drift state, and an opaque credential-binding alias. It never
stores provider credentials or raw OpenBao secrets.

Per-agent channels remain in `codestra.agent.channel`; campaign telephony
identity remains in `cc.campaign.channel`; Middleware mappings and provider
manifest truth remain outside Odoo.

### 8.3 Prohibited new owners

Do not create `cc.manifest.version`, another campaign/customer/workflow/channel
model, another platform/tenant membership, another integration outbox, another
provider callback controller, or another agent workspace addon.

## 9. Module ownership and dependency direction

The implementation must evolve existing modules in this direction:

```text
codestra_cc_core
  -> codestra_cc_security
  -> codestra_cc_campaign
  -> codestra_cc_crm and existing workflow/policy/communications modules
  -> codestra_campaign_publishing
  -> codestra_admin_agent_workspace
```

`call_center_campaign` remains the compatibility and private Middleware
integration boundary during migration. `codestra_staging_campaign_design`
becomes fixture/migration input only after its fixed design profiles and hard-
coded fields are mapped to published templates. `codestra_campaign_crm_os`
continues to provide existing runtime workflow and operational services while
its five fixed installation-hook workflows are migrated into versioned template
fixtures. Neither module is deleted in the first release.

Before implementation changes dependencies, the plan must run an import/DAG
check and prevent circular dependencies. Facade modules must not silently
become competing sources of truth.

## 10. Configuration and operational lifecycles

Three different lifecycle types are intentionally retained:

### 10.1 Template/configuration lifecycle

```text
draft -> in_review -> approved -> published -> superseded
                                   |              |
                                   +-> rolled_back <-+
```

This lifecycle selects effective Odoo configuration. Publication is atomic and
audited but does not activate providers.

### 10.2 Campaign operational lifecycle

The implemented `cc.campaign.lifecycle_state` remains authoritative:

```text
draft -> design_pending -> design_ready -> approval_pending -> approved
      -> provisioning -> provisioned_disabled -> testing -> staging_ready
      -> activation_pending -> active
```

`blocked`, `failed`, `rollback_pending`, `rolled_back`, and `archived` retain
their implemented transition rules. Staging code continues to reject `active`,
`production_eligible`, and `live_enabled` until a separately reviewed
production activation release exists.

### 10.3 Middleware design-revision lifecycle

The existing `call.center.campaign.design.revision` remains immutable evidence
of the requested revision, returned manifest, validation, approval, and
supersession. Middleware remains authoritative for the canonical provisioning
manifest and integration mappings.

### 10.4 Mapping rule

A published Odoo configuration creates one idempotent design-request event.
The matching Middleware revision must bind the Odoo configuration hash,
campaign identity, environment, and request/event identity. Stale responses are
stored as superseded evidence and cannot become current. A workflow asset marked
effective cannot independently change the campaign operational lifecycle.

## 11. Campaign Studio

The existing campaign facades are expanded into one role-controlled wizard:

1. **Ownership:** tenant/company binding, business unit, application, campaign
   code, purpose, direction, environment, owner, and primary supervisor.
2. **Template:** select a published template version or clone an authorized new
   draft.
3. **Layout:** sections, ordering, stable/custom fields, role visibility, and
   read-only projection placement.
4. **Fields:** typed definitions, required/validation rules, PII classification,
   masking, search/report flags, and conditional visibility.
5. **Workflow:** existing workflow version, states, transitions, required
   fields, tasks, callbacks, scripts, dispositions, appointments, and SLA.
6. **Membership:** primary supervisor, agents, senior agents, QA, workforce,
   compliance, configuration manager, auditor, skills, and same-campaign
   transfer rules.
7. **Channels/integrations:** VICIdial/WebRTC, Klyrow, Telnexa, application
   capabilities, approved n8n bindings, desired disabled state, and required
   synthetic tests.
8. **Review/provision:** normalized validation, configuration diff, independent
   approval, atomic publish, outbox submission, progress/readback, test,
   activation request, emergency disable, reconciliation, and rollback.

Each step persists a draft through model services. The final review renders the
exact normalized snapshot and hash that will be published. Changing a published
configuration creates a successor draft; it never mutates the effective row.

## 12. Native workspace and navigation

`codestra_admin_agent_workspace` is the primary native Odoo shell. It must be
extended, not cloned.

### 12.1 Login routing

After Keycloak/Odoo authentication, the server resolves platform, tenant, and
campaign scope. An Agent or Supervisor with one valid operational membership is
routed directly to that campaign. The campaign is derived server-side and no
campaign selector is rendered. Platform/Tenant users with legitimately
multiple scopes use the existing authorized selector contract and persistent
context banner.

### 12.2 Agent workspace

The existing three-panel structure remains:

- phone/call-control delegates to existing `codestra.vicidial.call` services;
- customer/CRM renders stable and typed template fields, workflow, tasks, and
  read-safe application projections;
- script/disposition renders the published campaign assets and governed
  completion service.

The header shows immutable campaign identity, presence, WebRTC/provider state,
environment, and freshness. The timeline combines calls, email, SMS, notes,
tasks, callbacks, workflow changes, and normalized application events without
exposing provider credentials or raw sensitive payloads.

Every button must map to one named model service. External actions create a
durable command/outbox row and show pending, accepted, effective, failed, or
stale state. No UI action may make a direct provider HTTP request.

### 12.3 Supervisor workspace

The Supervisor sees only the primary supervised campaign: live agent state,
queue, callbacks, transfers, SLA, QA, workforce exceptions, dispositions,
conversion, and channel health. Listen/whisper/barge controls, if present, use
separate audited permissions and existing call-control services; visibility is
not authority.

### 12.4 Administrative workspace

The existing Admin Console is expanded with application registry, templates,
campaign studio, publication, provisioning progress, integration status,
desired/effective state, drift, reconciliation, audit, and emergency disable.
Platform Operator remains read-heavy. Tenant Admin remains limited to the
implemented tenant contract unless a separately approved RBAC change extends
campaign-configuration authority.

## 13. API and service design

### 13.1 Model-first rule

Template, application, field-builder, configuration, and workspace-schema APIs
are not implemented until their owning models, constraints, ACLs, record rules,
and service tests exist. Controllers are thin adapters; authorization and
business rules live in model/domain services.

Native Odoo backend screens use model services directly. A REST/JSON endpoint
is added only for the external SaaS shell or another approved client. Odoo RPC
and REST controllers must not implement parallel business logic.

### 13.2 Browser-facing logical operations

The browser contract must provide these logical capabilities, mapped to
existing routes/actions where present:

- authenticated context and resolved workspace;
- published workspace schema with configuration hash/ETag;
- campaign-scoped work queue and customer projection;
- typed field update with optimistic concurrency;
- timeline, task, callback, transition, disposition, email draft, SMS draft,
  and allowlisted application command;
- supervisor live/queue/KPI/QA operations;
- admin application/template/configuration lifecycle and provisioning status.

The server ignores or rejects browser-supplied tenant, company, business-unit,
campaign, role, or provider identity that conflicts with authenticated scope.

### 13.3 Middleware-facing Odoo contract

Preserve the endpoint catalog in
`custom-addons/call_center_campaign/docs/ODOO-ENDPOINT-CATALOG.yaml`, including:

- `/api/v1/integration/outbox/*` claim/read/renew/ack/fail/release;
- `/api/v1/integration/results` normalized result ingress;
- `/api/v1/integration/results/{id}/reconcile`;
- desired-state reads for campaigns, agents, and leads;
- trace and audit reads;
- capabilities, liveness, readiness, attestation, and metrics.

Odoo continues to reject provider webhooks. The retired
`/codestra/integration/v1/results` route remains gone. New integration behavior
extends the catalog and versioned resource-specific contracts instead of adding
a generic model writer.

## 14. Application template packs

Initial published template families are created from reviewed fixtures, not
silently activated:

| Application | Odoo workspace sections | Authority boundary |
| --- | --- | --- |
| Beyvra | Identity, KYC/compliance status, account summary, restrictions, risk, support | No unrestricted trading, money movement, or compliance override in Odoo |
| Transportation | Customer, origin/destination, cargo, pickup/delivery, carrier, driver, quote, shipment, dispatch | Logistics transactions remain in Transportation |
| MoneyBee | Business, owners, request, documents, prequalification, underwriting status, offer, funding status, complaints | Human underwriting/funding authority remains in MoneyBee |
| Breero | Service, description, location, schedule, contact preference, provider, assignment, status | Booking/provider/payment/payout truth remains in Breero |
| Booked4Seasons | Customer intake and Breero request projection | No second booking/provider backend |
| LARIM-A | Service, provider, quote, booking, availability, visit, review, case | Marketplace fulfillment/payment truth remains in LARIM-A |
| Restaurant | Guest, order/reservation, location, schedule, support reason, status | Payment, inventory, and fulfillment remain in Restaurant |
| Codestra Development | Service type, scope, budget, timeline, technical requirements, proposal | Project delivery truth remains in its authoritative application |
| Senior Products | Customer, authorized representative, interest, appointment, consent | Sensitive information is minimized and non-medical claims enforced |
| Student Repayment | Borrower, servicer, balance/status projection, repayment workflow, consent | Servicing and financial decisions remain external |
| Kyqra | Provenance, qualification, consent, review state | Lead ingestion/review only; Kyqra is not a CRM |

Existing fixed workflow and staging design fixtures are migrated into draft
template versions, compared to their current behavior, reviewed, and published
individually. Migration never makes a provider active.

## 15. Integration, communications, and webhooks

Outbound cross-system flow is Odoo transaction -> existing Odoo outbox -> Kong
-> Middleware -> governed adapter -> application/provider -> readback. Inbound
flow is provider/application webhook or outbox -> Kong -> Middleware inbox ->
normalized result -> Odoo result ingress -> canonical projection -> Odoo bus
notification.

All commands/events carry schema version, event/command identity, tenant,
company, business unit, application, campaign, entity, correlation, causation,
idempotency key, payload hash, timestamp, and source version where applicable.

Klyrow, Telnexa, and VICIdial provider callbacks terminate at Middleware. Odoo
receives delivery/call/result projections only. n8n workflows are versioned,
allowlisted, service-authenticated, idempotent, and installed inactive.

Current default-off controls remain false, using existing canonical flag names:
live email, live SMS, callbacks/external side effects, n8n activation, PSTN,
live call control, lead publication, agent synchronization, production
eligibility, and campaign live enablement.

## 16. Dashboard and information delivery

Odoo operational dashboards read canonical Odoo records and calculated
campaign-scoped projections. The existing `codestra.tenant.kpi`, campaign KPI,
performance, call, task, timeline, and desired/effective-state owners are reused.
Do not create a dashboard-owned copy of business records.

- Agent dashboards show assigned work, tasks/callbacks, communications,
  workflow state, personal metrics, and application projections.
- Supervisor dashboards show the supervised campaign's live agents, queue,
  ASA, abandonment, occupancy, adherence, transfer success, callback SLA, FCR,
  QA, conversion, dispositions, channel state, and stale-data indicators.
- Admin dashboards show service/integration state, provisioning progress,
  outbox/inbox health, result failures, manifest/configuration hashes, drift,
  reconciliation, kill switches, and last readback.
- Grafana receives metrics/logs/traces through the monitoring plane and never
  becomes a customer/CRM database.
- Superset reads minimized historical facts through an approved analytics store
  or reporting replica and is never an operational command surface.

Every card exposes `last_updated_at` and freshness state. Missing data is
`STALE` or `DISCONNECTED`, never zero. Customer identifiers, phone/email values,
message bodies, tokens, signatures, credentials, and recordings are prohibited
from metric labels and unrestricted logs.

## 17. Security invariants

1. An Agent or Senior Agent has exactly one active operational membership.
2. Each active human-staffed campaign has exactly one active primary
   Supervisor; a primary Supervisor operationally supervises one campaign.
3. Campaign ownership is immutable outside reviewed migration capability.
4. Cross-campaign reads, searches, RPC, controller access, attachments,
   chatter, activities, exports, reports, transfers, and dashboard aggregation
   fail closed.
5. Agents cannot browse global contacts, bulk export, duplicate, bulk delete,
   reassign campaign, change supervisor, or alter channel bindings.
6. Customer projection creation is restricted to the governed CRM service or
   explicit global contact-center authority.
7. Sensitive values are masked by classification and purpose; operational
   administration never exposes OpenBao values.
8. `sudo()` is allowed only in narrow services after explicit tenant/company/
   campaign resolution and must append audit evidence.
9. Service identities cannot use interactive login and receive one audience and
   least-privilege scopes.
10. Configuration publication, access approval, production activation, and
    break-glass follow existing separation-of-duty evidence.

## 18. Error handling and reliability

- Validate normalized configuration before publication and before outbox
  creation.
- Use database uniqueness/locking for version numbers, event identities,
  idempotency keys, and resource allocation.
- Identical replays return stored results; changed-content reuse returns a
  conflict.
- Retry only explicitly retryable timeouts, rate limits, and server failures
  with bounded exponential backoff and jitter.
- Authentication, authorization, schema, domain, and state-transition failures
  are not automatically retried.
- Persist failure, retry, dead-letter, and reconciliation evidence.
- A partial provisioning run remains disabled.
- A readback mismatch blocks testing/activation and appears on the Admin
  Console.
- Stale configuration or manifest responses are retained as superseded evidence
  and cannot overwrite the current revision.
- UI actions display pending, accepted, effective, failed, stale, unauthorized,
  and retryable states without treating an HTTP acknowledgement as business
  completion.

## 19. Migration and compatibility

1. Inventory all installed legacy/canonical campaign, workflow, staging design,
   CRM, workspace, and publishing records at an exact database backup point.
2. Add new nullable references and new owner tables without changing effective
   behavior.
3. Seed `cc.application` deterministically from reviewed business/application
   mappings.
4. Convert fixed `codestra.campaign.design.profile`, five CRM OS workflow
   families, and application-specific stable fields into draft template data.
5. Compare generated schemas/workflows to current records and require review.
6. Publish templates individually while all external flags remain false.
7. Link existing campaigns to applications, template versions, and configuration
   versions; block ambiguous rows instead of guessing.
8. Switch native workspace reads to the published configuration service behind
   a default-off feature flag and run shadow comparisons.
9. Remove runtime dependence on fixed staging profiles only after exact parity,
   rollback, and upgrade tests pass.
10. Preserve external IDs, legacy delegated records, audit history, call history,
    message history, attachments, and Middleware design revisions.

No destructive data deletion is part of the initial implementation. Database-
changing rollback requires the matching PostgreSQL and filestore recovery point,
not only a Git revert.

## 20. Test design

Required automated evidence includes:

- module dependency/DAG and manifest validation;
- fresh install and upgrade on Odoo 19 with PostgreSQL;
- migration of fixed campaign designs and workflows;
- positive and negative ACL/record-rule matrices for every existing role;
- one-active-operational-membership and one-primary-supervisor concurrency;
- campaign immutability, cross-company, cross-tenant, and cross-campaign tests;
- attachment, chatter, activity, export, report, RPC, controller, and URL-ID
  isolation tests;
- template/configuration version immutability and atomic publication;
- typed field validation, masking, role visibility, conditional rules, size
  limits, and incompatible-schema rejection;
- workspace schema ETag/hash and server-derived scope;
- every visible native UI menu/action/button through Odoo browser tours;
- Owl lifecycle/registry failure detection where Owl components are used;
- outbox idempotency, leasing, acknowledgement, failure, replay, stale result,
  and reconciliation tests;
- Middleware contract and normalized result tests;
- VICIdial/Klyrow/Telnexa/n8n disabled-first and kill-switch tests;
- dashboard campaign isolation, freshness, stale/disconnected state, and PII
  redaction tests;
- load tests for workspace reads, queue refresh, field writes, event ingestion,
  dashboard aggregation, and outbox workers;
- backup/restore and module rollback rehearsal on staging.

SQLite-only tests cannot certify this design. Tests must record exact Git SHA,
database engine/version, installed module versions, configuration hashes, and
whether external side effects were simulated or real. No runtime claim may be
made without runtime evidence.

## 21. Release and activation

Implementation follows feature branch -> pull request -> exact-head CI -> merge-
result CI -> isolated PostgreSQL/Odoo runtime -> staging deployment of the exact
merged SHA -> affected-module upgrade -> role/UI/integration smoke tests ->
backup/restore evidence -> production deployment approval.

The feature is introduced default-off. The first rollout uses one synthetic
staging campaign, disabled VICIdial resources, inactive n8n workflows, suppressed
email/SMS delivery, and no external PSTN. Activation requires exact desired-
versus-actual readback, successful synthetic tests, healthy monitoring, tested
emergency disable, tested rollback, and separate explicit authorization.

## 22. Acceptance criteria

The design is implemented only when all of the following are proven:

1. One Odoo hierarchy supports every approved application without a generic
   one-size-fits-all field set.
2. Existing canonical owners are reused and the prohibited duplicate models,
   modules, controllers, adapters, workflows, and dashboards do not exist.
3. An Agent lands in exactly one campaign workspace and cannot discover or
   operate on another campaign through UI, RPC, REST, reports, attachments, or
   guessed identifiers.
4. A Platform Admin can create a draft from a published application template,
   use the controlled builder, review a normalized diff, publish an immutable
   configuration, and request disabled provisioning.
5. Each application pack renders its own fields, workflow, scripts,
   dispositions, policies, and allowed commands from the published version.
6. Every visible action is backed by one tested domain service; external actions
   use the existing Middleware-only outbox/result boundary.
7. Odoo never receives provider webhooks or stores provider credentials.
8. Middleware manifest evidence, actual state, drift, and reconciliation are
   visible without making Odoo the manifest authority.
9. Operational dashboard data is campaign-isolated and monitoring/analytics
   data is minimized, fresh, and visibly stale on failure.
10. PostgreSQL, security, browser-tour, contract, concurrency, failure,
    reconciliation, migration, backup/restore, and rollback evidence passes at
    the exact candidate SHA.
11. All live-delivery, PSTN, production, and external-write controls remain
    disabled until separately authorized.

## 23. Repository implementation boundaries

This Odoo specification defines Odoo-owned behavior. The later multi-repository
implementation plan may assign dependencies to Middleware, Keycloak, Kong,
Caddy, OpenBao, n8n, VICIdial, Klyrow, Telnexa, application backends, SDK,
monitoring, and analytics repositories. Those repositories must consume the
versioned contract and implement only their declared authority. No repository
may create a self-integration or local clone of another repository's source of
truth.

