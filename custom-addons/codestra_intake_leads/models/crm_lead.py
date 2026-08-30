from __future__ import annotations

import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CrmLead(models.Model):
    _inherit = "crm.lead"

    codestra_tenant_id = fields.Char(index=True, copy=False)
    codestra_site_id = fields.Char(index=True, copy=False)
    codestra_campaign_key = fields.Char(index=True, copy=False)
    codestra_source_channel = fields.Selection(
        selection=[
            ("form", "Form"),
            ("landing_page", "Landing Page"),
            ("chat", "Chat"),
            ("voice", "Voice"),
            ("api", "API"),
            ("other", "Other"),
        ],
        copy=False,
        index=True,
    )
    codestra_conversation_id = fields.Char(index=True, copy=False)
    codestra_attribution = fields.Json(copy=False)
    codestra_consent = fields.Json(copy=False)
    codestra_intake_metadata = fields.Json(copy=False)

    @api.model
    def codestra_upsert_intake_lead(self, envelope):
        """Create/update a CRM lead from an already-authorized Middleware event."""
        if not isinstance(envelope, dict):
            raise ValidationError("Codestra intake envelope must be an object")

        event_id = self._codestra_required_text(envelope, "event_id", 128)
        tenant_id = self._codestra_required_text(envelope, "tenant_id", 128)
        idempotency_key = self._codestra_required_text(envelope, "idempotency_key", 180)
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise ValidationError("Codestra intake payload must be an object")

        payload_tenant = self._codestra_required_text(payload, "tenantId", 128)
        if payload_tenant != tenant_id:
            raise ValidationError("Codestra intake tenant mismatch")

        receipt = self.env["codestra.intake.receipt"].search(
            [
                ("tenant_id", "=", tenant_id),
                "|",
                ("event_id", "=", event_id),
                ("idempotency_key", "=", idempotency_key),
            ],
            limit=1,
        )
        if receipt:
            return self._codestra_result(receipt.lead_id, "duplicate", event_id, idempotency_key)

        email = self._codestra_normalize_email(payload.get("email"))
        phone = self._codestra_normalize_phone(payload.get("phone"))
        lead = self._codestra_find_open_lead(tenant_id, email, phone)
        values = self._codestra_values(payload=payload, email=email, phone=phone, tenant_id=tenant_id)
        if lead:
            lead.write(self._codestra_update_values(values, payload))
            action = "updated"
        else:
            lead = self.create(values)
            action = "created"

        self.env["codestra.intake.receipt"].create(
            {
                "tenant_id": tenant_id,
                "event_id": event_id,
                "idempotency_key": idempotency_key,
                "correlation_id": (envelope.get("correlation_id") or "")[:180] or False,
                "lead_id": lead.id,
            }
        )
        return self._codestra_result(lead, action, event_id, idempotency_key)

    @api.model
    def _codestra_find_open_lead(self, tenant_id, email, phone):
        domain = [("codestra_tenant_id", "=", tenant_id), ("active", "=", True)]
        identity = []
        if email:
            identity.append(("email_from", "=ilike", email))
        if phone:
            identity.append(("phone_sanitized", "=", self._codestra_phone_digits(phone)))
        if not identity:
            return self.browse()
        domain.extend(["|", identity[0], identity[1]] if len(identity) == 2 else [identity[0]])
        return self.search(domain, order="id desc", limit=1)

    @api.model
    def _codestra_values(self, *, payload, email, phone, tenant_id):
        source = payload.get("source") or "other"
        if source not in {"form", "landing_page", "chat", "voice", "api", "other"}:
            source = "other"
        name = (payload.get("name") or payload.get("message") or "Website lead").strip()[:300]
        description_parts = []
        if payload.get("message"):
            description_parts.append(str(payload["message"])[:10000])
        if payload.get("transcript"):
            description_parts.append("Conversation transcript:\n" + str(payload["transcript"])[:50000])
        return {
            "name": name or "Website lead",
            "contact_name": (payload.get("name") or "")[:300] or False,
            "email_from": email or False,
            "phone": phone or False,
            "description": "\n\n".join(description_parts) or False,
            "codestra_tenant_id": tenant_id,
            "codestra_site_id": (payload.get("siteId") or "")[:180] or False,
            "codestra_campaign_key": (payload.get("campaignId") or "")[:180] or False,
            "codestra_source_channel": source,
            "codestra_conversation_id": (payload.get("conversationId") or "")[:180] or False,
            "codestra_attribution": payload.get("attribution") or {},
            "codestra_consent": payload.get("consent") or {},
            "codestra_intake_metadata": {
                "fields": payload.get("fields") or {},
                "metadata": payload.get("metadata") or {},
            },
        }

    @api.model
    def _codestra_update_values(self, values, payload):
        optional = {
            "name": "name",
            "contact_name": "name",
            "email_from": "email",
            "phone": "phone",
            "description": "message",
            "codestra_site_id": "siteId",
            "codestra_campaign_key": "campaignId",
            "codestra_conversation_id": "conversationId",
            "codestra_attribution": "attribution",
            "codestra_consent": "consent",
        }
        update = dict(values)
        for field_name, payload_name in optional.items():
            if payload_name not in payload:
                update.pop(field_name, None)
        return update

    @api.model
    def _codestra_required_text(self, mapping, key, maximum):
        value = mapping.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"Codestra intake {key} is required")
        value = value.strip()
        if len(value) > maximum:
            raise ValidationError(f"Codestra intake {key} exceeds maximum length")
        return value

    @api.model
    def _codestra_normalize_email(self, value):
        if not value:
            return ""
        value = str(value).strip().lower()
        if len(value) > 320 or "@" not in value:
            raise ValidationError("Codestra intake email is invalid")
        return value

    @api.model
    def _codestra_phone_digits(self, value):
        return re.sub(r"\D", "", value or "")

    @api.model
    def _codestra_normalize_phone(self, value):
        if not value:
            return ""
        raw = str(value).strip()
        leading_plus = raw.startswith("+")
        digits = self._codestra_phone_digits(raw)
        if not digits or len(digits) > 15:
            raise ValidationError("Codestra intake phone is invalid")
        return ("+" if leading_plus else "") + digits

    @api.model
    def _codestra_result(self, lead, action, event_id, idempotency_key):
        return {
            "lead_id": lead.id,
            "action": action,
            "tenant_id": lead.codestra_tenant_id,
            "event_id": event_id,
            "idempotency_key": idempotency_key,
        }


class CodestraIntakeReceipt(models.Model):
    _name = "codestra.intake.receipt"
    _description = "Codestra Intake Receipt"
    _order = "id desc"

    tenant_id = fields.Char(required=True, index=True)
    event_id = fields.Char(required=True, index=True)
    idempotency_key = fields.Char(required=True, index=True)
    correlation_id = fields.Char(index=True)
    lead_id = fields.Many2one("crm.lead", required=True, ondelete="cascade", index=True)

    _event_unique = models.Constraint(
        "UNIQUE(tenant_id, event_id)",
        "A Codestra intake event can only be applied once per tenant.",
    )
    _idempotency_unique = models.Constraint(
        "UNIQUE(tenant_id, idempotency_key)",
        "A Codestra intake idempotency key can only be applied once per tenant.",
    )
