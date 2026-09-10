import re
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..transport import (
    MiddlewareSmsClient, SmsTransportError, STATES, TERMINAL,
    configuration, delivery_enabled, validate_message,
)

_WRITE_CAPABILITY = object()


class SmsOutbox(models.Model):
    _name = "codestra.sms.outbox"
    _description = "Codestra SMS Middleware Outbox"
    _order = "next_attempt_at, id"

    sms_id = fields.Many2one("sms.sms", required=True, ondelete="restrict", readonly=True, index=True)
    lead_id = fields.Many2one("crm.lead", required=True, ondelete="restrict", readonly=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True, index=True)
    business_unit_id = fields.Many2one("call.center.business.unit", required=True, readonly=True, index=True)
    communication_id = fields.Many2one("codestra.campaign.communication", readonly=True, ondelete="restrict")
    tenant_id = fields.Char(required=True, readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    correlation_id = fields.Char(required=True, readonly=True)
    payload = fields.Json(required=True, readonly=True, groups="base.group_system")
    state = fields.Selection([
        ("pending", "Queued locally"), ("reconcile", "Awaiting delivery"),
        ("indeterminate", "Submission requires reconciliation"),
        ("done", "Delivered"), ("failed", "Stopped"),
    ], default="pending", required=True, readonly=True, index=True)
    message_id = fields.Char(readonly=True, index=True)
    middleware_status = fields.Char(readonly=True)
    attempts = fields.Integer(default=0, readonly=True)
    last_error_code = fields.Char(readonly=True)
    next_attempt_at = fields.Datetime(default=fields.Datetime.now, readonly=True, index=True)
    _sms_unique = models.Constraint("unique(sms_id)", "A native SMS may have only one submission intent.")
    _key_unique = models.Constraint("unique(idempotency_key)", "SMS submission identities must be unique.")

    @api.model_create_multi
    def create(self, values_list):
        self._require_internal()
        return super().create(values_list)

    def write(self, values):
        self._require_internal()
        return super().write(values)

    def unlink(self):
        raise AccessError("SMS submission history cannot be deleted.")

    def _require_internal(self):
        if self.env.context.get("_sms_write_capability") is not _WRITE_CAPABILITY:
            raise AccessError("Only the SMS integration may change delivery history.")

    def _update(self, values):
        return self.sudo().with_context(_sms_write_capability=_WRITE_CAPABILITY).write(values)

    @api.model
    def _policy(self, lead, number, config):
        lead.ensure_one()
        unit = lead.business_unit_id
        campaign = lead.call_center_campaign_id
        if (not unit or not campaign or not lead.company_id
                or lead.company_id.id != config["company_id"]
                or unit.company_id != lead.company_id
                or unit.id != config["business_unit_id"]
                or campaign.business_unit_id != unit):
            raise SmsTransportError("SCOPE_MISMATCH")
        if (lead.do_not_call or lead.preferred_contact_method == "none"
                or lead.consent_status in ("revoked", "expired", "denied")
                or lead.migration_review_required):
            raise SmsTransportError("CONTACT_BLOCKED")
        if not re.fullmatch(r"\+[1-9][0-9]{5,14}", number or ""):
            raise SmsTransportError("INVALID_E164_NUMBER")
        # Consent is bound to the lead's actual destination, not a free-form
        # number supplied through the native composer or RPC.
        known = {re.sub(r"[\s().-]", "", str(lead[name] or ""))
                 for name in ("phone", "mobile", "normalized_phone") if name in lead._fields}
        if number not in known:
            raise SmsTransportError("DESTINATION_NOT_BOUND_TO_LEAD")
        now = fields.Datetime.now()
        consents = lead.sudo().consent_ids.filtered(lambda row: row.channel == "sms")
        latest = consents.sorted(lambda row: (row.consented_at, row.id), reverse=True)[:1]
        if latest:
            allowed = (latest.status == "granted" and latest.consented_at <= now
                       and (not latest.expires_at or latest.expires_at > now))
        else:
            allowed = bool(lead.codestra_sms_consent)
        if not allowed:
            raise SmsTransportError("SMS_CONSENT_REQUIRED")
        suppression = self.env["call.center.suppression"].sudo()
        if suppression.search_count([
            ("business_unit_id", "=", unit.id), ("identifier_type", "=", "phone"),
            ("identifier_hash", "=", suppression.hash_identifier(number)), ("active", "=", True),
            "|", ("expires_at", "=", False), ("expires_at", ">", now),
        ]) or self.env["phone.blacklist"].sudo().search_count([("number", "=", number), ("active", "=", True)]):
            raise SmsTransportError("RECIPIENT_SUPPRESSED")
        try:
            local = now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(campaign.timezone or unit.timezone or "UTC"))
        except (ValueError, ZoneInfoNotFoundError):
            raise SmsTransportError("CONTACT_TIMEZONE_INVALID") from None
        if not campaign.calling_hour_start <= local.hour + local.minute / 60 < campaign.calling_hour_end:
            raise SmsTransportError("OUTSIDE_CONTACT_HOURS")
        if lead.partner_id and self.env["codestra.contact.center.complaint"].sudo().search_count([
            ("customer_id", "=", lead.partner_id.id), ("state", "not in", ("RESOLVED", "CLOSED")),
            ("compliance_relevance", "=", True),
        ]):
            raise SmsTransportError("COMPLIANCE_COMPLAINT_HOLD")

    @api.model
    def _enqueue(self, sms):
        sms.ensure_one()
        sms.check_access("write")
        existing = self.sudo().search([("sms_id", "=", sms.id)], limit=1)
        if existing:
            # Native resend never creates a second provider submission.
            existing._project_native_state()
            return existing
        message = sms.mail_message_id
        if not message or message.model != "crm.lead" or not message.res_id:
            raise SmsTransportError("CRM_LEAD_REQUIRED")
        lead = self.env["crm.lead"].browse(message.res_id).exists()
        if not lead:
            raise SmsTransportError("CRM_LEAD_REQUIRED")
        lead.check_access("read")
        config = configuration()
        self._policy(lead, sms.number, config)
        if not sms.uuid or not re.fullmatch(r"[a-fA-F0-9-]{32,36}", sms.uuid):
            raise SmsTransportError("SMS_IDENTITY_INVALID")
        if not sms.body or len(sms.body) > 5000:
            raise SmsTransportError("SMS_CONTENT_INVALID")
        key = "odoo-sms:" + sms.uuid
        payload = {
            "channel": "sms", "from": config["sender"], "to": [sms.number],
            "content": {"text": sms.body},
            "metadata": {"category": "service", "consent": "granted", "odooSmsUuid": sms.uuid,
                         "billingAccountId": config["billing_account_id"],
                         "odooCampaignId": str(lead.call_center_campaign_id.id)},
        }
        communication = self.env["codestra.campaign.communication"].sudo().create({
            "channel": "SMS", "direction": "OUTBOUND", "campaign_id": lead.call_center_campaign_id.id,
            "lead_id": lead.id, "consent_basis": "Odoo SMS consent checked before submission",
            "correlation_id": sms.uuid, "idempotency_key": key,
        })
        job = self.sudo().with_context(_sms_write_capability=_WRITE_CAPABILITY).create({
            "sms_id": sms.id, "lead_id": lead.id, "company_id": lead.company_id.id,
            "business_unit_id": lead.business_unit_id.id, "tenant_id": config["tenant_id"],
            "idempotency_key": key, "correlation_id": sms.uuid, "payload": payload,
            "communication_id": communication.id,
        })
        sms._update_sms_state_and_trackers("process")
        return self.sudo().browse(job.id)

    def _project_native_state(self):
        self.ensure_one()
        native, history = STATES.get(self.middleware_status, ("error", "FAILED") if self.state == "failed" else ("process", "QUEUED"))
        self.sms_id.sudo()._update_sms_state_and_trackers(native, "sms_server" if native == "error" else None)
        self.communication_id.sudo().write({"status": history, "message_id": self.message_id})
        self.sms_id.mail_message_id._notify_message_notification_update()

    def _apply(self, result):
        self.ensure_one()
        status, message_id = validate_message(
            result, tenant=self.tenant_id, key=self.idempotency_key,
            correlation=self.correlation_id, sms_uuid=self.sms_id.uuid, message_id=self.message_id,
        )
        if self.middleware_status in TERMINAL:
            return  # stale readbacks cannot regress a final delivery result
        self._update({
            "message_id": message_id, "middleware_status": status, "last_error_code": False,
            "state": "done" if status == "delivered" else "failed" if status in TERMINAL else "reconcile",
            "next_attempt_at": False if status in TERMINAL else fields.Datetime.now() + timedelta(minutes=1),
        })
        self._project_native_state()

    def _readback(self, client, token):
        return client.message(token=token, tenant=self.tenant_id, key=self.idempotency_key, correlation=self.correlation_id)

    def _cancel_before_submission(self):
        self._update({"state": "failed", "middleware_status": "cancelled",
                      "last_error_code": "CANCELLED_BEFORE_SUBMISSION", "next_attempt_at": False})
        self._project_native_state()

    @api.model
    def _cron_process(self, limit=20):
        # Reconciliation remains available after the delivery switches close.
        domain = [("state", "in", ("pending", "indeterminate", "reconcile")),
                  ("next_attempt_at", "<=", fields.Datetime.now())]
        jobs = self.sudo().search(domain, limit=min(max(int(limit), 1), 100))
        for candidate in jobs:
            job = candidate.try_lock_for_update().filtered_domain(domain)
            if not job:
                continue
            submitting = job.state == "pending"
            if submitting and job.sms_id.state == "canceled":
                job._cancel_before_submission()
                continue
            if submitting and not delivery_enabled():
                job._update({"last_error_code": "SMS_DELIVERY_DISABLED",
                             "next_attempt_at": fields.Datetime.now() + timedelta(minutes=5)})
                continue
            try:
                config = configuration()
                if (job.tenant_id != config["tenant_id"] or job.company_id.id != config["company_id"]
                        or job.business_unit_id.id != config["business_unit_id"]):
                    raise SmsTransportError("SCOPE_MISMATCH")
                if submitting:
                    self._policy(job.lead_id, job.payload["to"][0], config)
                client = MiddlewareSmsClient(config)
                job._update({"attempts": job.attempts + 1})
                token = client.token()
                if submitting:
                    # Commit intent BEFORE any message POST. After a lost HTTP
                    # response, process crash or transaction retry, this row can
                    # only use GET; a 404 never authorizes a new submission.
                    job._update({"state": "indeterminate", "next_attempt_at": fields.Datetime.now() + timedelta(minutes=1)})
                    self.env.cr.commit()
                    job = job.try_lock_for_update()
                    if not job:
                        continue
                    sms = job.sms_id.try_lock_for_update()
                    if not sms:
                        continue
                    sms.invalidate_recordset(["state"])
                    if sms.state == "canceled":
                        job._cancel_before_submission()
                        continue
                    # Recheck consent after the commit; hold the SMS row lock
                    # through POST so cancellation cannot succeed concurrently.
                    self._policy(job.lead_id, job.payload["to"][0], config)
                    result = client.message(token=token, tenant=job.tenant_id, key=job.idempotency_key,
                                            correlation=job.correlation_id, payload=job.payload)
                else:
                    result = job._readback(client, token)
                job._apply(result)
            except SmsTransportError as error:
                values = {"last_error_code": str(error), "next_attempt_at": fields.Datetime.now() + timedelta(minutes=5)}
                if job.state == "pending":
                    if error.retryable and job.attempts < 5:
                        # Token acquisition has no message side effect. Retry
                        # transient failures before the committed POST intent.
                        values["next_attempt_at"] = fields.Datetime.now() + timedelta(minutes=2 ** job.attempts)
                    else:
                        values.update({"state": "failed", "next_attempt_at": False})
                job._update(values)
                if job.state == "failed":
                    job._project_native_state()
            self.env.cr.commit()
