# Codestra Odoo 19 Corporate Call Center

## Public repository mission contract

**Status:** source-only engineering foundation  
**Target platform:** Odoo 19 with Codestra Middleware, VICIdial, Kong, Keycloak and explicitly allowlisted n8n automation  
**Canonical API prefix:** `/v1/contact-center/`  
**Canonical identity issuer:** `https://auth.codestra.co/realms/codestra`

This document is a sanitized repository contract derived from the approved corporate call-center mission. The original mission contains internal host inventory and remains outside this public repository. No credential, customer record, secret, private address, database dump, filestore, live configuration or provider authorization may be committed here.

## Mission objective

Preserve working Odoo records and stable external identifiers while progressively repairing the existing call-center integration and adding the missing corporate CRM, agent, supervisor, QA, compliance, workforce, billing, reporting and integration capabilities.

This repository is implementation source, not production evidence. A feature is not complete merely because code or a branch exists. Installation, migration, staging certification, exact-head review, immutable release evidence, backup/restore rehearsal, bounded canary and reconciliation remain separate gates.

## Authoritative system boundaries

| System | Authoritative responsibility |
|---|---|
| Odoo 19 | CRM, customer 360, interactions, tickets, campaigns, QA, client operations, reporting and business records |
| VICIdial | PBX, dialing, inbound queues, live call state, agent telephony state and recordings |
| Codestra Middleware | Authorization, contract validation, idempotency, transactional delivery, reconciliation and controlled downstream writes |
| Kong | Canonical API ingress, authentication enforcement, rate limits and request correlation |
| Keycloak | Human OIDC and machine client-credential identities |
| n8n | Explicitly allowlisted orchestration; never the system of record |
| Provider services | Email and SMS operations behind independent production gates |
| PostgreSQL | Odoo and integration data through Odoo ORM and reviewed migrations |
| Redis | Queues, leases and temporary coordination only |

Binding prohibitions:

- Odoo must not become a second dialer.
- Odoo add-ons must not write directly to VICIdial or provider databases.
- External systems must not write directly to Odoo PostgreSQL.
- n8n must not hold authoritative customer state or arbitrary Odoo credentials.
- Browser requests must not select arbitrary workflows, senders, Odoo record IDs or privileged provider actions.
- Odoo core source must not be modified.

## Safety defaults

Every branch starts with the following capabilities closed:

```text
LIVE_ODOO_WRITE=false
ENABLE_EXTERNAL_DELIVERY=false
EMAIL_DELIVERY=false
SMS_DELIVERY=false
PSTN_DIALING=false
CALLBACK_DISPATCH=false
N8N_ACTIVATION=false
```

Only one external channel may be certified at a time. Code, documentation and CI must never claim that a live gate passed without exact evidence from the reviewed environment.

## Module catalog

### Foundation and interaction integrity

- `codestra_cc_core`
- `codestra_cc_reliability`
- `codestra_cc_audit`
- `codestra_cc_vicidial`

### Agent and campaign experience

- `codestra_cc_agent_desktop`
- `codestra_cc_campaign`
- `codestra_cc_disposition`
- `codestra_cc_customer_360`
- `codestra_campaign_publishing`

### Corporate operations

- `codestra_cc_supervisor`
- `codestra_cc_quality`
- `codestra_cc_compliance`
- `codestra_case_management`
- `codestra_cc_workforce`
- `codestra_cc_identity`
- `codestra_agent_onboarding`
- `codestra_training_academy`

### Omnichannel and client operations

- `codestra_cc_omnichannel`
- `codestra_cc_mailbox`
- `codestra_cc_automation`
- `codestra_client_operations`

### Commercial, reporting and assistance

- `codestra_revenue_assurance`
- `codestra_cc_analytics`
- `codestra_data_quality`
- `codestra_client_portal`
- `codestra_ai_agent_assistant`

Each implemented module must have a valid Odoo 19 manifest, explicit dependencies, security groups or access controls, record rules where business records are stored, models, views where users operate the feature, tests, migration notes and module documentation. Circular dependencies are prohibited.

## Core data contract

The first implementation branch must establish typed, indexed models for:

- interactions and call legs;
- normalized events with unique source/event identity;
- campaigns, queues and versioned dispositions;
- wrap-up and callbacks;
- consent and suppression;
- controlled recording references;
- agent profiles and state;
- inbox, outbox and reconciliation;
- append-only audit;
- client contracts, rate plans, billable usage and provisioning jobs.

JSON may preserve a sanitized versioned event body, but it must not replace searchable business fields or required database constraints.

## API contract

The public contract is rooted at `/v1/contact-center/` and is exposed only through the governed ingress. The initial OpenAPI file defines:

- private health and readiness;
- VICIdial and provider event ingestion;
- authorized screen-pop resolution;
- interaction read, disposition, callback and transfer;
- agent state;
- supervisor queue views and audited actions;
- published campaign configuration;
- agent provisioning;
- reconciliation;
- operations reports and restricted audit search.

Side-effecting requests require a short-lived machine or user identity, request and correlation identifiers, and an idempotency key. Unknown event schema versions fail closed. Reusing an event ID with a different body must be rejected.

## User experience contract

The agent workspace must be responsive at common call-center desktop sizes and restore active interaction context after refresh. It includes:

- customer and verification state;
- campaign, queue, language and live call state;
- consent, DNC and recording warnings;
- customer profile and prior-interaction timeline;
- versioned script and dynamic campaign form;
- approved telephony controls;
- callback and supervisor-assistance tools;
- sticky mandatory wrap-up.

An agent cannot return to Ready until required wrap-up fields validate.

## Reliability contract

All external effects follow:

```text
Odoo transaction
  -> transactional outbox
  -> Middleware authorization and validation
  -> authorized downstream service
  -> result event
  -> inbox deduplication
  -> Odoo reconciliation
```

Implement bounded retry, lease expiry, stale-job recovery, dead-letter review, authorized replay, stable schema versions and end-to-end correlation. Reconciliation mismatches must remain visible and auditable.

## Authorization contract

At minimum, implement and negatively test Agent, Senior Agent, Closer, QA Analyst, Supervisor, Campaign Manager, Client Operations Manager, Workforce Manager, Compliance Officer, Billing Manager, Reporting Viewer, Integration Operator, Service Account and Platform Administrator.

Cross-company and cross-campaign reads must fail closed. Agents cannot edit consent evidence or restricted recordings. Reporting roles are read-only. Service accounts cannot use interactive login. Supervisor controls require dedicated permissions and immutable audit records.

## Delivery phases

1. Baseline and isolated restore evidence.
2. Repair and compatibility with existing Odoo records and external IDs.
3. Core schema, migrations, authorization, API, inbox and outbox.
4. Agent desktop, campaigns, dispositions, customer 360 and screen-pop.
5. Supervisor, QA, compliance, workforce, onboarding, portal, cases and revenue.
6. Synthetic contract certification for identity, ingress, Middleware, VICIdial, n8n and providers.
7. Negative authorization, security, accessibility, load and recovery testing.
8. Protected exact-head review and immutable release creation.
9. Sanitized isolated staging certification.
10. Approved production promotion through bounded, independently gated channels.

## Minimum engineering evidence

The cross-cutting assurance branch must retain evidence for:

- Odoo unit and ORM constraint tests;
- ACL and record-rule tests;
- controller and OpenAPI contract tests;
- browser screen-pop tests;
- event replay, ordering and collision tests;
- outbox, inbox, lease and reconciliation tests;
- fresh install, upgrade, interrupted migration and restore;
- accessibility and keyboard operation;
- secret, dependency and container scans;
- concurrent agent and event-processing load;
- worker and provider failure recovery.

Target outcomes include zero duplicate side effects, zero lost final interactions, zero cross-tenant exposure and zero unexpected customer messages.

## Branch governance

`config/call-center-workstreams.json` is the machine-readable branch and module ownership registry. `docs/branches/CALL-CENTER-BRANCH-STACK.md` defines dependency order. Feature branches remain draft until their own acceptance evidence exists.

Do not merge by administrator bypass. Do not deploy an uncommitted tree or mutable tag. A merged source SHA is not production-ready until its matching artifact, SBOM, provenance, staging evidence, rollback rehearsal and approval tuple are verified.

## Completion semantics

Use `PASS` only when the exact gate was executed and evidence is retained. Use `BLOCKED` when credentials, provider authorization, private repository controls, independent approval, runtime access or another external prerequisite is unavailable. Never reinterpret source-only work as a completed runtime, migration, staging or production deployment.
