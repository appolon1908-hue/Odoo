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

## Runtime verification

Draft PR [#32](https://github.com/appolon1908-hue/Odoo/pull/32) ran the exact
branch head and stacked merge-result source validations successfully. Its pinned
Odoo 19/PostgreSQL runtime installed all 63 custom modules and completed 397
tests with zero failures or errors. The PostgreSQL schema audit and fail-closed
administrator provisioning audit also passed.

The `codestra_cc_vicidial` suite contributed 10 test methods / 12 Odoo test
counters covering the catalog, collision rejection, disabled desired state,
immutable identity, cross-campaign query isolation, exact replay, altered replay,
append-only evidence, unsafe evidence rejection, and global false flags.

The unchanged calendar/reminder/scheduler browser tour was skipped in this
GitHub image because the optional Python `websocket-client` package is absent.
Its successful browser execution is retained on the immediately preceding
CRM/helpdesk base branch; this branch adds no appointment or browser assets.

## Gate

The authority supplies none of the 558 required user-group, inbound-group, list,
script, disposition-set, and email-alias values. Every controlled row therefore
remains `PARTIAL` and `blocked_partial_catalog` with desired state `disabled`.

External middleware, VICIdial, Asterisk, n8n, carrier, and PSTN execution was not
attempted because no reviewed isolated staging endpoint was supplied.

Recommendation: `STAGING-ONLY`

Production gate: `PRODUCTION_BLOCKED`

## Scripts and dispositions boundary

The scripts/dispositions branch adds no external writer. `cc.script.version`
delegates content ownership to the compatible legacy script record while adding
immutable approval and acknowledgement evidence. Agent rendering derives its
campaign from the active server membership, returns only the approved version,
and omits internal prohibited-language and supervisor-note fields.

The controlled disposition catalog remains absent. The generated reconciliation
matrices contain 93 campaign rows: every external script ID is `MISSING`, every
external read-back is `NOT_TESTED`, and every disposition approval is `BLOCKED`.
Zero disposition catalog rows were imported. The schema rejects native status
codes longer than six characters and cross-campaign legacy/channel adoption, but
it cannot claim catalog reconciliation without the original 2,677-row source.

No Middleware, VICIdial, Asterisk, n8n, carrier, PSTN, or production operation was
attempted.
