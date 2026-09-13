# Codestra Prometheus Metrics

A single read-only `GET /codestra/metrics` endpoint in Prometheus text-exposition
format, so `appolon1908-hue/Codestra-Prometheus` can scrape Odoo the same
way it already scrapes Kong and Middleware.

**Note**: `call_center_campaign` (a canonical-baseline-governed addon) already
serves a thinner `GET /metrics` (`codestra_odoo_outbox_pending`,
`codestra_odoo_result_inbox_total`). This addon does not replace or conflict
with that route - it adds the health/readiness/backlog/error signals that
route doesn't cover, at a separate path, because extending a governed
addon's own file requires bumping `config/canonical-addon-baseline.json`,
which is outside this addon's scope. Prometheus should eventually scrape
both, or the two should be consolidated by whoever owns that governed
addon's review process.

## Role boundary (matches `appolon1908-hue/Caddy`'s
`config/observability-exposure.v1.json`)

- Prometheus scrapes this endpoint over a private network only - it must
  never be reachable through a public Caddy route.
- Alertmanager sends alerts to Middleware, never to Odoo. This addon
  contains no alert-receiving code.
- Grafana reads from Prometheus, not from this endpoint directly, and is
  read-only.
- Superset's business-analytics metrics (ASA, AHT, abandonment, etc. - see
  `api/contracts/reporting-metrics-v1.json`) are a separate, unimplemented
  concern from this addon's technical metrics.

## What's exposed and how each number is computed

- `codestra_up` / `codestra_ready` - process-up and a `SELECT 1` DB check,
  same convention as `call_center_campaign`'s existing `/health/ready`.
- `codestra_sms_outbox_backlog` / `_errors_total` - real counts from
  `codestra.sms.outbox.state`.
- `codestra_agent_onboarding_backlog` / `_errors_total` - real counts from
  `codestra.agent.onboarding.state`.
- `codestra_agent_channel_drift_backlog` - real count of
  `codestra.agent.channel` rows requested but not yet provisioned.
- `codestra_mail_queue_backlog` / `_errors_total` - real counts from
  `mail.mail.state`.
- `codestra_metrics_scrape_duration_seconds` - this endpoint's own compute
  time. Odoo/Werkzeug gives addons no platform-wide request-timing hook
  without patching core dispatch, which this addon deliberately does not
  do - so there is no genuine platform-wide HTTP latency metric here, and
  this value must not be presented as one.

## Access control

Gated by a shared bearer token read from a protected file whose *path* is
configured via the `codestra.metrics.token_file` `ir.config_parameter`
(DB-backed, so every worker process sees the same value - unlike an OS
environment variable). The file itself must be a regular file, no symlink,
no group/world permission bits, same convention as
`codestra_agent_onboarding`'s `outbox_delivery._protected_value`. This is
defense in depth on top of, not a replacement for, the private-network-only
routing Caddy's contract already requires for Prometheus scrape targets.
