# Calling workspace integration — issue #75

This source change adds Odoo's canonical **read side**. It does not complete the
calling mission or enable a production campaign. The command path from PR #91
and campaign repair from PR #95 are already on protected main; this change is
based on `630e616` (including the CRM login entry fix in PR #100).

## Ownership and compatibility

| Responsibility | Existing owner | This change |
| --- | --- | --- |
| Campaign identity, design, revisions, approval/outbox | `call_center_campaign` | Reads current authorized membership and business unit; preserves existing producer/approval behavior |
| Employee/user identity, governed onboarding | `codestra_identity_provisioning`, `call_center_core` | Requires the active user, unique agent, and one intersecting campaign assignment |
| Agent/call records, timeline, dispositions, callbacks, recordings | `codestra_vicidial_crm` | Adds a read-only, user/tenant/campaign-bound recovery queue; preserves legacy fields and call records |
| Keycloak code/PKCE login | `codestra_orbit_theme` | Adds opt-in calling scopes and an expiring, user/subject-bound credential in the server-side session |
| REST session/status transport | `codestra_vicidial_crm.models.calling_realtime` | Bounded HTTPS, exact public authority paths, no redirects, no proxy inheritance, no retry, strict generated schemas |
| Browser events and screen pops | `codestra_vicidial_crm` | Dedicated ticket client, scope/sequence/duplicate checks, persisted-projection readback, bounded reconnect |
| Commands, tickets, operation/CDR authority | Middleware | Must validate the user's issuer/audience/scopes/session/current assignments; this change supplies no service-account substitute |
| Ticket consumption, ordered event delivery and revocation | `Websocket-` | A matching gateway release is still required |
| TLS/WSS, request policy | Caddy and Kong | Exact canonical hosts; certified staging/production routes and redaction remain required |

The full module inventory remains in `config/call-center-module-coverage.json`
and `config/call-center-workstreams.json`. No legacy fields/models are removed.
Legacy call-event ingestion and Odoo Bus remain the current production path.
Selecting the canonical mode suppresses Bus-driven screen pops, including when
its contract gates fail. It does not silently downgrade after a canonical error.

## New path

1. The explicit calling mode adds `realtime:session:create` and
   `telephony:status` to the existing Keycloak code/PKCE login request.
2. Odoo retains a bounded, expiring user token in its **server-side session**.
   This change never reads the existing database OAuth token as a fallback,
   creates no new credential field, and returns no access/refresh token.
   Existing `auth_oauth` credential persistence remains separate migration debt.
3. Same-origin authenticated BFF routes derive identity from Odoo assignments.
   The browser cannot supply a tenant, campaign, agent, role, token, or endpoint
   to ticket creation. Middleware must derive and authorize ticket claims again.
4. Odoo posts the campaign selection and resume cursor to the canonical session
   endpoint. The response must contain the pinned digest, exact WSS URL, and a
   ticket expiring within 60 seconds. Old `ws_url` responses are rejected.
5. The socket sends its ticket once in the initial auth frame. The proposed
   canonical gateway must then emit `realtime.connected.v1`. The deployed legacy
   `authenticated` control frame is deliberately rejected. Coordinating this
   first-frame handoff with the gateway is a remaining release requirement;
   the current platform contract does not fully specify that wire handshake.
6. Scope must match tenant, business unit, campaign, agent and Odoo user.
   Event sequence is tracked per operation; stream cursors can legitimately
   skip other agents' events. Identical committed duplicates are suppressed.
   A gap, regression or identity conflict freezes advancement immediately.
7. A screen pop reads an existing Middleware-projected Odoo call whose
   correlation, Asterisk ID, scope, event ID and sequence all agree. Browser
   events never write an authoritative CRM state or inject a lead reference.
8. Recovery requests survive unavailable operation reads. An observed operation
   remains marked as requiring CDR reconciliation; it never releases an
   ambiguous originate reservation or enables another call. Control-level gaps
   create a scoped `stream` recovery entry for operator reconciliation.

The client uses no browser token/ticket/cursor storage. Cursor state lasts for
this page session; a reload or a late join into a call requires reconciliation
when the first observed operation sequence is not 1. Reconnect delays are
1, 2, 4, 8, 15 and 30 seconds, with six attempts per outage. Queues, operations
and deduplication history have explicit limits. Logout/unmount cancels timers
and ignores pending ticket responses. Gateway-side revocation remains mandatory.

Agent-status notifications are acknowledged after scope validation without a
call lookup or synthesized state; they do not stop subsequent call events.

Agent-state commands, transfers, dispositions and authoritative CDR ingestion
are not added by this read-side slice. The canonical view keeps live controls
disabled. Existing call-control and callback policies remain authoritative.

## Contract generation and verification

`python3 scripts/generate_calling_client_schema.py` derives runtime schemas from
the pinned OpenAPI/AsyncAPI components (authoring requires PyYAML). Do not edit
the Python JSON or browser schema by hand. The source gate's stdlib-only
`--check` binds the reviewed generator, authority digest and both runtime copies
through `.codestra/calling-client-schema.lock.json`; it does not claim to run
an OpenAPI SDK generator. Local regeneration and transport/browser behavior are
also verified during this change. A distributable canonical calling SDK is still
required from `SDK-repository`.

## System integration and migration

The reviewed opt-in overlay is
`deploy/compose/compose.calling-realtime.integration.yaml`. Its default is off.
Do not set the three component digest assertions merely to make them equal:
collect their real source/artifact/runtime evidence first. Each must be
`b39cdffe56a8185c91174228f0423df68b1137f34875f6ee52f9914f904bf724` for this
Odoo candidate. A different authority requires coordinated regeneration/review.

After protected merge and source-scope convergence, build one signed immutable
candidate including both modified addons. Rehearse upgrade from the paired
production database/filestore backup in an isolated network with all scheduled
external delivery disabled. Upgrade `codestra_vicidial_crm` to `19.0.3.5.0` and
`codestra_orbit_theme` to `19.0.1.3.0`; Odoo creates the recovery table/ACL/rule.
There is no legacy data rewrite or deletion. Preserve the current module order
and complete mount set. Do not hot-copy files into the running addon tree.

The unchanged canonical HTTPS/WSS hosts require isolated routing and valid TLS
for staging. An isolated certification must prove the actual user-token ticket
flow, one-use/revoked/wrong-origin negatives, callback projection, cursor replay,
CDR reconciliation and paired restore. Production promotion must reuse that
exact digest. Rollback restores the matching database and filestore pair plus
the prior image, addon mounts and configuration; do not drop audit tables alone.

## Observed release blockers — 2026-09-10

- Odoo and Middleware pin `b39cdffe…`; SDK-repository pins `e5ea6ddc…` after
  documented local OpenAPI/AsyncAPI corrections. Its generation script produces
  public/control-plane clients, not a canonical calling client. These are
  different bytes and must not be represented as a matching shared SDK digest.
- The current Websocket- source and deployed gateway use the legacy
  `ws_url` / `authenticated` / `last_event_id` protocol and noncanonical events.
  Gateway image revision read-back: `9118e5bc01f9ce4a52add8753c096d061cd84848`.
- Production Odoo uses base image
  `sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5`
  with calling addons mounted from release `91e22ef4e69e624142bb3865b16c43a14e8b69d6`.
  No calling/OIDC integration environment variables were present in that
  container. The newer login-only mount does not establish calling deployment.
- Public API `/healthz` and `/readyz` returned 200, but `/version` returned 404.
  Health alone cannot prove exact calling runtime source/contract identity.
- The committed login-deployment record reports that its additional Restic copy
  returned Access Denied. No fresh off-host calling backup/restore certification
  was performed in this change.
- Exact Middleware/gateway/SDK convergence, Keycloak audience/scope/session
  certification, immutable staging identities, canonical persisted projection,
  CDR mapping, paired restore/rollback, and a separately bounded canary are still
  required. No production calling activation or call was performed here.

`ODOO_NO_GO_WITH_EXACT_BLOCKERS`. Keep #75 open.
