from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.request
import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class ResPartner(models.Model):
    _inherit = "res.partner"

    codestra_integration_external_id = fields.Char(index=True, copy=False)
    codestra_integration_status = fields.Selection(
        [("test", "Test"), ("active", "Active"), ("inactive", "Inactive")],
        default="test",
        copy=False,
    )

    _codestra_external_unique = models.Constraint(
        "UNIQUE(codestra_integration_external_id)",
        "Middleware external contact IDs must be unique.",
    )


class CrmLead(models.Model):
    _inherit = "crm.lead"

    codestra_form_type = fields.Char(index=True, readonly=True, copy=False)
    codestra_form_version = fields.Char(readonly=True, copy=False)
    codestra_source_site = fields.Char(index=True, readonly=True, copy=False)
    codestra_consent_timestamp = fields.Datetime(readonly=True, copy=False)
    codestra_consent_disclosure_version = fields.Char(readonly=True, copy=False)
    codestra_sms_consent = fields.Boolean(readonly=True, copy=False)
    codestra_email_marketing_consent = fields.Boolean(readonly=True, copy=False)
    codestra_consent_correlation_id = fields.Char(index=True, readonly=True, copy=False)

class MiddlewareRequest(models.Model):
    _name = "codestra.middleware.request"
    _description = "Codestra Middleware Idempotency Record"
    _order = "id desc"

    event_id = fields.Char(required=True, index=True, readonly=True)
    idempotency_key = fields.Char(required=True, index=True, readonly=True)
    request_hash = fields.Char(required=True, readonly=True)
    operation = fields.Char(required=True, readonly=True)
    correlation_id = fields.Char(required=True, index=True, readonly=True)
    tenant_id = fields.Char(required=True, index=True, readonly=True)
    response_json = fields.Text(required=True, readonly=True)
    partner_id = fields.Many2one("res.partner", ondelete="restrict", readonly=True)
    created_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)

    _event_unique = models.Constraint("UNIQUE(event_id)", "Middleware event IDs cannot be replayed.")
    _idempotency_unique = models.Constraint(
        "UNIQUE(tenant_id,idempotency_key)",
        "Middleware idempotency keys are tenant scoped and unique.",
    )

    def write(self, values):
        raise AccessError("Middleware request evidence is immutable.")

    def unlink(self):
        raise AccessError("Middleware request evidence is immutable.")


class EmailDeliveryStatus(models.Model):
    _name = "codestra.email.delivery.status"
    _description = "Codestra Email Delivery Status"
    _order = "occurred_at desc, id desc"

    event_id = fields.Char(required=True, index=True, readonly=True)
    correlation_id = fields.Char(required=True, index=True, readonly=True)
    message_id = fields.Char(required=True, index=True, readonly=True)
    tenant_id = fields.Char(required=True, index=True, readonly=True)
    customer_id = fields.Char(index=True, readonly=True)
    provider = fields.Char(required=True, readonly=True, default="klyrow")
    event_type = fields.Char(required=True, readonly=True)
    status = fields.Selection(
        [("delivered", "Delivered"), ("bounced", "Bounced"), ("deferred", "Deferred")],
        required=True, readonly=True, index=True,
    )
    occurred_at = fields.Datetime(required=True, readonly=True)

    _event_unique = models.Constraint("UNIQUE(event_id)", "Email delivery event IDs must be unique.")

    def write(self, values):
        raise AccessError("Email delivery evidence is immutable.")

    def unlink(self):
        raise AccessError("Email delivery evidence is immutable.")


class CrmExternalMapping(models.Model):
    _name = "codestra.crm.external.mapping"
    _description = "Codestra CRM External Object Mapping"
    _order = "id desc"

    customer_key = fields.Char(required=True, index=True, readonly=True)
    external_id = fields.Char(required=True, index=True, readonly=True)
    middleware_id = fields.Char(required=True, index=True, readonly=True)
    model = fields.Selection([("crm.lead", "CRM Lead")], required=True, readonly=True)
    record_id = fields.Integer(required=True, index=True, readonly=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True)
    business_unit_id = fields.Many2one("call.center.business.unit", required=True, readonly=True)
    service_user_id = fields.Many2one("res.users", required=True, readonly=True)
    created_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)

    _customer_external_unique = models.Constraint(
        "UNIQUE(customer_key,external_id,model)", "External CRM object IDs are tenant scoped and unique."
    )
    _middleware_unique = models.Constraint("UNIQUE(middleware_id)", "Middleware object IDs are unique.")

    def write(self, values):
        raise AccessError("CRM mappings are immutable.")

    def unlink(self):
        raise AccessError("CRM mappings are immutable.")


class MiddlewareOutbound(models.AbstractModel):
    _name = "codestra.middleware.outbound"
    _description = "Odoo to Codestra Middleware Event Client"

    @api.model
    def emit_synthetic_event(self, event_type, correlation_id, idempotency_key, payload):
        if not str(event_type).startswith(("customer.", "campaign.")):
            raise ValidationError("Unsupported Odoo middleware event type.")
        if not payload.get("synthetic_test"):
            raise ValidationError("This method is restricted to tagged synthetic events.")
        params = self.env["ir.config_parameter"].sudo()
        target = params.get_param("codestra.middleware.event_url")
        api_key = params.get_param("codestra.middleware.api_key")
        secret = params.get_param("codestra.middleware.webhook_secret")
        tenant = params.get_param("codestra.middleware.tenant_id")
        if not all((target, api_key, secret, tenant)):
            raise ValidationError("Middleware outbound identity is not configured.")
        event_id = "odoo-" + uuid.uuid4().hex
        envelope = {
            "event_type": event_type,
            "event_version": "1.0",
            "occurred_at": fields.Datetime.now().isoformat() + "Z",
            "tenant_id": tenant,
            "customer_id": payload.get("customer_id"),
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "payload": payload,
            "metadata": {"source": "odoo", "synthetic_test": True},
        }
        raw = json.dumps(envelope, separators=(",", ":")).encode()
        stamp = str(int(time.time()))
        canonical = b"\n".join((stamp.encode(), event_id.encode(), b"odoo", raw))
        signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
        request = urllib.request.Request(target, raw, {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
            "X-Event-Id": event_id,
            "X-Timestamp": stamp,
            "X-Signature": "sha256=" + signature,
        }, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            result = json.loads(response.read())
            status = response.status
        event = self.env["codestra.integration.event"].register_event(
            event_type, "odoo", "middleware", payload,
            correlation_id=correlation_id, idempotency_key=idempotency_key,
        )
        self.env["codestra.integration.audit"]._append(
            event, "middleware.delivery", "success",
            {"http_status": status, "event_id": event_id},
        )
        return {"http_status": status, "event_id": event_id, "result": result}
