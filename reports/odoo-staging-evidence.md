# Odoo contact-center staging evidence

Evidence date: 2026-08-28

Branch: `docs/odoo-contact-center-authority`

Base commit: `6dc403350da71962af28603c0bdf2e73f7f6821e`

## Authority-branch validation

| Check | Result | Status |
| --- | --- | --- |
| Authority source/repository comparison | Equal after newline normalization; source ends mid-sentence | PARTIAL |
| Embedded canonical/native pairs | 93 parsed; 93 present in CSV; 0 missing; 0 extra | PASS |
| Identifier uniqueness | 93 unique canonical codes and 93 unique native IDs | PASS |
| VICIdial native identifier length | Maximum eight characters | PASS |
| Callback compatibility policy | Eight callback-out rows; all eight have agent login false | PASS |
| Access-control catalog | Ten roles transcribed from section 6 | PASS |
| Target module architecture | 38 rows: 17 foundation, 13 profile, 8 overlay | PASS |
| Controlled disposition catalog | Referenced 2,677-row source is unavailable | BLOCKED |
| Git whitespace validation | `git diff --cached --check` passed | PASS |
| Full source validation (`scripts/run_ci.sh`) | 59 manifests; 0 review errors/warnings; integration, security, API, migration, evidence, and release source gates passed; 3 source contract tests passed | PASS |
| Runtime certification for new authority | No implementation exists on this documentation branch | NOT_TESTED |
| External middleware/VICIdial/n8n read-back | No staging endpoint is configured; no external mutation attempted | BLOCKED |

The initial `bash` command resolved to WSL, which is not installed. The same
repository wrapper was then run successfully with
`C:\Program Files\Git\bin\bash.exe`. No production or external system was touched.

## Retained prior-base evidence

The base commit previously completed a local Odoo 19/PostgreSQL suite across 59
custom modules with 339 tests passed and zero failures/errors. That evidence
supports base compatibility only; it does not certify the new architecture,
membership isolation, or external integrations.

Recommendation: `STAGING-ONLY`

Production gate: `PRODUCTION_BLOCKED`

## Core-domain branch evidence

Branch: `feat/cc-core-domain`

| Check | Result | Status |
| --- | --- | --- |
| Focused Odoo 19 upgrade | 8 test methods; 0 failed; 0 errors | PASS |
| Upgrade adoption read-back | 13/13 units; 112/112 campaigns; 102/102 channels; zero duplicate links | PASS |
| Clean 59-module Odoo 19 install/regression | 346 tests; 0 failed; 0 errors | PASS |
| Clean-install adoption read-back | 13/13 units; 111/111 campaigns; 102/102 channels | PASS |
| Production/live state | 0 live-enabled; 0 production-eligible; 0 active workspaces | PASS |
| Callback compatibility | 8 mappings; 0 login-enabled; 0 active | PASS |
| Canonical membership/record rules | Owned by the next stacked branches | NOT_TESTED |

The first two disposable upgrade attempts exposed an invalid related-field path
and two legacy synthetic identifiers outside the canonical format. The field path
was corrected. `MIGRATION_FIXTURE` and `TEST_SYN` are now preserved without rename
as disabled, blocked legacy exceptions. The final upgrade and clean-install runs
are green.

## Campaign-security branch evidence

Branch: `feat/cc-campaign-security`

| Check | Result | Status |
| --- | --- | --- |
| Focused Odoo 19 upgrade | 12 methods / 14 counters; 0 failed; 0 errors | PASS |
| Clean 60-module Odoo 19 install/regression | 358 tests; 0 failed; 0 errors | PASS |
| Stable authority roles | Ten role groups plus one reusable scoped base group | PASS |
| Database invariants | Four membership partial unique indexes plus one break-glass partial unique index | PASS |
| Global canonical rules | Six fail-closed rules installed | PASS |
| Agent campaign isolation | Search, direct ID, name search, grouped reporting, export, copy, create, and write covered | PASS |
| Membership visibility | Agent self-only; supervisor campaign-only; cross-campaign record hidden | PASS |
| Supervisor invariant | One active campaign per supervisor and one active primary supervisor per campaign | PASS |
| Technical administrator | Zero canonical campaign visibility without break-glass; separate approval and revocation covered | PASS |
| Production/live state | 0 live-enabled; 0 production-eligible; 0 active workspaces | PASS |
| Callback compatibility | 8 mappings; 0 login-enabled; 0 active | PASS |

The clean database contained 13 canonical business units, 111 canonical
campaigns, and 102 canonical channels. Transactional security fixtures rolled
back cleanly, leaving zero memberships and zero break-glass grants. The clean
run included the calendar, reminder, and scheduler pop-out browser tour.

The module intentionally does not add OIDC, session pinning, external account
provisioning, or automatic session revocation; those remain owned by the next
stacked identity branch. Status remains `STAGING-ONLY` and
`PRODUCTION_BLOCKED`.

## Identity-membership branch evidence

Branch: `feat/cc-identity-membership`

| Check | Result | Status |
| --- | --- | --- |
| Focused identity upgrade | 9 methods / 13 counters; 0 failed; 0 errors | PASS |
| Campaign-security regression | 12 methods / 14 counters; 0 failed; 0 errors | PASS |
| Clean 60-module Odoo 19 install/regression | 366 tests; 0 failed; 0 errors | PASS |
| Governed identity lifecycle | Separate submit/approval, immutable desired-state envelope, exact read-back, and activation gate | PASS |
| Session authority | SHA-256-only server session/OIDC binding to one membership, campaign, and scope version | PASS |
| Revocation lifecycle | Suspension, expiry, revocation, device revocation, and revoke-then-grant reassignment covered | PASS |
| Authenticated route | Forged `campaign_id=999999` ignored; server-derived agent landing returned 303 | PASS |
| Identity schema | 3 identity tables; 3 global identity rules; 52 membership/identity indexes | PASS |
| Clean database ownership | 13 units; 111 campaigns; 102 channels | PASS |
| Clean database identity state | 0 memberships, outbox rows, session scopes, reassignments, or active membership after rollback | PASS |
| Production identity state | 0 production-enabled envelopes; no external transport or network action | PASS |
| Calendar/reminder/scheduler browser tour | Included in the 366-test clean run | PASS |

The full run loaded 138 Odoo modules, including all 60 workspace modules. The
identity module installed as version `19.0.2.0.0`. Authenticated operational
requests are checked globally and fail closed if their server-pinned membership
or campaign scope no longer matches.

The desired-state outbox deliberately has no transport worker. Keycloak, mail,
Middleware, VICIdial, and external OIDC read-back remain `NOT_TESTED` until
reviewed staging endpoints exist. Status remains `STAGING-ONLY` and
`PRODUCTION_BLOCKED`.

## Campaign-mail branch evidence

Branch: `feat/cc-campaign-mail`

| Check | Result | Status |
| --- | --- | --- |
| Focused mail upgrade | 11 methods / 13 counters; 0 failed; 0 errors | PASS |
| Legacy campaign/CRM/lead/telephony regression | 144 tests; 0 failed; 0 errors | PASS |
| Clean 61-module Odoo 19 install/regression | 377 tests; 0 failed; 0 errors | PASS |
| Campaign isolation | Alias routing, threads, chatter, followers, activities, attachments, query surfaces, and cross-thread quarantine covered | PASS |
| Clean database ownership | 13 units; 111 campaigns; 102 channels | PASS |
| Clean database mail state | 0 routes, sender identities, groups, memberships, threads, inbound events, or quarantine rows after rollback | PASS |
| Mail schema | 7 mail tables; 72 mail-table indexes; 11 module-owned global rules | PASS |
| Email safety defaults | Both named global flags false; 0 model live switches enabled | PASS |
| Authority alias catalog | 93 rows; 93 alias keys missing; 0 routes provisioned | BLOCKED |
| External mail/provider read-back | No reviewed staging endpoint or transport configured; no external mutation attempted | NOT_TESTED |

The module installed as version `19.0.1.0.0`; the dependent mailbox facade
installed as `19.0.1.1.0`. It contains no public inbound controller or transport
worker. Status remains `STAGING-ONLY` and `PRODUCTION_BLOCKED`.

## CRM and Helpdesk workspace branch evidence

Branch: `feat/cc-crm-helpdesk-workspaces`

| Check | Result | Status |
| --- | --- | --- |
| Focused CRM/Helpdesk/legacy-CRM compatibility | Odoo aggregate 41 tests; CRM 7 counters, Helpdesk 8 counters, legacy CRM OS 34 counters; 0 failed; 0 errors | PASS |
| Clean 63-module Odoo 19 install/regression | 388 tests; 0 failed; 0 errors | PASS |
| Source validation | 63 manifests; strict review 0 errors/warnings; all source gates; 3 contract tests | PASS |
| Campaign CRM isolation | Customer profiles and leads cover search, direct ID, name search, grouped queries, copy, export, create, write, chatter, activities, and attachments | PASS |
| Helpdesk isolation and workflow | Queue, approved SLA, ticket scope, deadlines, breach, escalation, resolution, direct ID, grouped queries, chatter, activities, and attachments | PASS |
| Clean database ownership | 13 units; 111 campaigns; 102 channels | PASS |
| Clean CRM/Helpdesk state | 0 customer profiles, queues, SLA policies, or tickets after transactional rollback | PASS |
| CRM/Helpdesk schema | 4 tables; 67 indexes; 12 module-owned rules | PASS |
| Enterprise Helpdesk | `helpdesk.ticket` table/module absent; canonical Community substitute installed | NOT_TESTED |
| External ticket/provider integration | No reviewed staging endpoint or transport configured; no external mutation attempted | NOT_TESTED |
| Calendar/reminder/scheduler browser tour | Headless Chrome reported `test successful` in the clean 388-test run | PASS |

The CRM module composes the existing campaign CRM operating system and adapts
both of its legacy global lead rules to canonical membership-derived scope. The
Customer 360 and agent-desktop facades now depend on the canonical CRM and
Helpdesk owners instead of maintaining parallel data. Both modules install as
`19.0.1.0.0`; the two facades install as `19.0.1.1.0`.

The installed Community runtime has no Enterprise Helpdesk dependency. The
branch therefore does not claim an Enterprise extension was tested and does not
create external tickets. Status remains `STAGING-ONLY` and
`PRODUCTION_BLOCKED`.

## VICIdial canonical-mapping branch evidence

Branch: `feat/cc-vicidial-mapping`

Draft PR: [#32](https://github.com/appolon1908-hue/Odoo/pull/32)

| Check | Result | Status |
| --- | --- | --- |
| Exact-head and stacked merge source validation | 63 manifests; strict review 0 errors/warnings; all source gates; 3 contract tests | PASS |
| Clean Odoo 19/PostgreSQL install/regression | 397 tests; 0 failed; 0 errors | PASS |
| Focused VICIdial boundary suite | 10 methods / 12 Odoo counters | PASS |
| Controlled identifiers | 93 canonical codes; 93 unique native IDs; maximum 8 characters | PASS |
| Legacy comparison | 93 identifier drifts; 8 unmanaged legacy mappings; no automatic rename or overwrite | PARTIAL |
| Callback compatibility | 8 mappings; 0 agent-login enabled | PASS |
| Missing optional native catalog | 558 of 558 values absent | BLOCKED |
| Desired/live state | 0 mapping, provisioning, agent-sync, or live-control flags enabled | PASS |
| Read-back contract | Exact replay idempotent; altered replay rejected; evidence append-only | PASS |
| Campaign authorization | Search, direct ID, name search, grouped reporting, export, copy, create, and write covered | PASS |
| Runtime operations | PostgreSQL schema and fail-closed administrator provisioning audits | PASS |
| Calendar/reminder/scheduler browser tour | Skipped in GitHub image because optional `websocket-client` is absent; successful unchanged-base evidence retained above | NOT_TESTED |
| External middleware/VICIdial/Asterisk/n8n read-back | No reviewed isolated staging endpoint; no external mutation attempted | NOT_TESTED |

`codestra_cc_vicidial` is now a concrete middleware-only mapping boundary rather
than a dependency facade. It owns two canonical models, read-only views,
campaign-global record rules, restricted exports, four false global flags, and a
checksum-pinned catalog copy. Existing signed API, agent desired-state, call,
recording, and legacy campaign-mapping owners remain unchanged.

Every controlled row is still `PARTIAL` and `blocked_partial_catalog`. No direct
Odoo/VICIdial database or browser write, campaign provisioning, agent sync, live
call control, carrier action, or PSTN call occurred.

Recommendation: `STAGING-ONLY`

Production gate: `PRODUCTION_BLOCKED`
