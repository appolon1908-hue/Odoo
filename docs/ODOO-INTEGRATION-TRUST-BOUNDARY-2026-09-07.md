# Odoo integration trust-boundary continuation — 2026-09-07

Related issues: #75, #73, #63, #56. This is a source repair, not a production certificate.

## Reviewed source baseline

- Odoo: `a7a9364925c7182098cbda234f3fddc13c594c71`, current `main` when this work started.
- SDK authority repair #109 is merged as `17313e760acfbce44ddd08c29da0869782976cb4`; the September 6 issue checkpoint saying it is still open is stale.
- Odoo still reports public visibility. No private upstream source was fetched or copied.

## Implemented repair

`codestra.telephony.middleware.client.originate_call` previously exposed a public
Odoo RPC method which reads the service credential with `sudo()` and accepts an
arbitrary payload. The governed lead action must remain the browser entrypoint.
The transport is now decorated with Odoo 19 `@api.private`, preserving the Python
method name and the existing committed-reservation dispatcher while rejecting
RPC access, including RPC calls made as an administrator.

Before transport, reject malformed/control-bearing URLs and headers, invalid
ports, non-object or non-JSON payloads, conflicting body/header idempotency,
non-finite request numbers, and request bodies above 128 KiB. No target is changed
and no activation flag is enabled.

After transport, reject duplicate JSON keys (including nested/escaped keys),
non-finite numbers including exponent overflow, excessive JSON nesting,
malformed UTF-8, oversized bodies, malformed call identities, and a supplied
correlation/idempotency identity belonging to another request. Such replies raise
`OriginateOutcomeUnknown`, not `OriginateRejected`, so the existing dispatcher
keeps the reservation reconcilable rather than treating an ambiguous result as
proof of no call. Existing timeout, redirect-denial, and HTTP-error classifications
remain in place. No automatic request retry was added.

## Validation and integration

`tests/security/test_telephony_transport.py` contains 24 offline tests against the
actual transport source, with Odoo model/decorator shims and in-memory HTTP
responses. They passed locally. These shims do not prove Odoo RPC or ORM behavior.
The existing `scripts/run_isolated_source_tests.py` automatically discovers them;
no workflow gate is weakened or skipped.

`custom-addons/codestra_vicidial_crm/tests/test_telephony_trust_boundary.py` adds six
Odoo runtime tests and is imported by the addon test package. It exercises the
real `odoo.service.model.call_kw` privacy check, preserves the lead action's RPC
entrypoint, and verifies internal dispatch, acknowledgement identity, ambiguous
response handling, and pre-transport rejection. These tests require the existing
Odoo 19/PostgreSQL CI job; local source tests are not their result.

## Remaining issue disposition

- **#75:** This repair does not implement the generated SDK canonical command
  adapter or dedicated WebSocket ticket/session/ordered-event workspace. Keep
  those source milestones explicit, followed by exact cross-service staging and
  controlled-canary evidence. SDK #109 being merged does not certify an SDK
  package or a deployed Odoo integration.
- **#73:** Tenant/identity/campaign negative tests, command/result/read-back,
  callback replay, and deployment-specific restoration must pass through the
  actual Caddy/Kong/Keycloak/Middleware/Odoo chain. The legacy database-backed
  `codestra.middleware.api_key` configuration is unchanged; migration to governed
  secret references remains part of the canonical client work.
- **#63:** No immutable image was published, no release SHA was selected, and no
  protected environment was verified or dispatched. Staging, paired database /
  filestore restore, rollback, read-only canary/soak, and independent activation
  remain required. `PRODUCTION_CERTIFIED=NO`.
- **#56:** The private importer must remain blocked while the destination is
  public. Visibility/access audit, source-copy authorization, protected sync
  environment, separate scoped source/destination credentials, reviewed plan,
  and an exact-source import PR are still required. No confidentiality gate was
  bypassed.

## Safety and rollback

No server connection, database migration, deployment, outbound email/SMS, call,
provider write, or live-effect enablement was performed. Existing activation
switches remain unchanged. Source rollback is a protected revert of this change;
there is no schema migration to reverse. Do not revert the RPC privacy restriction
merely to make an ungoverned caller work; route that caller through the authorized
lead/reservation workflow instead.

## References

- https://github.com/appolon1908-hue/Odoo/issues/75
- https://github.com/appolon1908-hue/Odoo/issues/73
- https://github.com/appolon1908-hue/Odoo/issues/63
- https://github.com/appolon1908-hue/Odoo/issues/56
- https://github.com/appolon1908-hue/SDK-repository/pull/109
- https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html
- https://www.odoo.com/documentation/19.0/developer/reference/backend/security.html
