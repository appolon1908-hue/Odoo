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

Draft PR [#33](https://github.com/appolon1908-hue/Odoo/pull/33) completed its
exact-head and stacked merge-result source checks. The pinned Odoo 19/PostgreSQL
runtime installed all 63 custom modules and passed 404 tests with zero failures
or errors; `codestra_cc_disposition` contributed 10 focused test counters. The
PostgreSQL schema and fail-closed administrator audits also passed.

## Callback, transfer, and referral boundary

Draft PR [#34](https://github.com/appolon1908-hue/Odoo/pull/34) adds an immutable
held operation outbox. It deliberately has no transport worker. Callback and
transfer payloads derive the campaign from the authenticated Odoo membership;
browser-supplied cross-campaign scope is rejected.

The 93-row callback matrix has zero publication-enabled rows. All callback
policies are `MISSING`, external read-back is `NOT_TESTED`, and every overall
row is `PARTIAL`. The eight `*-CALLBACK-OUT` identifiers remain disabled
technical compatibility mappings and are not user-login queues.

The positive same-campaign transfer produces one held validation event. A
cross-campaign live-transfer request produces a safe rejection and no outbox
command. Cross-campaign referrals use a separate asynchronous flow: the source
stores consent and payload hashes, the privileged service creates one
minimum-data destination record, and the source user cannot read the destination
campaign or destination record.

The exact branch runtime installed all 64 custom modules and passed 412 tests
with zero failures or errors; `codestra_cc_calls` contributed 10 focused
counters. No Middleware, VICIdial, Asterisk, carrier, PSTN, n8n, or production
operation was attempted.

## Recording and quality boundary

Draft PR [#35](https://github.com/appolon1908-hue/Odoo/pull/35) adds a canonical
recording metadata binding and campaign quality workflow without adding an
external transport or public route. The legacy recording owner remains the raw
source; Odoo retains only controlled identifiers, checksums, protected
storage-reference hashes, policy hashes, and append-only evidence.

The 93-row recording matrix has zero playback-enabled rows, zero externally
reconciled storage rows, and 93 missing campaign policy seeds. The 93-row
quality matrix has zero AI-enabled rows and 93 missing program/scorecard seeds.
Every row in both reports remains `PARTIAL`.

The runtime installed all 65 custom modules and passed 421 tests with zero
failures or errors. The focused tests verify exact recording binding,
campaign-scoped access, immutable evidence, purpose-bound legal holds, weighted
scorecards, critical failures, separate finalization, superseding corrections,
calibration, disputes, and coaching. They also verify that internal capability
objects are removed before governed records return to callers.

No recording object was downloaded, copied, deleted, played, or exposed through
a signed URL. No AI, Middleware, VICIdial, Asterisk, carrier, PSTN, n8n, or
production operation was attempted.

## Workforce and reporting boundary

Draft PR [#36](https://github.com/appolon1908-hue/Odoo/pull/36) adds governed
workforce and reporting models without adding an external adapter, poller,
writer, public route, or transport. The private service accepts normalized,
source-hashed adherence, real-time, and KPI events; exact replay returns the
existing record and altered replay is rejected.

Published schedules bind the approved workforce-policy hash and agent identity.
Schedule changes, cancellations, and overtime bind the original schedule hash,
require a separate primary-supervisor decision, and may be applied only by WFM.
The original schedule is retained as cancelled evidence and a replacement is
published where applicable.

The 93-row workforce/reporting matrix has no approved campaign policy seeds and
no external read-back. Schedule, schedule-change, adherence, exception, and
aggregate snapshot contracts are `STAGING_READY`; campaign policy and external
source reconciliation gates remain `MISSING` or `NOT_TESTED`, so every row is
`PARTIAL`.

Run
[33192950718](https://github.com/appolon1908-hue/Odoo/actions/runs/33192950718)
installed all 67 modules and passed 435 Odoo tests with zero failures or errors.
No external WFM, Middleware, VICIdial, Asterisk, reporting, email, carrier,
PSTN, n8n, or production operation was attempted.
