# `feat/cc-callback-transfer` close-out

Status: `PARTIAL` / `STAGING-ONLY` / `PRODUCTION_BLOCKED`

Base: `feat/cc-scripts-dispositions` at
`789998ae32c26f005d63b3d84cb2c32304c8da64`

## Implemented

- Added the concrete `codestra_cc_calls` campaign operations layer for callback
  policies, callbacks, immutable callback history, appointments, and reminders.
- Added same-campaign transfer routes and validation evidence. Cross-campaign
  live-transfer requests return a non-sensitive rejection and never produce a
  transfer command.
- Added controlled asynchronous referrals with explicit consent evidence,
  allowed-field enforcement, a minimum-data destination record, exactly-once
  materialization, and source-side non-sensitive status only.
- Added immutable held operation-outbox evidence and privileged, idempotent
  read-back actions without a network writer or public controller.
- Replaced the calendar, reminder, and scheduler systray placeholders with
  canonical pop-outs while preserving the existing click-to-call pop-up.
- Installed `CC_ENABLE_CALLBACK_PUBLICATION=false` and
  `CC_ENABLE_WARM_TRANSFER=false` as fail-closed global defaults.
- Generated the required 93-row callback readiness matrix.

## Validation

- Draft PR [#34](https://github.com/appolon1908-hue/Odoo/pull/34) exact-head and
  stacked merge-result source checks: `PASS`.
- 64 manifests reviewed; strict review reported zero errors or warnings.
- Pinned Odoo 19/PostgreSQL runtime: 412 tests, 0 failed, 0 errors;
  `codestra_cc_calls` contributed 10 focused counters.
- Callback scheduling, local-time/calling-hours validation, idempotent read-back,
  missed-callback recovery, appointment preparation, same-campaign transfer,
  cross-campaign rejection, transfer result replay, referral minimization,
  destination isolation, and canonical pop-out asset contracts are covered.
- PostgreSQL schema and fail-closed administrator state audits: `PASS`.

## Unresolved gates

- No campaign has an approved callback policy seed or reviewed external
  Middleware/VICIdial staging endpoint. Publication and authoritative external
  read-back remain `NOT_TESTED`.
- All 93 callback matrix rows are therefore `PARTIAL`; publication is false on
  every row and no technical callback campaign is treated as a staffed queue.
- The optional browser-tour dependency is absent in the GitHub runtime, so the
  new pop-out contract is source-tested here. Successful execution of the
  unchanged legacy calendar/reminder/scheduler browser tour is retained on the
  preceding CRM/helpdesk branch.

## Rollback

Return the stack to `feat/cc-scripts-dispositions` or restore the disposable
pre-upgrade database. No external callback, transfer, referral, PSTN, or
production operation was performed.
