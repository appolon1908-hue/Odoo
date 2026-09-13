import re
from datetime import timedelta
from email.utils import getaddresses
from uuid import uuid4

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import email_normalize

from ..transport import (
    EmailTransportError, MiddlewareEmailClient, STATE_RANK, TERMINAL,
    configuration, delivery_enabled, state_from_events, validate_message,
)
from .mail import _MAIL_WRITE_CAPABILITY

_WRITE_CAPABILITY = object()


class EmailOutbox(models.Model):
    _name = "codestra.email.outbox"
    _description = "Codestra Email Middleware Outbox"
    _order = "next_attempt_at, id"

    mail_id = fields.Many2one(
        "mail.mail", required=True, ondelete="restrict", readonly=True, index=True,
    )
    mail_message_id = fields.Many2one(
        "mail.message", ondelete="restrict", readonly=True, index=True,
    )
    company_id = fields.Many2one(
        "res.company", required=True, ondelete="restrict", readonly=True, index=True,
    )
    tenant_id = fields.Char(required=True, readonly=True, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    correlation_id = fields.Char(required=True, readonly=True, index=True)
    payload = fields.Json(required=True, readonly=True, groups="base.group_system")
    state = fields.Selection([
        ("pending", "Queued locally"), ("reconcile", "Awaiting delivery"),
        ("indeterminate", "Submission requires reconciliation"),
        ("done", "Delivered"), ("failed", "Stopped"),
    ], default="pending", required=True, readonly=True, index=True)
    delivery_state = fields.Selection([
        ("requested", "Requested"), ("accepted", "Accepted"),
        ("queued", "Queued"), ("provider_accepted", "Provider accepted"),
        ("delivered", "Delivered"), ("deferred", "Deferred"),
        ("bounced", "Bounced"), ("complained", "Complained"),
        ("suppressed", "Suppressed"), ("rejected", "Rejected"),
        ("failed", "Failed"),
    ], default="requested", required=True, readonly=True, index=True)
    message_id = fields.Char(readonly=True, index=True)
    provider_reference = fields.Char(readonly=True, index=True)
    attempts = fields.Integer(default=0, readonly=True)
    last_error_code = fields.Char(readonly=True)
    next_attempt_at = fields.Datetime(
        default=fields.Datetime.now, readonly=True, index=True,
    )

    _mail_unique = models.Constraint(
        "unique(mail_id)", "A native email may have only one submission intent.",
    )
    _key_unique = models.Constraint(
        "unique(idempotency_key)", "Email submission identities must be unique.",
    )

    @api.model_create_multi
    def create(self, values_list):
        self._require_internal()
        return super().create(values_list)

    def write(self, values):
        self._require_internal()
        return super().write(values)

    def unlink(self):
        raise AccessError("Email submission history cannot be deleted.")

    def _require_internal(self):
        if self.env.context.get("_email_write_capability") is not _WRITE_CAPABILITY:
            raise AccessError("Only the email integration may change delivery history.")

    def _update(self, values):
        return self.sudo().with_context(
            _email_write_capability=_WRITE_CAPABILITY
        ).write(values)

    @api.model
    def _addresses(self, mail):
        partner_addresses = [
            partner.email_normalized or partner.email or ""
            for partner in mail.recipient_ids
        ]
        values = getaddresses([mail.email_to or "", *partner_addresses])
        normalized = [email_normalize(address or "") for _, address in values]
        recipients = list(dict.fromkeys(
            value.lower() for value in normalized if value
        ))
        if len(recipients) != 1 or len(set(recipients)) != 1:
            raise EmailTransportError("EXACTLY_ONE_RECIPIENT_REQUIRED")
        if mail.email_cc:
            raise EmailTransportError("CC_UNSUPPORTED")
        return recipients

    @api.model
    def _enqueue(self, mail):
        mail.ensure_one()
        mail.check_access("write")
        existing = self.sudo().search([("mail_id", "=", mail.id)], limit=1)
        if existing:
            existing._project_native_state()
            return existing
        config = configuration()
        if self.env.company.id != config["company_id"]:
            raise EmailTransportError("COMPANY_SCOPE_MISMATCH")
        sender = (email_normalize(mail.email_from or "") or "").lower()
        if sender != config["sender"]:
            raise EmailTransportError("SENDER_IDENTITY_MISMATCH")
        recipients = self._addresses(mail)
        if mail.attachment_ids:
            raise EmailTransportError("ATTACHMENTS_UNSUPPORTED")
        if any(
            name in mail._fields and mail[name]
            for name in ("mailing_id", "mailing_trace_ids", "mass_mailing_id")
        ) or mail.mail_message_id.model in {
            "mailing.mailing", "mailing.contact", "mailing.list",
        }:
            raise EmailTransportError("CAMPAIGN_EMAIL_DISABLED")
        subject = str(mail.subject or "")
        html = str(mail.body_html or "")
        if not subject or len(subject) > 998 or not html or len(html) > 100000:
            raise EmailTransportError("EMAIL_CONTENT_INVALID")
        identity = str(uuid4())
        key = "odoo-email:" + identity
        correlation = "odoo-email:" + identity
        payload = {
            "channel": "email",
            "from": config["sender"],
            "to": recipients,
            "replyTo": email_normalize(mail.reply_to or "") or None,
            "content": {"subject": subject, "html": html},
            "metadata": {
                "category": "transactional",
                "odooMailId": str(mail.id),
            },
        }
        job = self.sudo().with_context(
            _email_write_capability=_WRITE_CAPABILITY
        ).create({
            "mail_id": mail.id,
            "mail_message_id": mail.mail_message_id.id or False,
            "company_id": config["company_id"],
            "tenant_id": config["tenant_id"],
            "idempotency_key": key,
            "correlation_id": correlation,
            "payload": payload,
        })
        mail.with_context(
            _codestra_email_mail_capability=_MAIL_WRITE_CAPABILITY
        ).sudo().write({
            "auto_delete": False,
            "codestra_email_state": "requested",
            "codestra_email_correlation_id": correlation,
        })
        return self.sudo().browse(job.id)

    def _project_native_state(self):
        self.ensure_one()
        terminal_failure = self.delivery_state in TERMINAL - {"delivered"}
        values = {
            "codestra_email_state": self.delivery_state,
            "codestra_middleware_message_id": self.message_id or False,
            "codestra_email_correlation_id": self.correlation_id,
            "codestra_provider_reference": self.provider_reference or False,
        }
        if self.delivery_state == "delivered":
            values.update({
                "state": "sent", "date": fields.Datetime.now(),
                "failure_reason": False, "failure_type": False,
            })
        elif terminal_failure:
            values.update({
                "state": "exception", "failure_reason": self.delivery_state,
            })
        else:
            values["state"] = "outgoing"
        self.mail_id.with_context(
            _codestra_email_mail_capability=_MAIL_WRITE_CAPABILITY
        ).sudo().write(values)
        if self.mail_message_id:
            notifications = self.env["mail.notification"].sudo().search([
                ("mail_message_id", "=", self.mail_message_id.id),
                ("notification_type", "=", "email"),
            ])
            if self.delivery_state == "delivered":
                notifications.write({"notification_status": "sent"})
            elif terminal_failure:
                notifications.write({
                    "notification_status": "bounce"
                    if self.delivery_state == "bounced" else "exception",
                    "failure_reason": self.delivery_state,
                })
            self.mail_message_id._notify_message_notification_update()

    def _apply(self, result, events=None):
        self.ensure_one()
        state, message_id, provider_reference = validate_message(
            result,
            tenant=self.tenant_id,
            key=self.idempotency_key,
            correlation=self.correlation_id,
            mail_id=self.mail_id.id,
            message_id=self.message_id,
        )
        if events is not None:
            state = state_from_events(events, state)
        if STATE_RANK[self.delivery_state] > STATE_RANK[state]:
            state = self.delivery_state
        terminal = state in TERMINAL
        self._update({
            "message_id": message_id,
            "provider_reference": provider_reference or self.provider_reference,
            "delivery_state": state,
            "last_error_code": False,
            "state": "done" if state == "delivered" else "failed" if terminal else "reconcile",
            "next_attempt_at": (
                False if terminal
                else fields.Datetime.now() + timedelta(minutes=1)
            ),
        })
        self._project_native_state()

    def _apply_callback(self, *, state, tenant, correlation, message_id,
                        provider_reference=None):
        """Project one authenticated Middleware callback without another send/read."""
        self.ensure_one()
        if (
            tenant != self.tenant_id
            or correlation != self.correlation_id
            or message_id != self.message_id
            or state not in STATE_RANK
        ):
            raise EmailTransportError("CALLBACK_IDENTITY_MISMATCH")
        if STATE_RANK[state] < STATE_RANK[self.delivery_state]:
            return False
        terminal = state in TERMINAL
        values = {
            "delivery_state": state,
            "state": "done" if state == "delivered" else "failed" if terminal else "reconcile",
            "last_error_code": False,
            "next_attempt_at": (
                False if terminal
                else fields.Datetime.now() + timedelta(minutes=1)
            ),
        }
        if provider_reference:
            values["provider_reference"] = provider_reference
        self._update(values)
        self._project_native_state()
        return True

    def _readback(self, client, token):
        result = client.message(
            token=token, tenant=self.tenant_id, key=self.idempotency_key,
            correlation=self.correlation_id,
        )
        events = None
        if self.message_id or result.get("messageId"):
            events = client.events(
                token=token, tenant=self.tenant_id, key=self.idempotency_key,
                correlation=self.correlation_id,
                message_id=self.message_id or result["messageId"],
            )
        return result, events

    @api.model
    def _cron_process(self, limit=20):
        domain = [
            ("state", "in", ("pending", "indeterminate", "reconcile")),
            ("next_attempt_at", "<=", fields.Datetime.now()),
        ]
        jobs = self.sudo().search(domain, limit=min(max(int(limit), 1), 100))
        for candidate in jobs:
            job = candidate.try_lock_for_update().filtered_domain(domain)
            if not job:
                continue
            submitting = job.state == "pending"
            if submitting and not delivery_enabled():
                job._update({
                    "last_error_code": "EMAIL_DELIVERY_DISABLED",
                    "next_attempt_at": fields.Datetime.now() + timedelta(minutes=5),
                })
                continue
            try:
                config = configuration()
                if (
                    job.tenant_id != config["tenant_id"]
                    or job.company_id.id != config["company_id"]
                ):
                    raise EmailTransportError("SCOPE_MISMATCH")
                client = MiddlewareEmailClient(config)
                job._update({"attempts": job.attempts + 1})
                token = client.token()
                if submitting:
                    job._update({
                        "state": "indeterminate",
                        "next_attempt_at": fields.Datetime.now() + timedelta(minutes=1),
                    })
                    self.env.cr.commit()
                    job = job.try_lock_for_update()
                    if not job:
                        continue
                    result = client.message(
                        token=token, tenant=job.tenant_id,
                        key=job.idempotency_key,
                        correlation=job.correlation_id, payload=job.payload,
                    )
                    events = None
                else:
                    result, events = job._readback(client, token)
                job._apply(result, events)
            except EmailTransportError as error:
                values = {
                    "last_error_code": str(error),
                    "next_attempt_at": fields.Datetime.now() + timedelta(minutes=5),
                }
                if job.state == "pending":
                    if error.retryable and job.attempts < 5:
                        values["next_attempt_at"] = (
                            fields.Datetime.now() + timedelta(seconds=2 ** job.attempts)
                        )
                    else:
                        values.update({
                            "state": "failed", "delivery_state": "failed",
                            "next_attempt_at": False,
                        })
                job._update(values)
                if job.state == "failed":
                    job._project_native_state()
            self.env.cr.commit()
