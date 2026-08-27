# Odoo 19 — Codestra Integration Fabric v2

## Authority

Odoo owns customers, contacts, companies, leads, opportunities, activities, campaigns, appointments, call history, support cases, communication preferences, and business communication history.

Odoo does not own Keycloak passwords or service clients, Kong policy, provider credentials, n8n state, telephony execution, SMS/email/social delivery truth, crawler execution, or cross-system retry.

## Communication path

```text
Odoo transaction -> Odoo integration outbox -> Middleware
Middleware command -> approved Odoo service operation -> Odoo read-back
n8n -> Middleware only -> Odoo adapter
```

n8n receives no Odoo API key, session, administrator account, JSON-2 credential, XML-RPC credential, or PostgreSQL access.

## CRM facade

The canonical public/internal business facade is owned by Middleware and exposes versioned operations for:

- contacts and companies;
- leads and opportunities;
- activities and campaign enrollment;
- callbacks and appointments;
- support-case routing;
- communication preferences and suppressions;
- call history and post-call follow-up;
- Odoo synchronization operations and read-back.

Every mutation requires tenant/company authorization, idempotency, correlation, causation, expected resource version where applicable, and destination read-back.

## Odoo event outbox

Odoo writes an event record in the same database transaction as the business change. An integration worker sends the event to Middleware with the `odoo-integration` service identity. The browser and n8n never deliver the outbox directly.

Event families include:

```text
crm.contact.changed.v1
crm.lead.created.v1
crm.lead.stage_changed.v1
crm.opportunity.changed.v1
crm.activity.completed.v1
crm.callback.requested.v1
crm.appointment.changed.v1
crm.call_followup.completed.v1
crm.support_case.changed.v1
privacy.preference.changed.v1
```

## Command families

Middleware may request only allowlisted, model-specific service operations:

```text
crm.contact.upsert.v1
crm.lead.upsert.v1
crm.lead.assign.v1
crm.activity.create.v1
crm.callback.schedule.v1
crm.appointment.upsert.v1
crm.call_history.append.v1
crm.support_case.route.v1
privacy.preference.project.v1
```

A service operation validates allowed fields and company boundaries. No generic model/method proxy is permitted.

## Capability defaults

```text
ODOO_WRITE=false
CALLBACK_DISPATCH=false
ENABLE_EXTERNAL_DELIVERY=false
CRAWLER_WRITEBACK=false
PRODUCTION_DIALING=false
```

## Implementation branches

```text
integration/n8n-automation-contract-v2-20260827
  -> integration/codestra-crm-fabric-v2
       -> feature/crm-facade-api-v1
       -> feature/automation-outbox-v1
       -> feature/communication-history-v1
       -> feature/consent-projection-v1
       -> feature/contact-center-automation-v1
       -> test/crm-fabric-contracts-v1
```

No branch is deployed directly. Odoo module installation, database migration, and live writes require separate exact-head release evidence.