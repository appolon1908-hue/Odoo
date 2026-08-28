# Odoo/VICIdial integration reconciliation

Evidence date: 2026-08-28

Branch: `feat/cc-vicidial-mapping`

## Result

The controlled authority contains 93 unique canonical campaign codes and 93
unique VICIdial campaign IDs. All native IDs satisfy the eight-character native
limit. Odoo now owns one immutable `cc.telephony.mapping` desired-state record
for each controlled pair without changing any legacy mapping.

| Check | Count | Status |
| --- | ---: | --- |
| Controlled catalog rows | 93 | PASS |
| Unique canonical campaign codes | 93 | PASS |
| Unique VICIdial campaign IDs | 93 | PASS |
| IDs longer than eight characters | 0 | PASS |
| Technical callback compatibility rows | 8 | PASS |
| Callback rows allowing agent login | 0 | PASS |
| Optional native values supplied | 0 of 558 | BLOCKED |
| Legacy identifiers equal controlled identifiers | 0 | DRIFT |
| Legacy identifier drifts | 93 | PARTIAL |
| Unmanaged legacy mapping rows | 8 | PARTIAL |
| Desired/provisioning/agent-sync/live-control mappings enabled | 0 | PASS |
| Authoritative external VICIdial read-back | 0 | NOT_TESTED |

`MATCH`, `DRIFT`, `MISSING`, and `CONFLICT` are explicit classifications. The
loader refuses collision, schema, row-count, checksum, direction, business-unit,
callback, or agent-login disagreement. It never truncates, renames, or overwrites
the existing hash-like native identifiers.

## Middleware contract

The model contract returns a hash-bound disabled desired-state document and
accepts only a bounded read-back schema. Read-back is exactly once by event ID,
rejects altered replay, stores hashes and a safe evidence reference rather than
raw payloads, and can report `match`, `drift`, `missing`, or `conflict`. It cannot
enable provisioning or live call control.

There is no direct Odoo-to-VICIdial database client, browser writer, or new
unauthenticated route. Existing signed integration APIs and telephony projection
owners remain unchanged. The restricted middleware is the only permitted future
adapter boundary.

## Gate

The authority supplies none of the 558 required user-group, inbound-group, list,
script, disposition-set, and email-alias values. Every controlled row therefore
remains `PARTIAL` and `blocked_partial_catalog` with desired state `disabled`.

External middleware, VICIdial, Asterisk, n8n, carrier, and PSTN execution was not
attempted because no reviewed isolated staging endpoint was supplied.

Recommendation: `STAGING-ONLY`

Production gate: `PRODUCTION_BLOCKED`
