# Codestra Contact Center VICIdial Boundary

This module owns the canonical Odoo-to-VICIdial campaign mapping boundary. It
adopts the 93 controlled canonical/native identifier pairs without changing the
legacy records or inventing any missing native configuration.

## Implemented

- `cc.telephony.mapping`: one immutable, deterministic mapping for every row in
  the checksum-pinned controlled catalog.
- `cc.telephony.middleware.contract`: a narrow desired-state/read-back adapter
  contract for the authenticated Codestra middleware. It contains no network or
  VICIdial database client.
- `cc.telephony.readback`: append-only, exactly-once retained evidence. Altered
  event replay is rejected and raw payloads or credentials are never stored.
- Global campaign record rules, read-only configuration views, restricted
  export, and adversarial cross-campaign tests.

The legacy `call.center.campaign.mapping`, existing signed integration APIs,
agent desired state, call events, and recording implementation remain owned by
their existing modules. This module does not create a second dialer or call
history.

## Fail-closed status

The supplied authority marks every row `PARTIAL` and omits user group, inbound
group, list, script, disposition, and email-alias identifiers. Therefore all 93
mappings are `blocked_partial_catalog`; none is provisioning-ready. The eight
`*-CALLBACK-OUT` compatibility mappings remain disabled with agent login denied.

These parameters are installed as `false` and are not an activation mechanism:

- `CC_ENABLE_CAMPAIGN_PROVISIONING`
- `CC_ENABLE_AGENT_SYNC`
- `CC_ENABLE_VICIDIAL_WRITES`
- `CC_ENABLE_LIVE_CALL_CONTROL`

No Odoo/VICIdial direct database write, browser automation, provider mutation,
PSTN dialing, agent sync, campaign provisioning, or production activation is
performed by this module. Promotion requires the missing authoritative values,
an approved identifier migration, restricted middleware adapter execution,
read-back, reconciliation, rollback evidence, and synthetic staging acceptance.
