# Codestra Contact Center Identity

Concrete, fail-closed identity lifecycle for canonical Campaign Workspaces.

The module adds:

- separate submit and approval steps for campaign membership;
- an immutable, deterministic desired-state outbox created in the same Odoo
  transaction as approval;
- required Odoo, Keycloak, email, Middleware, and VICIdial read-back gates;
- server-derived session pinning using only SHA-256 session and OIDC-subject
  hashes;
- per-request membership and campaign `scope_version` validation;
- Odoo device/session revocation using Odoo's existing reviewed `res.device`
  mechanism;
- suspension, expiry, revocation, and security-event deprovisioning envelopes;
- governed revoke-then-grant campaign reassignment;
- optional links to the existing durable `codestra.provisioning.request` engine;
- `/contact-center/agent` and `/contact-center/supervisor` landing routes.

No public method accepts a campaign identifier as authority. Campaign scope is
always derived from the authenticated user's one active operational membership.
Raw session identifiers and OIDC tokens are never stored.

The identity outbox is staging evidence, not a live connector. It exposes no
transport worker and makes no network call. All payloads set production
provisioning and browser campaign selection to false. Middleware/VICIdial,
Keycloak, and mail adapter execution remains disabled until later reviewed
branches and production gates pass.

The controlled 2,677-row disposition catalog is still missing and is unrelated
to this module's bounded identity tests, but remains a release blocker.
