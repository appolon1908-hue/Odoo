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
