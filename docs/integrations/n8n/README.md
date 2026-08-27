# Odoo 19 ↔ Middleware ↔ n8n integration

## Authority

Odoo 19 is the business system of record for customers, contacts, leads, opportunities, activities, callbacks, appointments, call history, consent projections, support records and business communication history.

n8n does not call Odoo directly and never receives an Odoo password, API key, session cookie or database credential.

```text
Odoo business event or external intake
  -> Odoo/Middleware outbox or Kong/Middleware API
  -> Middleware canonical event and automation job
  -> n8n timing, branching and approval
  -> Middleware Odoo command
  -> Odoo service operation and read-back
  -> Middleware reconciliation
  -> Odoo chatter/history projection
```

## Odoo publishes through Middleware

Proposed event families:

```text
crm.lead.intake_requested
crm.lead.normalized
crm.opportunity.stage_changed
crm.callback.requested
crm.callback.due
crm.appointment.created
crm.appointment.reminder_due
crm.campaign.enrollment_requested
support.case.created
privacy.preference.changed
privacy.deletion.requested
```

Odoo must publish durable events through an approved outbox. It does not call an n8n public webhook.

## Commands Odoo accepts through Middleware

```text
crm.lead.create_or_update
crm.lead.deduplicate_proposal
crm.lead.enrichment_apply
crm.activity.create
crm.callback.create_or_update
crm.appointment.create_or_update
crm.call_history.record
crm.communication_history.record
crm.support_case.assign
crm.preference.project
crm.external_result.reconcile
```

Each command carries tenant, correlation, causation and idempotency identifiers. Exact replay returns the original result. A conflicting replay is rejected without changing the original record.

## Initial n8n workflows

```text
codestra.crm.lead-intake.v1
codestra.crm.lead-deduplicate.v1
codestra.crm.lead-enrichment-review.v1
codestra.crm.post-call-followup.v1
codestra.crm.callback-schedule.v1
codestra.crm.appointment-reminders.v1
codestra.crm.stale-lead-reactivation.v1
codestra.crm.campaign-enrollment.v1
codestra.crm.support-case-route.v1
codestra.crm.consent-propagation.v1
codestra.crm.opportunity-stage-notification.v1
```

## Security and data rules

- No direct n8n access to Odoo or PostgreSQL.
- Odoo human users cannot fabricate provider events.
- Middleware service operations use a dedicated least-privilege identity.
- Every record is company/tenant scoped.
- PII remains in Odoo and approved Middleware payloads; workflow Git exports contain none.
- Long waits and approvals are durable Middleware state, not open n8n executions.
- Email, SMS, calling and crawler effects are separate capabilities and remain disabled by default.
- Odoo never writes directly to VICIdial, Asterisk, Jasmin, Postal, Mautic or a carrier.

## Branch dependencies

```text
Middleware-/core/integration-contracts
Middleware-/core/event-ledger-outbox
Middleware-/core/webhook-inbox-replay
Middleware-/core/workers-scheduler
Middleware-/integration/keycloak
Middleware-/integration/n8n
Middleware-/integration/odoo-19
N8N/contract/automation-control-plane-v2-20260827
N8N/shared/automation-runtime
N8N/automation/odoo-crm
```

## Acceptance

```text
DIRECT_N8N_ODOO_ACCESS=DENIED
DIRECT_DATABASE_ACCESS=DENIED
TENANT_ISOLATION=PASS
EXACT_REPLAY=PASS
CONFLICTING_REPLAY=PASS
CONCURRENT_DUPLICATE=PASS
CHATTER_AND_HISTORY_IDEMPOTENT=PASS
CAPABILITY_DEFAULT_FALSE=PASS
WORKFLOWS_ACTIVE_IN_GIT=NO
PRODUCTION_CHANGED=NO
```
