# Communications Platform Authority — Odoo / CRM and Business State

## Purpose

This document defines `appolon1908-hue/Odoo` as the principal CRM and business-state authority participating in the unified communications platform.

## Permanent ownership

This repository owns:

- Codestra Odoo custom modules and business workflows;
- CRM leads, contacts, activities, campaign-facing business state and approved business records;
- campaign-scoped scripts, dispositions, callbacks, dashboards and supervisor/agent workflow modules where implemented in Odoo;
- Odoo-side command/result mapping and user experiences;
- module migrations, tests and release evidence.

This repository does not own:

- cross-system authorization, durable command state, provider credentials, idempotency or provider execution — `Middleware-`;
- SMS runtime — `telnexa`;
- email runtime — `klyrow.com`;
- voice runtime — `Vicidialer-Codestra`;
- public API gateway — `Kong`;
- identity issuance — `Keycloak`;
- workflow orchestration — `N8N`;
- public SDK/contracts — `SDK-repository`;
- TLS edge — `Caddy`.

## Required path

```text
Odoo user/business workflow
      -> governed Odoo integration module
      -> Middleware command/event boundary
      -> provider/channel adapter
      -> Klyrow / Telnexa / VICIdial

Provider/channel event
      -> Middleware durable event boundary
      -> approved Odoo result/update mapping
      -> Odoo business state
```

Odoo modules must not call Postal, Jasmin/Telnexa, VICIdial/Asterisk or provider databases directly for privileged cross-system effects.

## CRM communications model

Odoo may request communication effects and receive normalized results, but Middleware remains responsible for effect authorization and delivery state. Odoo should persist business-facing references such as:

- communication/message ID;
- channel;
- related customer/contact/lead/case;
- campaign context;
- requested/scheduled time;
- high-level canonical status;
- provider reference where safe/useful;
- failure category suitable for business workflow;
- callback/follow-up requirements;
- consent/suppression outcome references;
- correlation/operation IDs for audit and support.

Odoo must not invent provider delivery truth. Delivered/failed/unknown state comes from the normalized Middleware/provider reconciliation path.

## Campaign isolation

Campaign isolation is mandatory across contact-center modules:

1. Each normal agent belongs to exactly one active campaign context.
2. An agent cannot view, access, receive leads from, transfer into, report on or receive campaign email for another campaign.
3. Each campaign has its own lead lists, scripts, dispositions, callbacks, recording references, inbound groups, transfer routes, dashboards, inboxes and workflows as applicable.
4. Each campaign has one primary supervisor unless the governance model is explicitly changed and reviewed.
5. Supervisors are limited to their campaign.
6. Global administration is separately authorized and fully audited.
7. Middleware commands must carry and validate campaign/tenant context where the operation is campaign-bound.

## Communication request rules

Effectful Odoo actions must use stable, versioned Middleware commands with:

- authenticated service/user context;
- tenant and campaign context;
- correlation ID;
- deterministic idempotency key;
- explicit communication capability;
- canonical request payload;
- expected-version/concurrency controls where business state can race.

The UI must present pending/accepted/submitted/delivered/failed/unknown states truthfully rather than assuming synchronous success.

## Event and result handling

Inbound normalized communication events must be processed idempotently. Odoo result handlers should:

- reject cross-tenant/cross-campaign mismatches;
- deduplicate event IDs/operation IDs;
- maintain an auditable event/result history;
- avoid destructive overwrites of prior delivery evidence;
- preserve indeterminate/unknown state until reconciliation resolves it;
- create approved follow-up activities when policy requires human action.

## Consent and suppression

Odoo can capture business consent/preferences and display suppression outcomes, but the actual pre-send enforcement at the cross-system boundary remains in Middleware/channel policy. Odoo must not provide a direct override around global/legal suppressions without a separately reviewed privileged workflow.

## Safety rules

1. No direct provider/database credentials in Odoo modules.
2. No direct cross-system writes that bypass Middleware.
3. No live send/dial action activated merely by installing a module.
4. Unknown provider outcomes remain visible as unknown/indeterminate until reconciled.
5. Campaign and tenant isolation must be enforced both in Odoo access rules and Middleware authorization.
6. PII/recording access follows least privilege and retention requirements.
7. CRM state-changing callbacks/results require idempotent processing and audit history.
8. Module upgrades that alter business data require migration, backup and rollback planning.
9. Staging must use non-live/fail-closed channel capabilities unless separately approved.
10. Emergency channel kill switches must not prevent Odoo from reading existing status/history.

## Cross-repository contract requirements

Odoo communication changes may require coordinated evidence from:

- `Odoo` — module/access/business-state behavior;
- `Middleware-` — command/event/authorization/reconciliation behavior;
- `SDK-repository` — public contract changes when applicable;
- `Keycloak` — Odoo service identity/scopes when changed;
- `Kong` — gateway route/scope policy if the Odoo integration crosses Kong;
- `klyrow.com`, `telnexa`, `Vicidialer-Codestra` — provider behavior behind Middleware;
- `N8N` — orchestration contracts where workflows act on Odoo events;
- `Caddy` — ingress changes where applicable.

## Release gates

Before communication-related Odoo modules or workflows are production-enabled:

1. static and runtime module CI pass at exact head;
2. access-control and campaign-isolation tests pass;
3. Middleware contract compatibility passes;
4. duplicate command/result tests pass;
5. tenant/campaign mismatch attempts fail closed;
6. unknown/reconciliation states are exercised;
7. staging smoke tests prove no provider bypass;
8. database/filestore backup and rollback are verified for data-changing upgrades;
9. exact reviewed SHA is deployed;
10. live channel capability activation is separately approved.

## Branching

Use short-lived `feature/*`, `fix/*`, `docs/*` and `test/*` branches. Changes flow through protected review and staging before production. Documentation changes do not authorize module installation, database migration, email/SMS sending or dialing.
