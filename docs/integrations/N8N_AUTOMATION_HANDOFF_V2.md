# Odoo 19 ↔ Middleware ↔ n8n Automation Handoff v2

## Exact contract lineage

```text
Odoo repository: appolon1908-hue/Odoo
Odoo branch: integration/n8n-automation-v2
Odoo base SHA: 35d87740ac76458e3652b7d71ba2a2a6da2d8893
Middleware contract SHA: bd6c7c0a470a74ef648fe2a21e2d9dcd4c2328a4
N8N contract SHA: e3a3e97ab0da0d7df78bba52b18904e5f83e6dbe
Production activation: NOT AUTHORIZED
```

## Authority boundary

Odoo is the business system of record for CRM records, customers, leads, opportunities, activities, appointments, callbacks, campaigns, support cases, call history, consent projections, and business communication history.

n8n must never connect directly to Odoo, Odoo PostgreSQL, or Odoo credentials. All cross-system writes and reads use the approved Middleware Odoo adapter.

```text
Odoo business event
 -> Odoo transactional outbox
 -> Middleware durable inbox
 -> Middleware automation job
 -> n8n orchestration
 -> Middleware governed Odoo command
 -> Odoo service operation
 -> Odoo read-back
 -> Middleware reconciliation
```

## Required Odoo modules or additive extensions

Implement through focused child branches after this contract is reviewed:

```text
codestra_middleware_bridge
codestra_automation_outbox
codestra_automation_projection
codestra_automation_approvals
codestra_delivery_history
codestra_identity_reference
codestra_consent_preferences
```

Reuse existing equivalent modules rather than creating duplicate authorities.

## Outbound Odoo events

Odoo writes an outbox row in the same transaction as the business change. Suggested events:

```text
crm.lead.intake_requested
crm.lead.normalized
crm.callback.requested
crm.appointment.reminder_due
crm.campaign.enrollment_requested
crm.opportunity.stage_changed
support.case.created
privacy.preference.changed
crm.email.requested
telephony.call.requested
crawler.job.requested
```

Every event carries tenant/company, Odoo record identity, correlation, causation, idempotency, actor, event version, timestamps, and safe payload metadata.

## Inbound governed commands

Only the Middleware Odoo service identity may request supported operations:

```text
create_or_update_lead
create_activity
create_call_followup
create_or_update_callback
create_or_update_calendar_event
create_support_case
record_message_request
record_delivery_result
record_identity_projection
record_consent_projection
record_crawler_enrichment
create_operations_exception
```

Do not expose a generic unrestricted model/method executor.

## Idempotency and concurrency

- Store the Middleware command ID and semantic request digest.
- Exact replay returns the original result.
- Conflicting replay returns `idempotency_conflict` without modifying the original record.
- Use row locks or optimistic versions where concurrent state transitions matter.
- A command result is complete only after destination read-back.
- Human users cannot fabricate immutable provider or completed-call events.

## Company and tenant isolation

- Every command names one authoritative tenant/company mapping.
- The service identity receives only approved companies and models.
- Record rules continue to protect human users.
- Cross-company identifiers fail closed.
- No sudo path may turn a tenant mismatch into a valid command.

## Automation workflows paired with this branch

```text
N8N/automation/odoo-crm
N8N/automation/identity-provisioning
N8N/automation/vicidial-telephony
N8N/automation/telnexa-sms
N8N/automation/klyrow-email
N8N/automation/kyqra-crawler
N8N/privacy/data-rights
N8N/operations/reconciliation
```

## Capability gates

Middleware must enforce the effective gate immediately before each effect:

```text
ODOO_WRITE=false
CALLBACK_DISPATCH=false
ENABLE_EXTERNAL_DELIVERY=false
LEAD_PUBLISH=false
CRAWLER_WRITEBACK=false
PRIVACY_WRITE=false
PRODUCTION_DIALING=false
```

An active n8n workflow does not enable any of these capabilities.

## Required tests

```text
clean install and upgrade
outbox transaction atomicity
service authorization
company isolation
exact replay
conflicting replay
concurrent duplicate
callback/calendar synchronization
consent and suppression projection
provider delivery duplicate
Middleware outage recovery
n8n duplicate execution
rollback and restore
zero external effects in staging
```

No Odoo database, module, container, credential, workflow, external message, call, or production service is changed by this documentation branch.
