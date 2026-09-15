# Odoo Unified Campaign Control Plane and Application Workspace Design

## Document control

| Field | Value |
| --- | --- |
| Repository | `appolon1908-hue/Odoo` |
| Baseline | `main` at `1bad5819889ec83f0c5ab261f2d2fad3be2a4720` |
| Date | 2026-09-15 |
| Status | Revised from Master Mission v1.0; pending written-spec review |
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

### 2.1 Master Mission v1.0 adoption

The user-supplied **Master Mission — Codestra Application Integration Plane,
Version 1.0, dated 2026-09-15** is adopted as the cross-repository execution
charter subject to the binding contradiction resolutions in section 4. Its
repository-aware discovery, ownership, anti-duplication, contract, security,
testing, staging, completion-report, and production-authorization rules apply
to this design.

The mission's diagrams are normalized as follows so they describe deployable
trust boundaries rather than implying that every component is an inline proxy:

```text
Human/browser: Keycloak issues token or Odoo session
Public API:    client -> Caddy -> Kong validates token/policy
              -> Middleware revalidates authorization -> governed adapter
              -> authoritative application API

Application event: authoritative application transaction + local outbox
                   -> private authenticated Middleware event ingress + inbox
                   -> validated subscribers
                   -> Odoo operational projection
                   -> approved analytics projection
                   -> optional approved inactive-by-default n8n automation

Provider callback: provider -> Caddy -> Kong source policy
                   -> Middleware provider adapter + durable inbox
                   -> normalized result/event subscribers
```

Keycloak is the identity and token issuer. It is not synchronously called to
validate every request; Kong and Middleware validate signed tokens using the
configured issuer, audience, keys, expiry, authorized party, and scopes.
Application events do not depend serially on Odoo, n8n, or analytics. Each is
an authorized subscriber or projection target so one failure cannot corrupt or
block every other destination.

Telemetry is a separate plane with type-correct paths:

```text
metrics -> application /metrics -> Prometheus -> Alertmanager and Grafana
logs    -> application stdout/file -> Alloy -> Loki -> Grafana
traces  -> application OTLP -> Alloy/OTel Collector -> Tempo -> Grafana
```

Monitoring components never carry business commands or become business data
authorities.

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
| Odoo could accept application/provider webhooks | Provider callbacks and application event ingress terminate at Kong/Middleware. Odoo accepts only normalized Middleware results through the existing private integration contract. |
| Tenant, company, business unit, and campaign might be inferred by names | All mappings are explicit and fail closed. Browser payloads cannot select or override the authenticated campaign scope. |
| New `/platform/v1` Odoo routes could be added beside current routes | Odoo preserves `/api/v1/integration/*` as its private Middleware contract. New browser APIs are added only where a native model service cannot satisfy the client, and never duplicate an existing operation. |
| Business-unit Admin and Closer were treated as established roles | They are not added. Existing platform, tenant, and campaign roles remain canonical. Closing capability is an explicit skill/policy assigned to an existing campaign role, not an implicit new security tier. |
| The master mission listed an immutable Odoo campaign manifest version | That item is rejected because it conflicts with Middleware manifest authority. Odoo owns `cc.campaign.configuration.version` and references existing immutable returned design-revision evidence; no Odoo manifest owner is created. |
| Keycloak appeared as an inline request-validation hop | Keycloak issues identities and tokens. Kong validates gateway policy and token claims; Middleware independently revalidates the authorization context. |
| Odoo, n8n, and analytics appeared as one serial result pipeline | They are independent governed consumers of a durable normalized event. n8n is optional, asynchronous, versioned, allowlisted, and inactive by default. |
| Prometheus appeared to feed Loki and Tempo | Metrics, logs, and traces use separate pipelines. Prometheus may alert through Alertmanager; Loki stores logs; Tempo stores traces; Grafana visualizes approved data sources. |
| Public webhook headers assumed every provider supports bearer tokens and Codestra signatures | Each public source uses its strongest supported allowlisted authentication profile: mTLS, OAuth/service token, HMAC signature, or an approved combination. Middleware normalizes identity and verifies replay protection before persistence. Internal Codestra delivery uses the full standard header set. |
| Both `/internal/v1/*` and root health routes were mandatory | They are logical capabilities. Each repository maps them to one existing canonical route family and publishes that mapping in its service manifest; it does not expose duplicates. |
| `ODOO_WRITE=false` could disable ordinary Odoo CRM work | No ambiguous global Odoo-write flag is introduced. Existing feature flags govern external application mutations and live side effects; normal authorized Odoo-owned CRM writes remain available. |
| Business-application outboxes appeared to use the public provider webhook route | Application outboxes use private authenticated Middleware event ingress or an existing equivalent. `/platform/v1/webhooks/{source}/events` is the governed public provider-callback surface only. |

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

### 10.5 Cross-repository integration-readiness lifecycle

The Master Mission's `DRAFT -> VALIDATED -> APPROVED -> PROVISIONING ->
PROVISIONED_DISABLED -> SYNTHETIC_TESTED -> ACTIVE` sequence is retained as a
cross-repository integration-readiness projection. It does not replace the
implemented campaign, configuration, workflow, Middleware revision, provider,
or domain lifecycles. Odoo derives and displays the readiness projection from
immutable evidence. `ACTIVE` is unavailable unless a separate explicit
production authorization permits the relevant side effect; technical
certification alone is not activation authority.

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

### 13.4 Cross-repository route ownership

The following are logical platform contracts. Every repository must first map
them to an existing compatible route and canonical contract. A new route is
allowed only when the owner repository proves the capability is missing and
documents backward compatibility.

Middleware alone owns the service catalog and governed integration API:

```text
GET    /platform/v1/services
POST   /platform/v1/services
GET    /platform/v1/services/{service_id}
PATCH  /platform/v1/services/{service_id}
POST   /platform/v1/services/{service_id}/validate
POST   /platform/v1/services/{service_id}/activate
POST   /platform/v1/services/{service_id}/decommission
GET    /platform/v1/services/{service_id}/dependencies
GET    /platform/v1/services/{service_id}/health

GET    /platform/v1/integrations/{application_id}/status
GET    /platform/v1/integrations/{application_id}/capabilities
POST   /platform/v1/integrations/{application_id}/commands/{command_name}
GET    /platform/v1/integrations/{application_id}/commands/{command_id}
GET    /platform/v1/integrations/{application_id}/projections/{resource}/{resource_id}
POST   /platform/v1/integrations/{application_id}/test
POST   /platform/v1/integrations/{application_id}/reconcile
GET    /platform/v1/integrations/{application_id}/drift
POST   /platform/v1/integrations/{application_id}/disable
```

`command_name` is selected from a versioned allowlist. It never resolves an
arbitrary Python function, Odoo model/method, SQL statement, table, URL, or
source-code symbol.

Each authoritative application backend publishes one mapped private interface,
using existing equivalent routes where compatible:

```text
live health; ready health; version; capabilities; metrics;
submit allowlisted command; read command status; read safe projection;
consume authenticated Middleware event when the domain requires it
```

The illustrative `/internal/v1/*` paths in the Master Mission are not a mandate
to duplicate existing routes. Their chosen mappings are private, gateway and
network restricted, service authenticated, and recorded in the canonical
service manifest and OpenAPI contract.

Odoo's optional browser JSON surface maps the logical operations below to
existing actions/controllers before a new controller is considered:

```text
GET /cc/api/v1/me/workspace
GET /cc/api/v1/me/workspace-schema
GET /cc/api/v1/me/work-queue
GET /cc/api/v1/me/dashboard-summary
GET /cc/api/v1/supervisor/live
GET /cc/api/v1/supervisor/campaign-summary
GET /cc/api/v1/admin/integrations
GET /cc/api/v1/admin/provisioning
GET /cc/api/v1/admin/drift
```

These are not substitutes for `/api/v1/integration/*`, and native Odoo screens
use the same model/domain services rather than duplicating controller logic.

### 13.5 Service capability manifest

The implementation plan must locate the existing canonical service-manifest
format before changing it. Applications publish their own capabilities;
Middleware is authoritative for activation and integration status. The
canonical or mapped format must cover:

- stable service ID, display name, owner repository, service type, environment,
  tenant mode, business owner, and technical owner;
- runtime service-location reference without an embedded credential;
- Keycloak audience and required scopes;
- the single mapped liveness, readiness, version, metrics, OpenAPI, and AsyncAPI
  locations, with `not_applicable` where justified;
- dependencies and data classification;
- allowlisted commands, published events, and consumed events;
- timeout, retry, circuit-breaker, idempotency, and reconciliation policies;
- kill-switch name and SLO.

The logical field vocabulary is:

```yaml
service_id:
display_name:
owner_repository:
service_type:
environment:
tenant_mode:
business_owner:
technical_owner:
base_url_secret_ref:
keycloak_audience:
required_scopes:
health_live_path:
health_ready_path:
version_path:
metrics_path:
openapi_path:
asyncapi_path:
dependencies:
data_classification:
supported_commands:
published_events:
consumed_events:
timeout_policy:
retry_policy:
circuit_breaker_policy:
idempotency_policy:
reconciliation_supported:
kill_switch_name:
slo:
```

If the existing canonical format uses different field names, its documented
one-to-one mapping is extended instead of creating this as a second manifest.

OpenBao references identify credentials and signing material; plaintext secret
values, tokens, credentials, or URLs containing credentials are prohibited.

### 13.6 Command envelope and trust rules

Every cross-system mutation uses one immutable, schema-versioned command
envelope containing:

```json
{
  "schema_version": "1.0",
  "command_id": "uuid",
  "command_type": "application.resource.action",
  "tenant_id": "tenant-id",
  "business_unit_id": "business-unit-id-or-null",
  "application_id": "application-id",
  "campaign_id": "campaign-id-or-null",
  "entity_type": "resource",
  "entity_id": "source-entity-id",
  "actor": {
    "subject": "keycloak-subject",
    "actor_type": "human-or-service",
    "roles": ["audit-snapshot-only"]
  },
  "correlation_id": "uuid",
  "causation_id": "uuid-or-null",
  "idempotency_key": "stable-key",
  "expected_source_version": "version-or-null",
  "requested_at": "RFC3339 timestamp",
  "payload_hash": "sha256",
  "payload": {}
}
```

Middleware derives trusted actor, tenant, application, campaign, role, audience,
and scope context from the authenticated identity and authoritative mappings.
Client-supplied actor roles are audit claims only and cannot grant authority.
The owner validates schema and state before mutation, persists asynchronous
commands durably, applies optimistic concurrency where supported, and retains
immutable audit metadata. An identical retry returns the stored result. Reuse
of an idempotency key with a different canonical payload hash returns `409`.
Secrets never enter the command payload.

### 13.7 Event and projection envelope

Authoritative applications write domain state and an event to a local
transactional outbox in the same database transaction. They never dual-write
business state and Middleware over HTTP. The versioned event envelope contains:

```json
{
  "schema_version": "1.0",
  "event_id": "uuid",
  "event_type": "application.resource.state_changed",
  "tenant_id": "tenant-id",
  "business_unit_id": "business-unit-id-or-null",
  "application_id": "application-id",
  "campaign_id": "campaign-id-or-null",
  "entity_type": "resource",
  "entity_id": "source-entity-id",
  "source_version": "monotonic-version",
  "occurred_at": "RFC3339 timestamp",
  "correlation_id": "uuid",
  "causation_id": "command-or-event-id",
  "idempotency_key": "stable-event-key",
  "payload_hash": "sha256",
  "payload": {}
}
```

Middleware and downstream consumers use durable inboxes, unique event IDs,
canonical payload-hash comparison, out-of-order protection by source version,
bounded retry with jitter, dead-letter evidence, authorized replay without a
new event identity, schema compatibility, readback, and reconciliation. Tenant,
application, business-unit, and campaign values are mandatory when applicable
and are validated against explicit bindings rather than trusted from payloads.
No Kafka, NATS, or other broker is introduced until repository evidence shows
an adopted authority or measured PostgreSQL-outbox throughput fails an approved
SLO. n8n is not an event bus.

### 13.8 HTTP result semantics

Owners use one RFC 9457-style problem-details representation and these semantic
classes: `200` for synchronous success or identical completed replay; `201` for
owner-created resources; `202` for durable asynchronous acceptance; `400` for
malformed syntax; `401` for invalid identity; `403` for denied scope; `404` for
an authorized missing resource; `409` for replay-hash, version, or state
conflict; `422` for schema/domain rejection; `429` for rate limiting; `502` for
invalid upstream response; `503` for disabled integration, closed kill switch,
or unavailable dependency; and `504` for governed timeout. Authentication,
authorization, schema, domain, and illegal-state errors are never automatically
retried.

### 13.9 Runtime discovery and public entry points

Known public entry points are configuration inputs, not literals embedded in
application logic:

```text
API edge:      https://api.codestra.co
Odoo CRM:      https://crm.codestra.agency
Keycloak:      https://auth.codestra.co
n8n editor:    https://automation.codestra.co
Browser phone: https://phone.codestra.agency
```

No Grafana, Superset, provider, or internal application URL is invented by this
design. The implementation discovers them from the current deployment and
canonical service registry. Public integration API traffic enters through
Caddy and Kong. Browser/static delivery and Odoo's interactive web session use
their approved ingress mappings but cannot bypass Middleware for cross-system
commands. Databases, monitoring listeners, private provider callbacks, and
application backends have no ungoverned public route.

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

### 14.1 Governed integration lanes

The application registry and template pack declare capabilities, not generic
CRUD. The corresponding authoritative backend owns validation and state:

- **Breero:** read-safe service-request, provider, booking, assignment, and
  status projections; allowlisted assignment/status/follow-up/escalation
  commands only. Payment, payout, provider, and marketplace ledgers remain in
  Breero.
- **Booked4Seasons:** verified-attribution intake into Breero's existing
  contracts, including consent and idempotency; no booking engine, provider
  database, or second Breero adapter.
- **Transportation:** customer, carrier, driver, equipment, quote, shipment,
  stop, dispatch, tracking, and approved finance projections; governed quote,
  assignment, dispatch-transition, callback, and escalation commands.
- **MoneyBee:** lead, application, amount, document, underwriting status, offer,
  funding, renewal, and complaint projections. Odoo coordinates but never
  decides underwriting, approval, funding, or ledger state. An existing valid
  MoneyBee bridge is extended rather than replaced.
- **Beyvra:** read-safe customer, KYC, compliance, account summary,
  restrictions, risk, and support projections; approved support commands only.
  Trading orders, live money, account authority, and compliance overrides stay
  within Beyvra and governed Middleware contracts.
- **LARIM-A:** service, provider, quote, booking, availability, visit, review,
  and case projections; payments, fulfillment, and marketplace truth remain in
  LARIM-A.
- **Restaurant:** authorized restaurant, order, reservation, and support
  projections. Inventory, payment, fulfillment, and restaurant authority remain
  in the restaurant backend.
- **Kyqra:** provenance-rich, consent-bearing, deduplicated lead-source events
  from the proven canonical ingestion owner; never a second CRM.
- **Klyrow:** tenant/campaign-scoped senders, templates, messages, suppressions,
  preflight, and delivery callbacks. Live delivery remains disabled.
- **Telnexa:** tenant/campaign-scoped senders, templates, messages,
  conversations, suppression, usage, delivery, and inbound projections. Live
  delivery remains disabled.
- **VICIdial:** campaign/list/group/script/disposition/agent/phone desired state,
  readback, and call events. Provision disabled first; external PSTN remains
  disabled.
- **n8n:** only approved versioned workflows with one owner, input/output
  schemas, service identity, idempotency, timeout, retry, and kill switch;
  installed inactive.

Existing compatible public form operations such as sales contact, demo,
pricing, electronic-billing application, and electronic-billing registration
remain at their current canonical routes. They are not duplicated under
`/platform`. Breero, Booked4Seasons, Beyvra, and any other application
attribution fails closed until tenant/application context, consent, and
idempotency are verified.

## 15. Integration, communications, and webhooks

An Odoo transaction commits to the existing Odoo outbox. An authorized
Middleware worker claims it through the existing Odoo private outbox contract
and then uses the governed adapter to reach the application/provider. This
preserves the implemented pull/lease/acknowledgement model; no competing Odoo
push dispatcher is added. A business application's local transactional outbox
reaches a private, authenticated Middleware event-ingress mapping. Public
provider callbacks enter through Caddy -> Kong -> the one mapped Middleware
provider endpoint -> durable inbox. Both paths produce validated normalized
results/events. Odoo receives only the authorized subset through its existing
result ingress, applies a canonical projection, and publishes campaign-scoped
bus notifications.

All commands/events carry schema version, event/command identity, tenant,
business unit, application, campaign, entity, correlation, causation,
idempotency key, payload hash, timestamp, and source version where applicable.
Odoo company is enforced through the authoritative tenant/company/business-unit
binding and may be included as versioned metadata only when the receiving
contract understands it.

Klyrow, Telnexa, and VICIdial provider callbacks terminate at Middleware. Odoo
receives delivery/call/result projections only. n8n workflows are versioned,
allowlisted, service-authenticated, idempotent, and installed inactive.

The logical public provider-callback surface is
`POST /platform/v1/webhooks/{source}/events`, but Middleware must map a compatible
existing provider-specific endpoint instead of creating both. Every source has
one allowlisted authentication profile. Where the source supports the Codestra
standard, the request carries bearer service identity, content type, event ID,
timestamp, versioned signature and key ID, correlation ID, causation ID, and
idempotency key. Signatures cover the exact raw body. Sources that cannot issue
bearer tokens require an approved compensating profile such as mTLS plus HMAC;
they do not receive an insecure exception.

The normalized Codestra header vocabulary is:

```http
Authorization: Bearer <service-token>
Content-Type: application/json
X-Codestra-Event-Id: <event-id>
X-Codestra-Timestamp: <unix-or-rfc3339>
X-Codestra-Signature: <versioned-signature>
X-Codestra-Key-Id: <active-or-previous-key-id>
X-Correlation-ID: <correlation-id>
X-Causation-ID: <causation-id>
Idempotency-Key: <stable-key>
```

Middleware rejects expired timestamps, unknown bindings, unsupported content
types, oversized bodies, invalid signatures, and over-limit sources before
business processing; it records safe rejection evidence without logging secrets
or sensitive raw payloads. A valid request is persisted before `202`. Identical
duplicates return the original acknowledgement, while changed-content reuse of
an event ID or idempotency key returns `409`. Authorized replay preserves event
identity.

Current default-off controls remain false, using existing canonical flag names:
live email, live SMS, callbacks/external application writes, n8n activation,
PSTN, live call control, lead publication, agent synchronization, production
eligibility, and campaign live enablement. The generic label `ODOO_WRITE` is not
introduced because it could be misread as disabling ordinary Odoo-owned CRM
writes.

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

Dashboard datasets carry tenant, application, business-unit, campaign,
environment, source-version, last-event, projection-lag, and reconciliation
dimensions as applicable. Keycloak SSO and role mapping govern access; Superset
also enforces row-level security. Applications never write directly into a
dashboard UI store.

Every card exposes `last_updated_at` and freshness state. Missing data is
`STALE` or `DISCONNECTED`, never zero. Customer identifiers, phone/email values,
message bodies, tokens, signatures, credentials, and recordings are prohibited
from metric labels and unrestricted logs.

Required freshness objectives are 1-3 seconds for calls and agent presence,
1-5 seconds for operational record changes, 15-60 seconds for campaign KPI
aggregation, near-real-time logs/traces/alerts, and 5-15 minutes for historical
analytics. These are initial SLO objectives, not claims about current runtime
performance; implementation must establish measurements and error budgets.

Every application exposes or maps exactly one liveness, readiness, version, and
metrics capability. Instrumentation covers request rate/duration/errors,
command acceptance/completion/failure, webhook acceptance/rejection/signature
failure, inbox/outbox depth and oldest age, retries, dead letters,
reconciliation mismatch, dependency state, circuit-breaker state, data
freshness, and projection lag. W3C `traceparent` and the Codestra correlation ID
propagate across supported hops.

Application repositories emit telemetry but do not deploy their own Prometheus,
Grafana, Loki, Tempo, Alloy, Alertmanager, Superset, or OpenBao stacks. Structured
logs redact passwords, API keys, tokens, cookies, authorization headers,
signatures, message bodies, recordings, and sensitive customer/financial data.

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

For each integration role, the owning identity configuration reuses or creates
exactly one Keycloak service client, one application-specific audience, and
least-privilege scopes for the required commands, projections, events,
reconciliation, or administration. Service credentials are not shared between
applications. Kong validation never replaces Middleware authorization.
Middleware validates issuer, audience, signature, expiry, authorized party,
scope, tenant, application, campaign, and command binding again before routing.

OpenBao owns credentials, mTLS material, provider secrets, and webhook signing
keys. Application and Odoo records store only opaque path/secret identifiers.
Rotation supports active and previous key IDs for a bounded overlap period, and
negative tests cover wrong issuer, audience, scope, tenant, campaign, signature,
timestamp, and retired key.

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
- canonical OpenAPI/AsyncAPI validation, generated-artifact drift, and backward-
  compatibility tests;
- command idempotency, concurrent duplicate, payload-hash mismatch, optimistic-
  concurrency, and illegal-transition tests;
- outbox transaction rollback, leasing, acknowledgement, failure, replay, stale
  result, and reconciliation tests;
- inbox event-ID deduplication, payload-hash mismatch, out-of-order source
  version, dead-letter, and authorized replay tests;
- webhook exact-raw-body signature, active/previous key, timestamp expiry,
  content type, size limit, rate limit, and replay tests;
- wrong issuer, audience, authorized party, scope, tenant, application,
  business-unit, campaign, and role tests;
- timeout, bounded retry, circuit breaker, dependency outage, readback,
  reconciliation, and kill-switch tests;
- Middleware contract and normalized result tests;
- VICIdial/Klyrow/Telnexa/n8n disabled-first and kill-switch tests;
- dashboard campaign isolation, freshness, stale/disconnected state, and PII
  redaction tests;
- secret scanning, dependency scanning, structured-log redaction, and telemetry
  label-cardinality/PII tests;
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

This Odoo specification defines Odoo-owned behavior and the contracts it relies
on. The later multi-repository implementation plan assigns work only after each
repository has been inspected at an exact SHA. No repository may create a
self-integration, local clone of another repository's source of truth, duplicate
foundation branch, duplicate contract authority, or embedded copy of the shared
identity, secrets, gateway, monitoring, or analytics platform.

No repository may query or mutate another application's database, expose a
generic arbitrary-model/method/table/SQL writer, maintain parallel `/v1` and
`/v2` surfaces without a proven breaking-change migration, duplicate an
OpenAPI/AsyncAPI source, hand-written SDK, webhook receiver, n8n workflow,
campaign/customer/workflow/membership/channel owner, or build an adapter whose
source and target are the same service. Overlap is preserved until consumers,
data, rollback, and deprecation evidence make removal safe.

### 23.1 Binding ownership matrix

| Repository/service | Authoritative responsibility |
| --- | --- |
| `Middleware-` | Service registry, cross-system authorization/orchestration, command routing, event ingress, inbox/outbox coordination, adapters, idempotency, reconciliation, drift, and kill switches |
| `Odoo` | Campaign control plane, campaign CRM/projections, memberships, agent/supervisor/admin workspaces, tasks, operational communication timeline, desired provisioning state, and reconciliation display |
| `Keycloak` | Human/service identities, clients, audiences, roles, scopes, MFA, and token issuance |
| `Kong` | Gateway authentication enforcement, route policy, rate/request limits, and governed ingress |
| `Caddy` | TLS termination and approved upstream routing; no business logic |
| `Codestra-OpenBao` | Secret custody, rotation material, and opaque credential references |
| `N8N` | Approved asynchronous automation only; not business authority, gateway, event bus, or secret store |
| `Breero.com` | Service requests, providers, bookings, assignments, marketplace, and service-delivery truth |
| `booked4seasons` | Customer-facing intake that reuses Breero contracts; no second booking backend |
| `transportation-backend-` | Customers, carriers, drivers, equipment, quotes, shipments, stops, dispatch, and logistics truth |
| `Moneybee-Backend` | Loan leads/applications/documents, underwriting, offers, funding, renewals, and complaints |
| `beyvra-backend` | KYC, compliance, accounts, restrictions, support, and trading-domain truth |
| `LARIM-A-Backend` | Providers, services, quotes, bookings, availability, visits, reviews, and cases |
| Restaurant frontend and authoritative backend | Restaurant experience, orders, reservations, fulfillment, and restaurant-scoped operations; the frontend is presentation/session only |
| `kyqra-crawler` | Lead discovery and ingestion source unless repository evidence proves a different canonical owner |
| `kyqra` | Deprecated by default unless inspection proves a separate valid responsibility; never a second CRM |
| `klyrow.com` | Email domains/senders/templates/messages, suppressions, delivery events, and deliverability |
| `telnexa` | SMS senders/templates/messages/conversations, suppressions, usage, delivery events, and inbound SMS |
| `Vicidialer-Codestra` | Dialer campaigns/lists/groups/scripts/dispositions, agents, phones, active call state, and call events |
| `SDK-repository` | Generated clients from canonical contracts; never a competing OpenAPI/AsyncAPI authority |
| Named monitoring repositories | Their named shared monitoring component only; no self-registration clone |
| Grafana | Operational visualization over approved Prometheus, Loki, Tempo, and Alertmanager data |
| Superset | Historical analytics over protected minimized analytics data; never an operational command surface |

Frontend repositories contain presentation and session logic only. They never
hold cross-system credentials, provider adapters, transactional integration
workflows, or business authority. Similar frontend/backend names are classified
by evidence before any duplication decision.

### 23.2 Repository-aware execution gate

Every repository receives the same scoped execution protocol:

1. Identify repository and exact baseline from remotes, manifests, package
   metadata, README, source layout, current branch, worktree, and recent commits.
2. Read repository instructions and architecture/contract authority before
   editing.
3. Inventory existing models, migrations, controllers, schemas, adapters,
   clients, webhooks, workflows, dashboards, deployment files, tests, and open
   implementation paths.
4. Classify every relevant capability as `EXISTING_AND_VALID`,
   `EXISTING_BUT_PARTIAL`, `EXISTING_BUT_CONFLICTING`,
   `MISSING_IN_OWNER_REPOSITORY`, `EXTERNAL_DEPENDENCY`, or `NOT_APPLICABLE`.
5. Determine overlap authority from production usage, migrations, tests,
   canonical contracts, and repository documents. Preserve the authority,
   migrate consumers, deprecate obsolete paths, and retain rollback evidence.
6. Present a concise repository-specific design and file-impact/test plan and
   obtain explicit approval before implementation.
7. Change only that repository's owned capability. Record external dependencies
   and required contracts instead of building local replacements.
8. Test and report only evidence directly observed at the exact implementation
   SHA. Never imply another repository was changed, tested, deployed, or
   certified.

Protected branches, merge, deployment, or production activation require their
own authorization and green gates. A shared mission prompt is not authorization
for those actions.

### 23.3 Program gates, not a premature implementation plan

The cross-repository program proceeds through repository truth/ownership,
contract foundation, identity/secrets/gateway, Middleware core, Odoo control
plane, application domain interfaces, communications/automation,
dashboards/observability, contract/security certification, staging end-to-end
certification, and production handoff. Each repository executes only applicable
gates. Detailed repository order, file impacts, commits, tests, and handoffs are
defined in the implementation plan after this written design is approved.

Staging must prove the authorized equivalent of:

```text
Odoo action -> Odoo outbox -> Middleware governed claim
-> authoritative application -> readback
-> application outbox event -> Middleware durable inbox
-> Odoo timeline/dashboard + monitoring evidence + authorized analytics fact
```

The same test run proves wrong issuer/audience/scope, wrong tenant/campaign,
duplicate/replay, payload-hash mismatch, stale source version, invalid or
expired signature, closed kill switch, disabled integration, provider timeout,
dead-letter/replay, and reconciliation mismatch all fail safely. n8n is tested
as an optional inactive subscriber, not as a required hop in this chain.

### 23.4 Completion-report contract

Each repository returns this structure without fabricated counts or evidence:

```text
APPLICATION INTEGRATION PLANE — REPOSITORY REPORT

Repository:
Repository role:
Branch:
Implementation SHA:
Baseline SHA:
Working-tree status:

Authority decision:
Existing components reused:
Duplicate components found:
Duplicate components removed or deprecated:
Self-integration check:

Models changed:
Migrations:
Public endpoints:
Private endpoints:
Webhook endpoints:
Commands:
Events published:
Events consumed:
Projections:
Dashboard destinations:

Keycloak client/audience/scopes:
OpenBao secret references:
Kong/Caddy requirements:
Middleware dependency:
Other repository dependencies:

Tests executed:
Tests passed:
Tests failed:
Tests skipped:
PostgreSQL evidence:
Contract evidence:
Security evidence:
Webhook evidence:
Reconciliation evidence:
Dashboard/observability evidence:
Staging end-to-end evidence:

Default-off flags:
Kill switches:
Rollback procedure:

Unresolved blockers:
Production activation authorized: NO unless explicit evidence exists
Verdict: PASS / PARTIAL / BLOCKED / FAIL
```

`PARTIAL`, `BLOCKED`, and `FAIL` remain accurately labeled. Technical
certification never grants permission for live delivery, dialing, trading,
financial actions, external writes, merge, deployment, or production
activation.
