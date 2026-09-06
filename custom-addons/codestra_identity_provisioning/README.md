# Codestra Identity Provisioning

This Odoo 19 add-on coordinates reviewed identity and access requests for Odoo, Keycloak, VICIdial, SIP, agent-desktop and mailbox projections.

## Operating model

Provisioning is recorded as idempotent requests and steps with immutable audit evidence. Protected credentials are represented only by metadata references; secret values are not stored in Odoo business records.

The reviewed `post_init_hook` creates fail-closed safety flags and least-privilege defaults. Its use is explicitly declared against the exact module tree in the canonical add-on registry.

## Concurrency

Identifier uniqueness relies on Odoo constraints. SIP extension allocation uses the active Odoo cursor and a reviewed row lock; it does not open a separate PostgreSQL connection or expose database credentials.

## Safety

External provisioning and live communication capabilities remain disabled unless their independent authorization, provider and production gates are approved.

## Verification

Run the module tests and `scripts/run_ci.sh`. The source gates validate the exact reviewed tree, manifest, tests, integration boundary and closed production capabilities.

## Authoritative agent assignment

The provisioning form uses Odoo master records as dropdowns. Selecting one campaign derives its business unit, branch, single approved team, supervisor, calling-hours display, and the only active extension pool when those mappings are unambiguous. The hidden legacy campaign collection is synchronized to the selected primary campaign, preventing divergent assignments.

Changing or clearing the campaign clears old team, department, supervisor,
extension-pool, inbound-group, branch, and calling-hours selections before
deriving new values. Ambiguous required assignments must be selected again.
Server-side validation rejects a team or supervisor outside a configured primary
campaign mapping, including another team in the same business unit.

All campaign definitions remain Odoo-first and inactive until separately approved. This feature does not enable VICIdial writes, live call control, PSTN dialing, SMS, email, callbacks, or campaign activation.

## Agent monitoring API

Authenticated provisioning users may call:

`GET /codestra/provisioning/v1/monitoring/agents?campaign=CAMPAIGN-CODE&limit=200`

The response is restricted by Odoo company/business-unit record rules and contains only employee identity, Keycloak and VICIdial usernames, campaign, role, extension, lifecycle state, active status, and reconciliation time. It never returns credentials, tokens, recovery data, or customer records.

Provisioning users need assigned business units; administrator status alone does
not grant those assignments. HR Officer permission is unnecessary: the request
projects only the employee's display name and stable number, identity links use
their provisioning ACL and the request's business unit, and a read-only campaign
catalog grant remains company/unit scoped. No HR or sales role is added.
Campaign filtering runs before the 200-request ceiling and also matches legacy
`campaign_ids` when `primary_campaign_id` is unset. The newest matching onboarding
request per employee is returned, with record ID breaking timestamp ties.

Deployment must separately certify Caddy TLS, the Kong monitoring route policy,
and the authenticated Odoo session. This source change does not prove those
gateway integrations. Redis may cache short-lived results but is never authoritative.
