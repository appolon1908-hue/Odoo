from __future__ import annotations

import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CrmLead(models.Model):
    _inherit = "crm.lead"

    codestra_intake_event_id = fields.Char(index=True, copy=False)
    codestra_intake_idempotency_key = fields.Char(index=True, copy=False)
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

    _codestra_intake_event_unique = models.Constraint(
        "UNIQUE(codestra_tenant_id, codestra_intake_event_id)",
        "A Codestra intake event can only be applied once per tenant.",
    )
    _codestra_intake_idempotency_unique = models.Constraint(
        "UNIQUE(codestra_tenant_id, codestra_intake_idempotency_key)",
        "A Codestra intake idempotency key can only be applied once per tenant.",
    )

    @api.model
    def codestra_upsert_intake_lead(self, envelope):
        """Create/update a CRM lead from an already-authorized Middleware event.

        This method is intentionally not an HTTP controller. Middleware remains the
        cross-system write authority and calls the Odoo connector through the
        existing trusted integration channel.
        """
        if not isinstance(envelope, dict):
            raise ValidationError("Codestra intake envelope must be an object")

        event_id = self._codestra_required_text(envelope, "event_id", 128)
        tenant_id = self._codestra_required_text(envelope, "tenant_id", 128)
        idempotency_key = self._codestra_required_text(
            envelope, "idempotency_key", 180
        )
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise ValidationError("Codestra intake payload must be an object")

        payload_tenant = self._codestra_required_text(payload, "tenantId", 128)
        if payload_tenant != tenant_id:
            raise ValidationError("Codestra intake tenant mismatch")

        existing = self.search(
            [
                ("codestra_tenant_id", "=", tenant_id),
                "|",
                ("codestra_intake_event_id", "=", event_id),
                ("codestra_intake_idempotency_key", "=", idempotency_key),
            ],
            limit=1,
        )
        if existing:
            return self._codestra_result(existing, "duplicate")

        email = self._codestra_normalize_email(payload.get("email"))
        phone = self._codestra_normalize_phone(payload.get("phone"))

        lead = self._codestra_find_open_lead(tenant_id, email, phone)
        values = self._codestra_values(
            envelope=envelope,
            payload=payload,
            email=email,
            phone=phone,
        )
        if lead:
            lead.write(values)
            return self._codestra_result(lead, "updated")

        lead = self.create(values)
        return self._codestra_result(lead, "created")

    @api.model
    def _codestra_find_open_lead(self, tenant_id, email, phone):
        domain = [
            ("codestra_tenant_id", "=", tenant_id),
            ("active", "=", True),
        ]
        identity = []
        if email:
            identity.append(("email_from", "=ilike", email))
        if phone:
            identity.append(("phone", "=", phone))
        if not identity:
            return self.browse()
        if len(identity) == 2:
            domain.extend(["|", identity[0], identity[1]])
        else:
            domain.append(identity[0])
        return self.search(domain, order="id desc", limit=1)

    @api.model
    def _codestra_values(self, *, envelope, payload, email, phone):
        source = payload.get("source") or "other"
        if source not in {"form", "landing_page", "chat", "voice", "api", "other"}:
            source = "other"
        name = (payload.get("name") or payload.get("message") or "Website lead").strip()
        if len(name) > 300:
            name = name[:300]
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
            "codestra_intake_event_id": envelope["event_id"],
            "codestra_intake_idempotency_key": envelope["idempotency_key"],
            "codestra_tenant_id": envelope["tenant_id"],
            "codestra_site_id": (payload.get("siteId") or "")[:180] or False,
            "codestra_campaign_key": (payload.get("campaignId") or "")[:180] or False,
            "codestra_source_channel": source,
            "codestra_conversation_id": (payload.get("conversationId") or "")[:180] or False,
            "codestra_attribution": payload.get("attribution") or {},
            "codestra_consent": payload.get("consent") or {},
            "codestra_intake_metadata": {
                "fields": payload.get("fields") or {},
                "metadata": payload.get("metadata") or {},
                "correlation_id": envelope.get("correlation_id"),
            },
        }

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
    def _codestra_normalize_phone(self, value):
        if not value:
            return ""
        raw = str(value).strip()
        leading_plus = raw.startswith("+")
        digits = re.sub(r"\D", "", raw)
        if not digits or len(digits) > 15:
            raise ValidationError("Codestra intake phone is invalid")
        return ("+" if leading_plus else "") + digits

    @api.model
    def _codestra_result(self, lead, action):
        return {
            "lead_id": lead.id,
            "action": action,
            "tenant_id": lead.codestra_tenant_id,
            "event_id": lead.codestra_intake_event_id,
            "idempotency_key": lead.codestra_intake_idempotency_key,
        }
