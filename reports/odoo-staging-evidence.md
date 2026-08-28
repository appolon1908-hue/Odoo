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
