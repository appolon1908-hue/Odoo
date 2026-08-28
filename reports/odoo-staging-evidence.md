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
