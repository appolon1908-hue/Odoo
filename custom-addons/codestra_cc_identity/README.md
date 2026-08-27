# Codestra Contact Center Identity

Mission facade over the existing durable provisioning engine for Odoo users and employees, Keycloak identities, VICIdial identities and extensions, campaign membership, skills, supervisor assignments, mailboxes, and lifecycle reconciliation.

The canonical issuer is `auth.codestra.co`. Provisioning is a recorded, idempotent, approved workflow with per-system steps and compensation. This facade performs no network side effect during installation and does not expose credentials.
