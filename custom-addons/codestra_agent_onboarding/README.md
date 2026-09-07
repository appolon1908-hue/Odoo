# Codestra Agent Onboarding

This Odoo 19 application turns an approved employee-readiness record into one
governed contact-center identity and campaign assignment.

## Authority and lifecycle

Odoo owns the employee, the canonical `cc.campaign.membership`, the selected
role, the requested systems, and the approval evidence. The module never writes
to VICIdial, Keycloak, Klyrow, SIP, or Middleware directly.

The supported flow is:

```text
draft
→ in_review
→ approved
→ prepare access request
→ create inactive Odoo user
→ create one pending campaign membership
→ create one durable provisioning request
→ independent approval
→ reserve identifiers
→ emit agent.provisioning.requested.v1
→ external create-disabled + verification
→ matched Odoo/Keycloak/Middleware/VICIdial read-back
→ emit agent.activation-email.requested.v1
→ Keycloak creates a one-time action email delivered through Klyrow
→ explicit final activation
```

A prepared campaign assignment is immutable. Moving an agent to another
campaign uses the canonical revoke-then-grant reassignment workflow.

## Secure login email

The welcome event includes only:

- the approved login identifier;
- the credential-free HTTPS login page;
- the required Keycloak actions `UPDATE_PASSWORD` and `CONFIGURE_TOTP`;
- a bounded expiry;
- the Klyrow template key and recipient.

Odoo never generates, stores, logs, or emails a reusable plaintext password.
The one-time action URL is generated only by Keycloak at dispatch time and is
not returned to Odoo or persisted in the integration outbox.

The login URL is configured through:

```text
codestra.agent.activation.login_url
codestra.agent.activation.ttl_minutes
```

The URL must be HTTPS and contain no embedded credential, query, or fragment.

## Fail-closed behavior

The module refuses to continue when:

- readiness is incomplete;
- the campaign is not an approved canonical human-staffed workspace;
- the team, supervisor, department, branch, or role template crosses scope;
- an existing login would require unreviewed adoption;
- the requester attempts to approve their own access;
- the agent already has another open operational membership;
- the VICIdial username or user group is missing;
- any required provisioning step is not verified;
- identity read-back is missing or mismatched;
- the secure-login email lacks completed delivery evidence.

All external identities are requested in disabled state. No source flag enables
live dialing, live call control, external email delivery, or production
activation.

## Durable integration

Two immutable, idempotent events use the existing
`codestra.runtime.integration.outbox`:

- `agent.provisioning.requested.v1`
- `agent.activation-email.requested.v1`

Retries return the same event and cannot create duplicate users or duplicate
welcome emails. Result processing remains owned by the established integration
result inbox and Middleware/provisioning-service workflow.

## Verification

Run the module tests together with the repository source gates:

```bash
./scripts/run_ci.sh
```

The tests cover readiness, disabled user creation, one-campaign membership,
independent approval, identifier reservation, idempotent outbox production,
credential-free activation-email payloads, read-back gating, and immutable
campaign assignment.


### September 5 source reconciliation

Prepared onboarding inputs, company and integration identity are immutable; an RPC
context flag cannot bypass this boundary. Secure onboarding requires Keycloak
before preparation and an active role-template version. Campaign/company scope is
revalidated before preparing access.

Optional voicemail, recording_access and monitoring_access targets have matching
mandatory steps and callback identifiers. Secure-login activation requires a
processed, explicitly successful and reconciled result bound to its outbox event.
Historical receipts without explicit outcomes remain insufficient for activation;
they must be reconciled through authenticated, explicit result evidence. The new
`outcome_explicit` field defaults to false on existing rows.

These are source changes only. Module upgrades, database migration, account
provisioning, email delivery and production activation require separate approval.
