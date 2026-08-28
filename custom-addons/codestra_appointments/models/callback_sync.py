import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta, timezone

from odoo import api, fields, models
from odoo.exceptions import ValidationError


MAX_RESPONSE_BYTES = 256 * 1024
OPERATIONS = {
    "snoozed": "snooze",
    "rescheduled": "reschedule",
    "cancelled": "cancel",
    "completed": "complete",
    "in_progress": "start",
}


class CallbackSyncJob(models.Model):
    _name = "codestra.callback.sync.job"
    _description = "Codestra Callback Middleware Sync Job"
    _order = "next_attempt_at, id"
    _log_access = True

    callback_id = fields.Many2one(
        "codestra.callback", required=True, ondelete="cascade", index=True
    )
    operation = fields.Selection(
        [(value, value.replace("_", " ").title()) for value in (
            "create", "snoozed", "rescheduled", "cancelled", "completed",
            "in_progress", "reconcile",
        )],
        required=True,
        index=True,
    )
    idempotency_key = fields.Char(required=True, index=True, readonly=True)
    correlation_id = fields.Char(required=True, index=True, readonly=True)
    callback_version = fields.Integer(required=True, readonly=True)
    state = fields.Selection(
        [("pending", "Pending"), ("processing", "Processing"),
         ("done", "Done"), ("failed", "Failed")],
        default="pending", required=True, index=True,
    )
    attempt_count = fields.Integer(default=0, required=True)
    next_attempt_at = fields.Datetime(default=fields.Datetime.now, index=True)
    processing_started_at = fields.Datetime(readonly=True, index=True)
    last_error_code = fields.Char(readonly=True)
    completed_at = fields.Datetime(readonly=True)

    _job_unique = models.Constraint(
        "unique(idempotency_key)", "Callback synchronization jobs must be idempotent."
    )

    @api.model
    def _enabled(self):
        return os.getenv("CODESTRA_CALLBACK_SYNC_ENABLED", "false").lower() == "true"

    @api.model
    def _configuration(self):
        if not self._enabled():
            raise ValidationError("Callback middleware synchronization is disabled.")
        base_url = os.getenv("CODESTRA_CALLBACK_API_BASE_URL", "").rstrip("/")
        token_url = os.getenv("CODESTRA_CALLBACK_TOKEN_URL", "")
        client_id = os.getenv("CODESTRA_CALLBACK_CLIENT_ID", "")
        secret_file = os.getenv("CODESTRA_CALLBACK_CLIENT_SECRET_FILE", "")
        ca_file = os.getenv("CODESTRA_CALLBACK_CA_FILE", "")
        tenant = os.getenv("CODESTRA_CALLBACK_ALLOWED_TENANT", "")
        campaign = os.getenv("CODESTRA_CALLBACK_ALLOWED_CAMPAIGN", "")
        for value, label in ((base_url, "API URL"), (token_url, "token URL"),
                             (client_id, "client ID"), (secret_file, "secret file"),
                             (ca_file, "CA file")):
            if not value:
                raise ValidationError("Callback %s is not configured." % label)
        api = urllib.parse.urlparse(base_url)
        if (
            api.scheme != "https"
            or not api.hostname
            or api.username
            or api.password
            or api.query
            or api.fragment
        ):
            raise ValidationError("Callback API URL must use HTTPS.")
        token = urllib.parse.urlparse(token_url)
        private_keycloak = (
            token.scheme == "http"
            and token.hostname == "keycloak"
            and token.port == 8080
            and token.username is None
            and token.password is None
        )
        if (
            ((token.scheme != "https" and not private_keycloak) or not token.hostname)
            or token.username
            or token.password
            or token.query
            or token.fragment
        ):
            raise ValidationError(
                "Callback token URL must use HTTPS or the private Keycloak service."
            )
        if not os.path.isabs(secret_file) or not os.path.isabs(ca_file):
            raise ValidationError("Callback credentials must use absolute secret paths.")
        if tenant != "COD" or campaign != "TEST_SYN":
            raise ValidationError("Callback production allowlist is not bounded to COD/TEST_SYN.")
        return {
            "base_url": base_url,
            "token_url": token_url,
            "client_id": client_id,
            "secret_file": secret_file,
            "ca_file": ca_file,
            "tenant": tenant,
            "campaign": campaign,
        }

    @api.model
    def _ssl_context(self, ca_file):
        return ssl.create_default_context(cafile=ca_file)

    @api.model
    def _token(self, config):
        with open(config["secret_file"], encoding="utf-8") as handle:
            secret = handle.read().strip()
        if not secret:
            raise ValidationError("Callback client secret is empty.")
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": config["client_id"],
            "client_secret": secret,
            "scope": "callbacks.read callbacks.write",
        }).encode()
        outbound = urllib.request.Request(
            config["token_url"], data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        # _configuration bounds this request to HTTPS or private Keycloak.
        with urllib.request.urlopen(  # nosec B310
            outbound, timeout=10, context=self._ssl_context(config["ca_file"])
        ) as response:
            result = self._read_json(response)
        token = result.get("access_token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise ValidationError("Callback token response is invalid.")
        return token

    @api.model
    def _read_json(self, response):
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValidationError("Callback middleware response is too large.")
        result = json.loads(raw or b"{}")
        if not isinstance(result, dict):
            raise ValidationError("Callback middleware response must be an object.")
        return result

    @api.model
    def _identity(self, record):
        unit = (record.business_unit_id.code or "").upper()
        campaign = (record.campaign_id.code or "").upper()
        if unit != "COD" or campaign != "TEST_SYN":
            raise ValidationError("Callback synchronization denied outside COD/TEST_SYN.")
        agent = record.assigned_agent_id.login if record.assigned_agent_id else None
        team = record.assigned_team_id.code if record.assigned_team_id else None
        if not agent and not team:
            raise ValidationError("Callback synchronization requires an owner.")
        return unit, campaign, agent, team

    @api.model
    def _create_payload(self, record):
        unit, campaign, agent, team = self._identity(record)
        scheduled = fields.Datetime.to_datetime(record.scheduled_at)
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        evidence = record.compliance_evidence or {}
        return {
            "tenant_id": unit,
            "campaign_id": campaign,
            "contact_id": str(record.contact_id.id) if record.contact_id else None,
            "lead_id": str(record.lead_id.id) if record.lead_id else None,
            "opportunity_id": str(record.opportunity_id.id) if record.opportunity_id else None,
            "original_call_id": record.original_call_id or None,
            "original_linkedid": record.original_linkedid or None,
            "assigned_agent_id": agent,
            "assigned_user_id": agent,
            "assigned_team_id": team,
            "supervisor_id": record.supervisor_id.login if record.supervisor_id else None,
            "phone_number": record.phone_number,
            "scheduled_at": scheduled.isoformat(),
            "customer_timezone": record.customer_timezone,
            "priority": record.priority.upper(),
            "reason": record.reason,
            "notes": record.notes or "",
            "reminder_email_enabled": bool(record.reminder_email_enabled),
            "reminder_popup_enabled": bool(record.reminder_popup_enabled),
            "max_attempts": record.max_attempts,
            "compliance": {
                "consent": bool(evidence.get("consent", record.compliance_allowed)),
                "dnc": bool(evidence.get("dnc", False)),
                "suppressed": bool(evidence.get("suppressed", False)),
                "within_calling_hours": bool(evidence.get("within_calling_hours", record.compliance_allowed)),
                "campaign_allowed": bool(evidence.get("campaign_allowed", record.compliance_allowed)),
            },
            "customer_context": {
                "odoo_callback_id": record.id,
                "odoo_callback_uuid": record.callback_uuid,
                "contact_name": record.contact_id.display_name if record.contact_id else None,
            },
        }

    @api.model
    def _change_payload(self, record, operation):
        payload = {"expected_version": record.middleware_version}
        if operation == "rescheduled":
            scheduled = fields.Datetime.to_datetime(record.scheduled_at)
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
            payload.update({"scheduled_at": scheduled.isoformat(),
                            "customer_timezone": record.customer_timezone})
        elif operation == "completed":
            payload.update({"completion_disposition": record.completion_disposition,
                            "completion_notes": record.completion_notes or ""})
        return payload

    @api.model
    def _enqueue(self, record, operation, correlation_id):
        if not self._enabled():
            return self.browse()
        if not record.middleware_callback_uuid and operation != "reconcile":
            operation = "create"
        if operation not in dict(self._fields["operation"].selection):
            return self.browse()
        if operation == "create":
            key = "odoo-callback:%s:create" % record.callback_uuid
        elif operation == "reconcile":
            minute = fields.Datetime.now().replace(second=0, microsecond=0).isoformat()
            key = "odoo-callback:%s:reconcile:%s" % (record.callback_uuid, minute)
        else:
            key = "odoo-callback:%s:v%s:%s" % (
                record.callback_uuid, record.version, operation
            )
        existing = self.search([("idempotency_key", "=", key)], limit=1)
        if existing:
            return existing
        return self.sudo().create({
            "callback_id": record.id,
            "operation": operation,
            "idempotency_key": key,
            "correlation_id": correlation_id,
            "callback_version": record.version,
        })

    def _request(self):
        self.ensure_one()
        config = self._configuration()
        record = self.callback_id
        token = self._token(config)
        headers = {
            "Authorization": "Bearer %s" % token,
            "Accept": "application/json",
            "X-Correlation-ID": self.correlation_id,
            "Idempotency-Key": self.idempotency_key,
        }
        if self.operation == "reconcile":
            method, body = "GET", None
            url = "%s/callbacks/%s" % (config["base_url"], record.middleware_callback_uuid)
        elif self.operation == "create":
            method, body = "POST", self._create_payload(record)
            url = "%s/control/callbacks" % config["base_url"]
        else:
            method, body = "POST", self._change_payload(record, self.operation)
            url = "%s/control/callbacks/%s/%s" % (
                config["base_url"], record.middleware_callback_uuid,
                OPERATIONS[self.operation],
            )
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode() if body is not None else None
        if encoded is not None:
            headers["Content-Type"] = "application/json"
        outbound = urllib.request.Request(url, data=encoded, method=method, headers=headers)
        # _configuration bounds the base URL; only fixed path segments are added.
        with urllib.request.urlopen(  # nosec B310
            outbound, timeout=10, context=self._ssl_context(config["ca_file"])
        ) as response:
            return self._read_json(response)

    def _apply_result(self, result):
        self.ensure_one()
        callback_uuid = result.get("id")
        version = result.get("version")
        state = str(result.get("state", "")).lower()
        if not isinstance(callback_uuid, str) or not isinstance(version, int):
            raise ValidationError("Callback middleware acknowledgement is incomplete.")
        if (self.callback_id.middleware_callback_uuid and
                self.callback_id.middleware_callback_uuid != callback_uuid):
            raise ValidationError("Callback middleware identity changed unexpectedly.")
        values = {
            "middleware_callback_uuid": callback_uuid,
            "middleware_version": version,
            "middleware_sync_state": "synced",
            "middleware_last_sync_at": fields.Datetime.now(),
        }
        if self.operation == "reconcile" and state and state != self.callback_id.state:
            values.update({"state": state, "version": self.callback_id.version + 1})
            if state == "completed":
                values.update({
                    "completion_disposition": result.get("completion_disposition") or False,
                    "completion_notes": result.get("completion_notes") or "",
                    "completed_at": self.callback_id.completed_at or fields.Datetime.now(),
                })
            self.env["codestra.callback.history"].sudo().create({
                "callback_id": self.callback_id.id,
                "event_type": "callback.reconciled",
                "from_state": self.callback_id.state,
                "to_state": state,
                "version": self.callback_id.version + 1,
                "actor_id": self.env.user.id,
                "actor_source": "middleware",
                "correlation_id": self.correlation_id,
                "safe_detail": {"middleware_version": version},
            })
        self.callback_id.with_context(skip_callback_sync=True).sudo().write(values)
        self.write({"state": "done", "completed_at": fields.Datetime.now(),
                    "last_error_code": False})

    def _process_one(self):
        self.ensure_one()
        self.write({
            "state": "processing",
            "attempt_count": self.attempt_count + 1,
            "processing_started_at": fields.Datetime.now(),
        })
        try:
            self._apply_result(self._request())
        except urllib.error.HTTPError as error:
            code = "HTTP_%s" % error.code
            if error.code in (400, 401, 403, 404, 409, 413, 422):
                self.callback_id.with_context(skip_callback_sync=True).write(
                    {"middleware_sync_state": "reconciliation_required"}
                )
                self.write({"state": "failed", "last_error_code": code,
                            "next_attempt_at": False})
                return
            self._retry(code)
        except (OSError, ValueError, ValidationError, json.JSONDecodeError) as error:
            self._retry(type(error).__name__[:64])

    def _retry(self, code):
        if self.attempt_count >= 8:
            self.callback_id.with_context(skip_callback_sync=True).write(
                {"middleware_sync_state": "reconciliation_required"}
            )
            self.write({"state": "failed", "last_error_code": code,
                        "next_attempt_at": False})
            return
        delay = min(900, 2 ** min(self.attempt_count, 9))
        self.write({"state": "pending", "last_error_code": code,
                    "next_attempt_at": fields.Datetime.now() + timedelta(seconds=delay)})

    @api.model
    def _cron_process(self, limit=20):
        if not self._enabled():
            return 0
        # Claim rows in the current transaction. SKIP LOCKED lets multiple Odoo
        # workers run safely without delivering the same callback operation.
        self.env.cr.execute(
            """
                SELECT id
                  FROM codestra_callback_sync_job
                 WHERE state = 'pending'
                   AND next_attempt_at <= %s
                 ORDER BY next_attempt_at, id
                 FOR UPDATE SKIP LOCKED
                 LIMIT %s
            """,
            (fields.Datetime.now(), limit),
        )
        jobs = self.browse([row[0] for row in self.env.cr.fetchall()])
        for job in jobs:
            job._process_one()
            self.env.cr.commit()
        return len(jobs)

    @api.model
    def _cron_reconcile(self, limit=100):
        if not self._enabled():
            return 0
        records = self.env["codestra.callback"].sudo().search([
            ("middleware_callback_uuid", "!=", False),
            ("business_unit_id.code", "=", "COD"),
            ("campaign_id.code", "=", "TEST_SYN"),
            ("state", "not in", ("completed", "cancelled")),
        ], limit=limit)
        for record in records:
            self._enqueue(record, "reconcile", record.correlation_id)
        return len(records)

    def unlink(self):
        raise ValidationError("Callback synchronization audit jobs cannot be deleted.")
