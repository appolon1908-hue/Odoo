"""Read-only Prometheus text-exposition ``GET /codestra/metrics`` for Odoo.

Scope, deliberately narrow:

  * health/readiness  - real (process-up + a ``SELECT 1`` DB check, same
    convention as ``call_center_campaign``'s ``/health/ready``).
  * backlog           - real ORM-backed counts of non-terminal rows in
    existing queue/outbox models. Genuine data, not synthetic.
  * errors            - real ORM-backed counts of rows already recorded as
    failed/exception by their own model (SMS outbox ``failed``, agent
    onboarding ``failed``, ``mail.mail`` ``exception``). Not an HTTP error
    counter.
  * latency           - Odoo/Werkzeug gives addons no request-timing hook
    without patching core dispatch, which this module will not do. The only
    honest latency figure available here is this endpoint's own scrape
    duration, exposed as ``codestra_metrics_scrape_duration_seconds``. This
    is NOT platform-wide HTTP latency - do not present it as such upstream.

Every counter/gauge is computed fresh per scrape from the current
transaction; nothing is cached or estimated. Access is gated by a shared
bearer token (see ``_expected_token``) - this is defense in depth, not a
substitute for the private-network-only routing already required of
Prometheus scrape targets by ``appolon1908-hue/Caddy``'s
``config/observability-exposure.v1.json``.
"""

import hmac
import time
from pathlib import Path
from stat import S_ISREG

from odoo import http
from odoo.http import Response, request

TOKEN_FILE_PARAM = "codestra.metrics.token_file"
MAX_TOKEN_BYTES = 8192


class MetricsAuthUnavailable(Exception):
    pass


class MetricsAuthRejected(Exception):
    pass


def _expected_token():
    """Read the shared scrape token from a protected, non-symlink file.

    The file *path* is a DB-backed ``ir.config_parameter`` (visible to every
    worker process, unlike an OS environment variable set only in whichever
    process happens to run this request) - mirrors this codebase's general
    convention of using ``ir.config_parameter`` for addon-level config (see
    ``codestra_klyrow_smtp``/``codestra_middleware_bridge``) rather than raw
    env vars. The token *content* itself still lives only in the file, never
    the database, matching ``codestra_agent_onboarding``'s
    ``outbox_delivery._protected_value`` convention: a regular file, no
    symlink, no group/world permission bits. The token is never logged or
    echoed back.
    """
    path_value = request.env["ir.config_parameter"].sudo().get_param(TOKEN_FILE_PARAM, "")
    path = Path(path_value)
    try:
        stat_result = path.stat()
        if (
            not path_value
            or path.is_symlink()
            or not S_ISREG(stat_result.st_mode)
            or stat_result.st_mode & 0o027
        ):
            raise OSError
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise MetricsAuthUnavailable(
            "metrics scrape token reference is unavailable or unsafe"
        ) from error
    if not token or len(token) > MAX_TOKEN_BYTES:
        raise MetricsAuthUnavailable("metrics scrape token is empty or too large")
    return token


def _authenticate():
    expected = _expected_token()
    supplied = request.httprequest.headers.get("Authorization", "")
    if not supplied.startswith("Bearer "):
        raise MetricsAuthRejected("bearer token required")
    if not hmac.compare_digest(supplied.removeprefix("Bearer ").strip(), expected):
        raise MetricsAuthRejected("scrape token rejected")


def _readiness():
    """A real DB round-trip through the ORM (not raw SQL - this addon is
    not part of the reviewed canonical-addon-baseline SQL-exception
    registry, so it must not call ``cr.execute`` directly; the ORM's own
    internal SQL is not subject to that per-addon review gate)."""
    try:
        request.env["ir.config_parameter"].sudo().search_count([])
        return 1
    except Exception:  # noqa: BLE001 - readiness must never raise past this point
        return 0


def _sms_outbox_counts():
    Outbox = request.env["codestra.sms.outbox"].sudo()
    backlog = Outbox.search_count(
        [("state", "in", ("pending", "reconcile", "indeterminate"))]
    )
    errors = Outbox.search_count([("state", "=", "failed")])
    return backlog, errors


def _agent_onboarding_counts():
    Onboarding = request.env["codestra.agent.onboarding"].sudo()
    backlog = Onboarding.search_count(
        [("state", "in", ("draft", "in_review", "approved", "provisioning"))]
    )
    errors = Onboarding.search_count([("state", "=", "failed")])
    return backlog, errors


def _agent_channel_drift():
    Channel = request.env["codestra.agent.channel"].sudo()
    return Channel.search_count(
        [
            ("requested_state", "=", "requested"),
            ("provisioned_state", "=", "not_provisioned"),
        ]
    )


def _mail_queue_counts():
    Mail = request.env["mail.mail"].sudo()
    backlog = Mail.search_count([("state", "=", "outgoing")])
    errors = Mail.search_count([("state", "=", "exception")])
    return backlog, errors


def _render(started_at):
    up = 1
    ready = _readiness()
    sms_backlog, sms_errors = _sms_outbox_counts()
    onboarding_backlog, onboarding_errors = _agent_onboarding_counts()
    channel_drift_backlog = _agent_channel_drift()
    mail_backlog, mail_errors = _mail_queue_counts()
    scrape_duration = max(time.monotonic() - started_at, 0.0)

    lines = [
        "# HELP codestra_up Odoo process responded to this scrape (always 1 if reached).",
        "# TYPE codestra_up gauge",
        f"codestra_up {up}",
        "# HELP codestra_ready Odoo database readiness (SELECT 1 succeeded).",
        "# TYPE codestra_ready gauge",
        f"codestra_ready {ready}",
        "# HELP codestra_sms_outbox_backlog SMS outbox rows not yet delivered or failed.",
        "# TYPE codestra_sms_outbox_backlog gauge",
        f"codestra_sms_outbox_backlog {sms_backlog}",
        "# HELP codestra_sms_outbox_errors_total SMS outbox rows in a terminal failed state.",
        "# TYPE codestra_sms_outbox_errors_total gauge",
        f"codestra_sms_outbox_errors_total {sms_errors}",
        "# HELP codestra_agent_onboarding_backlog Agent onboarding records not yet active/closed/cancelled.",
        "# TYPE codestra_agent_onboarding_backlog gauge",
        f"codestra_agent_onboarding_backlog {onboarding_backlog}",
        "# HELP codestra_agent_onboarding_errors_total Agent onboarding records in a terminal failed state.",
        "# TYPE codestra_agent_onboarding_errors_total gauge",
        f"codestra_agent_onboarding_errors_total {onboarding_errors}",
        "# HELP codestra_agent_channel_drift_backlog Agent channels requested but not yet provisioned.",
        "# TYPE codestra_agent_channel_drift_backlog gauge",
        f"codestra_agent_channel_drift_backlog {channel_drift_backlog}",
        "# HELP codestra_mail_queue_backlog Outgoing mail.mail rows not yet sent.",
        "# TYPE codestra_mail_queue_backlog gauge",
        f"codestra_mail_queue_backlog {mail_backlog}",
        "# HELP codestra_mail_queue_errors_total mail.mail rows in the exception state.",
        "# TYPE codestra_mail_queue_errors_total gauge",
        f"codestra_mail_queue_errors_total {mail_errors}",
        "# HELP codestra_metrics_scrape_duration_seconds Time to compute this scrape response. Not platform-wide HTTP latency.",
        "# TYPE codestra_metrics_scrape_duration_seconds gauge",
        f"codestra_metrics_scrape_duration_seconds {scrape_duration:.6f}",
    ]
    return "\n".join(lines) + "\n"


class CodestraMetricsController(http.Controller):
    @http.route("/codestra/metrics", type="http", auth="none", methods=["GET"], csrf=False)
    def metrics(self):
        started_at = time.monotonic()
        try:
            _authenticate()
        except MetricsAuthUnavailable:
            return Response("metrics authentication unavailable", status=503)
        except MetricsAuthRejected:
            return Response("unauthorized", status=401)
        body = _render(started_at)
        return Response(
            body,
            status=200,
            content_type="text/plain; version=0.0.4; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )
