from __future__ import annotations

import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


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
        """Create/update a CRM lead from an authorized Middleware service event."""
        if not isinstance(envelope, dict):
            raise ValidationError("Codestra intake envelope must be an object")

        event_id = self._codestra_required_text(envelope, "event_id", 128)
        tenant_id = self._codestra_required_text(envelope, "tenant_id", 128)
        idempotency_key = self._codestra_required_text(envelope, "idempotency_key", 180)
        self._codestra_require_middleware_identity(tenant_id)

        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise ValidationError("Codestra intake payload must be an object")
        payload_tenant = self._codestra_required_text(payload, "tenantId", 128)
        if payload_tenant != tenant_id:
            raise ValidationError("Codestra intake tenant mismatch")

        receipt_model = self.env["codestra.intake.receipt"].sudo()
        receipt = receipt_model.search(
            [
                ("tenant_id", "=", tenant_id),
                "|",
                ("event_id", "=", event_id),
                ("idempotency_key", "=", idempotency_key),
            ],
            limit=1,
        )
        if receipt:
            return self._codestra_duplicate_result(receipt, event_id, idempotency_key)

        # Reserve the durable identities before any CRM mutation. PostgreSQL's
        # unique constraints serialize concurrent ORM inserts. The savepoint
        # contains only the reservation, so a losing request can roll it back and
        # safely reload the winner without rolling back unrelated request work.
        try:
            with self.env.cr.savepoint():
                receipt = receipt_model.create(
                    {
                        "tenant_id": tenant_id,
                        "event_id": event_id,
                        "idempotency_key": idempotency_key,
                        "correlation_id": (envelope.get("correlation_id") or "")[:180] or False,
                    }
                )
                self.env.cr.flush()
        except Exception as exc:
            # SQLSTATE 23505 is PostgreSQL's unique_violation. Do not import or
            # call a database driver directly; all other errors remain fail-closed.
            if getattr(exc, "pgcode", None) != "23505":
                raise
            receipt = receipt_model.search(
                [
                    ("tenant_id", "=", tenant_id),
                    "|",
                    ("event_id", "=", event_id),
                    ("idempotency_key", "=", idempotency_key),
                ],
                limit=1,
            )
            if not receipt:
                raise
            return self._codestra_duplicate_result(receipt, event_id, idempotency_key)

        # The narrow middleware service group is verified above. Use sudo only
        # after authorization so arbitrary authenticated RPC callers never gain
        # receipt or cross-record privileges.
        lead_model = self.sudo()
        email = lead_model._codestra_normalize_email(payload.get("email"))
        phone = lead_model._codestra_normalize_phone(payload.get("phone"))
        identities, identity_lead = lead_model._codestra_reserve_identities(
            tenant_id, email, phone
        )
        lead = identity_lead or lead_model._codestra_find_open_lead(
            tenant_id, email, phone
        )
        values = lead_model._codestra_values(
            payload=payload,
            email=email,
            phone=phone,
            tenant_id=tenant_id,
        )
        if lead:
            lead.write(lead_model._codestra_update_values(lead, values, payload))
            action = "updated"
        else:
            lead = lead_model.create(values)
            action = "created"

        lead_model._codestra_apply_consent(lead, payload.get("consent"), event_id)

        identities._codestra_finalize_lead(lead)
        receipt._codestra_finalize_lead(lead)
        return self._codestra_result(
            lead,
            action,
            event_id,
            idempotency_key,
            tenant_id=tenant_id,
        )

    @api.model
    def _codestra_require_middleware_identity(self, tenant_id):
        if not self.env.user.has_group("codestra_middleware_bridge.group_codestra_crm_api"):
            raise AccessError("Codestra intake upserts require the Middleware CRM service identity")
        params = self.env["ir.config_parameter"].sudo()
        configured = params.get_param("codestra.crm.tenant_ids") or params.get_param(
            "codestra.middleware.tenant_id"
        )
        allowed = {
            value.strip()
            for value in (configured or "").split(",")
            if value.strip()
        }
        if tenant_id not in allowed:
            raise AccessError("Codestra intake tenant is not authorized for the Middleware service")
        principal_key = f"codestra.crm.service_user.{self.env.user.id}.tenant_ids"
        principal_tenants = {
            value.strip()
            for value in (params.get_param(principal_key) or "").split(",")
            if value.strip()
        }
        if tenant_id not in principal_tenants:
            raise AccessError("Codestra intake tenant is not bound to this service principal")

    @api.model
    def _codestra_reserve_identities(self, tenant_id, email, phone):
        identity_model = self.env["codestra.intake.identity"].sudo()
        reservations = identity_model.browse()
        linked_leads = self.browse()
        values = sorted(
            (("email", email), ("phone", phone)),
            key=lambda item: item[0],
        )
        for identity_type, identity_value in values:
            if not identity_value:
                continue
            domain = [
                ("tenant_id", "=", tenant_id),
                ("identity_type", "=", identity_type),
                ("identity_value", "=", identity_value),
            ]
            reservation = identity_model.search(domain, limit=1)
            if not reservation:
                try:
                    with self.env.cr.savepoint():
                        reservation = identity_model.create({
                            "tenant_id": tenant_id,
                            "identity_type": identity_type,
                            "identity_value": identity_value,
                        })
                        self.env.cr.flush()
                except Exception as exc:
                    if getattr(exc, "pgcode", None) != "23505":
                        raise
                    reservation = identity_model.search(domain, limit=1)
                    if not reservation:
                        raise
            reservations |= reservation
            linked_leads |= reservation.lead_id
        if len(linked_leads) > 1:
            raise ValidationError("Codestra intake identities resolve to conflicting leads")
        return reservations, linked_leads[:1]

    @api.model
    def _codestra_duplicate_result(self, receipt, event_id, idempotency_key):
        return self._codestra_result(
            receipt.lead_id,
            "duplicate",
            event_id,
            idempotency_key,
            tenant_id=receipt.tenant_id,
        )

    @api.model
    def _codestra_find_open_lead(self, tenant_id, email, phone):
        base_domain = [("codestra_tenant_id", "=", tenant_id), ("active", "=", True)]
        if email:
            lead = self.search(
                base_domain + [("email_from", "=ilike", email)],
                order="id desc",
                limit=1,
            )
            if lead:
                return lead
        if phone:
            lead = self.search(
                base_domain + [("normalized_phone", "=", phone)],
                order="id desc",
                limit=1,
            )
            if lead:
                return lead
        return self.browse()

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
            description_parts.append(
                "Conversation transcript:\n" + str(payload["transcript"])[:50000]
            )
        return {
            "name": name or "Website lead",
            "contact_name": (payload.get("name") or "")[:300] or False,
            "email_from": email or False,
            "phone": phone or False,
            "normalized_phone": phone or False,
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
    def _codestra_update_values(self, lead, values, payload):
        update = dict(values)
        optional = {
            "name": "name",
            "contact_name": "name",
            "email_from": "email",
            "phone": "phone",
            "codestra_site_id": "siteId",
            "codestra_campaign_key": "campaignId",
            "codestra_conversation_id": "conversationId",
            "codestra_attribution": "attribution",
            "codestra_consent": "consent",
            "codestra_source_channel": "source",
        }
        for field_name, payload_name in optional.items():
            if payload_name not in payload:
                update.pop(field_name, None)
        if "message" not in payload and "transcript" not in payload:
            update.pop("description", None)
        if "fields" not in payload and "metadata" not in payload:
            update.pop("codestra_intake_metadata", None)
        else:
            existing = dict(lead.codestra_intake_metadata or {})
            merged = {
                "fields": existing.get("fields") or {},
                "metadata": existing.get("metadata") or {},
            }
            if "fields" in payload:
                merged["fields"] = payload.get("fields") or {}
            if "metadata" in payload:
                merged["metadata"] = payload.get("metadata") or {}
            update["codestra_intake_metadata"] = merged
        return update

    @api.model
    def _codestra_apply_consent(self, lead, consent_payload, event_id):
        if consent_payload is None:
            return
        if not isinstance(consent_payload, dict):
            raise ValidationError("Codestra intake consent must be an object")
        channel_fields = {"email": "email_from", "sms": "phone", "phone": "phone"}
        consent_model = self.env["call.center.consent"].sudo()
        suppression_model = self.env["call.center.suppression"].sudo()
        for channel, granted in consent_payload.items():
            if channel not in channel_fields or not isinstance(granted, bool):
                raise ValidationError("Codestra intake consent channel/value is invalid")
            destination = lead[channel_fields[channel]]
            if not destination:
                raise ValidationError(f"Codestra intake {channel} consent requires a destination")
            evidence = f"codestra-intake:{event_id}:{channel}"
            prior = consent_model.search(
                [("lead_id", "=", lead.id), ("channel", "=", channel)],
                order="id desc",
                limit=1,
            )
            if granted:
                if not prior or prior.status != "granted":
                    consent_model.create({
                        "lead_id": lead.id,
                        "business_unit_id": lead.business_unit_id.id,
                        "channel": channel,
                        "status": "granted",
                        "source": "codestra_intake",
                        "evidence_reference": evidence,
                    })
                continue
            if prior and prior.status == "granted":
                prior.with_context(revocation_reason="Codestra intake opt-out").action_revoke()
            identifier_type = "email" if channel == "email" else "phone"
            identifier_hash = suppression_model.hash_identifier(destination)
            suppression = suppression_model.search([
                ("business_unit_id", "=", lead.business_unit_id.id),
                ("identifier_type", "=", identifier_type),
                ("identifier_hash", "=", identifier_hash),
            ], limit=1)
            if suppression:
                suppression.write({"active": True, "reason": "optout", "source": evidence})
            else:
                suppression_model.create({
                    "business_unit_id": lead.business_unit_id.id,
                    "identifier_type": identifier_type,
                    "identifier_hash": identifier_hash,
                    "reason": "optout",
                    "source": evidence,
                })
            if channel == "phone":
                lead.write({"do_not_call": True, "do_not_contact_reason": "Codestra intake opt-out"})

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
    def _codestra_result(
        self,
        lead,
        action,
        event_id,
        idempotency_key,
        *,
        tenant_id,
    ):
        return {
            "lead_id": lead.id if lead else False,
            "action": action,
            "tenant_id": tenant_id,
            "event_id": event_id,
            "idempotency_key": idempotency_key,
        }


class CodestraIntakeReceipt(models.Model):
    _name = "codestra.intake.receipt"
    _description = "Codestra Intake Receipt"
    _order = "id desc"

    tenant_id = fields.Char(required=True, index=True, readonly=True)
    event_id = fields.Char(required=True, index=True, readonly=True)
    idempotency_key = fields.Char(required=True, index=True, readonly=True)
    correlation_id = fields.Char(index=True, readonly=True)
    lead_id = fields.Many2one(
        "crm.lead",
        required=False,
        ondelete="set null",
        index=True,
        readonly=True,
    )

    _event_unique = models.Constraint(
        "UNIQUE(tenant_id, event_id)",
        "A Codestra intake event can only be applied once per tenant.",
    )
    _idempotency_unique = models.Constraint(
        "UNIQUE(tenant_id, idempotency_key)",
        "A Codestra intake idempotency key can only be applied once per tenant.",
    )

    def _codestra_finalize_lead(self, lead):
        if any(receipt.lead_id for receipt in self):
            raise AccessError("Codestra intake receipt has already been finalized")
        return super().write({"lead_id": lead.id})

    def write(self, values):
        raise AccessError("Codestra intake receipts are immutable")

    def unlink(self):
        raise AccessError("Codestra intake receipts are immutable")


class CodestraIntakeIdentity(models.Model):
    _name = "codestra.intake.identity"
    _description = "Codestra Intake Normalized Identity"

    tenant_id = fields.Char(required=True, index=True, readonly=True)
    identity_type = fields.Selection(
        [("email", "Email"), ("phone", "Phone")],
        required=True,
        index=True,
        readonly=True,
    )
    identity_value = fields.Char(required=True, index=True, readonly=True)
    lead_id = fields.Many2one("crm.lead", ondelete="set null", index=True, readonly=True)

    _identity_unique = models.Constraint(
        "UNIQUE(tenant_id, identity_type, identity_value)",
        "A normalized intake identity can map to only one lead per tenant.",
    )

    def _codestra_finalize_lead(self, lead):
        conflicting = self.filtered(lambda identity: identity.lead_id and identity.lead_id != lead)
        if conflicting:
            raise AccessError("Codestra intake identity is already mapped to another lead")
        pending = self.filtered(lambda identity: not identity.lead_id)
        if pending:
            super(CodestraIntakeIdentity, pending).write({"lead_id": lead.id})

    def write(self, values):
        raise AccessError("Codestra intake identities are immutable")

    def unlink(self):
        raise AccessError("Codestra intake identities are immutable")
