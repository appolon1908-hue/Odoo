# `feat/cc-wfm-reporting` close-out

Status: `PARTIAL` / `STAGING-ONLY` / `PRODUCTION_BLOCKED`

Base: `feat/cc-recordings-quality` at
`c46096ecc9694d5bc2faffbe6b9e0bd7a193c39c`

## Implemented

- Added versioned campaign workforce policy with separate author, approval,
  activation, retirement, deterministic hash, and one-active-policy invariant.
- Added interval forecasting with derived staffing, immutable published agent
  schedules, agent acknowledgement, and campaign-scoped adherence evidence.
- Added separate schedule-change, cancellation, and overtime request, primary
  supervisor approval, WFM application, replacement schedule, and evidence
  hashes. The requester cannot approve the same change.
- Added normalized adherence ingestion, exception classification, primary
  supervisor acknowledgement/resolution, and an append-only exception timeline.
- Added privacy-minimized real-time capacity snapshots with ASA, abandon,
  occupancy, staffing variance, backlog, health, and alert classification.
- Added versioned KPI policy and controlled metric catalog, immutable aggregate
  or agent-level snapshots, threshold classification, exact replay handling,
  scoped dashboard views, and manifest-only controlled export evidence.
- Closed the legacy company-only workforce shift UI and ACLs without deleting
  historical records.
- Generated the required 93-row workforce/reporting readiness matrix, including
  schedule-change readiness, without seeding or claiming production policy.

## Validation

- Draft PR [#36](https://github.com/appolon1908-hue/Odoo/pull/36) exact-head and
  stacked merge-result source checks: `PASS`.
- GitHub Actions run
  [33192950718](https://github.com/appolon1908-hue/Odoo/actions/runs/33192950718)
  validated code head `292f035eb3ea637421ddd7af565fecf95fd58d83`.
- 67 manifests reviewed; strict review reported zero errors or warnings.
- Pinned Odoo 19/PostgreSQL runtime: 435 tests, 0 failed, 0 errors;
  `codestra_cc_wfm` contributed 11 counters and `codestra_cc_reporting`
  contributed 7 counters.
- Asset compilation, PostgreSQL schema, fail-closed administrator provisioning,
  administrator state, and installed-module state audits: `PASS`.
- Policy separation, immutable hashes, forecast calculation, schedule isolation,
  overtime approval, direct timeline-forgery denial, adherence idempotency,
  exception ownership, aggregate privacy, KPI thresholds, role scope, and raw
  export denial are covered.

## Unresolved gates

- No campaign has an approved workforce or KPI-reporting policy seed. All 93
  controlled matrix rows remain `PARTIAL`.
- Forecast source data and authoritative external WFM, Middleware, VICIdial, or
  reporting read-back were not supplied and remain `NOT_TESTED`.
- Real-time snapshots and KPI values are governed ingestion contracts; this
  branch does not add an external poller, writer, public controller, or transport.
- Bulk data export remains unavailable. The controlled export workflow returns
  evidence metadata only and no business rows.

## Rollback

Return the stack to `feat/cc-recordings-quality` or restore the disposable
pre-upgrade database. The legacy workforce UI stays available to administrators
for rollback inspection, but is hidden from operational users on this branch.
No schedule, dialer, workforce, reporting, telephony, email, or production
system outside the disposable CI database was changed.

Recommendation: `STAGING-ONLY`

Production gate: `PRODUCTION_BLOCKED`
