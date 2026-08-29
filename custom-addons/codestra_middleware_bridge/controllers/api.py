from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import ClassVar

from odoo import fields, http
from odoo.http import request

PREFIX = "CODESTRA-INTEGRATION-TEST-"


class CodestraMiddlewareBridge(http.Controller):
    CRM_LEAD_CREATE_FIELDS: ClassVar[set[str]] = {
        "name", "contact_name", "email", "phone", "company_name", "source",
        "campaign", "description", "customer_reference", "external_id", "middleware_id",
        "form_type", "form_version", "source_site", "consent_timestamp",
        "consent_disclosure_version", "sms_consent", "email_marketing_consent",
        "phone_consent", "consent_correlation_id", "consent_status",
        "allow_external_contact", "do_not_call", "suppression_reason",
        "consent_source", "consent_evidence_reference", "review_required",
        "initial_stage", "requested_by", "provenance_method",
        "provenance_reference", "provenance_legal_basis", "provenance_digest",
        "tags",
    }
    CRM_LEAD_PATCH_FIELDS: ClassVar[set[str]] = {
        "name", "contact_name", "email", "phone", "company_name", "source",
        "campaign", "description",
    }
    COMMAND_FIELDS: ClassVar[set[str]] = {
        "command_id", "command_type", "command_version", "target", "tenant_id",
        "requested_by", "correlation_id", "idempotency_key", "capability", "payload",
    }
    COMMAND_PAYLOAD_FIELDS: ClassVar[set[str]] = {
        "lead_source", "source_record_id", "initial_stage", "review_required",
        "allow_external_contact", "provenance", "consent", "lead",
    }
    PROVENANCE_FIELDS: ClassVar[set[str]] = {
        "method", "captured_by", "source_reference", "legal_basis", "content_digest",
    }
    CONSENT_FIELDS: ClassVar[set[str]] = {
        "status", "captured_at", "policy_version", "channels",
    }
    LEAD_FIELDS: ClassVar[set[str]] = {
        "name", "description", "contact", "company", "campaign_code", "tags",
    }
    def _json(self, status, value):
        return request.make_json_response(value, status=status)

    def _body(self):
        raw = request.httprequest.get_data()
        if len(raw) > 131072:
            return None, self._json(413, {"error": "body_too_large"})
        if not raw:
            return {}, None
        try:
            value = json.loads(raw)
        except ValueError:
            return None, self._json(422, {"error": "invalid_json"})
        if not isinstance(value, dict):
            return None, self._json(422, {"error": "object_required"})
        return value, None

    def _authenticate(self, body, tenant_allowlist_parameter=None, service_user_parameter="codestra.middleware.service_user_id"):
        headers = request.httprequest.headers
        timestamp = headers.get("X-Codestra-Timestamp", "")
        event_id = headers.get("X-Codestra-Event-ID", "")
        supplied = headers.get("X-Codestra-Signature", "").removeprefix("sha256=")
        tenant = headers.get("X-Tenant-ID", "")
        correlation = headers.get("X-Correlation-ID", "")
        idempotency = headers.get("Idempotency-Key", "")
        params = request.env["ir.config_parameter"].sudo()
        expected_tenant = params.get_param("codestra.middleware.tenant_id")
        try:
            fresh = abs(int(time.time()) - int(timestamp)) <= 300
        except (TypeError, ValueError):
            fresh = False
        if not all((timestamp, event_id, supplied, tenant, correlation, idempotency)):
            return None, self._json(401, {"error": "missing_authentication"})
        if not fresh:
            return None, self._json(401, {"error": "expired_timestamp"})
        allowed_tenants = {expected_tenant} if expected_tenant else set()
        if tenant_allowlist_parameter:
            allowed_tenants.update(item.strip() for item in (params.get_param(tenant_allowlist_parameter) or "").split(",") if item.strip())
        if not any(hmac.compare_digest(tenant, item) for item in allowed_tenants):
            return None, self._json(403, {"error": "tenant_rejected"})
        # Each tenant is bound to its own secret and its own service identity,
        # so one tenant's credential cannot authenticate another. A global value
        # remains the fallback for single-tenant installations.
        tenant_scope = "codestra.middleware.tenant." + tenant + "."
        secret = (
            params.get_param(tenant_scope + "inbound_hmac_secret")
            or params.get_param("codestra.middleware.inbound_hmac_secret")
        )
        # The security headers are covered by the signature; otherwise they can
        # be swapped freely on an otherwise valid signed body.
        canonical = b"\n".join((
            timestamp.encode(), event_id.encode(), request.httprequest.method.encode(),
            request.httprequest.path.encode(),
            tenant.encode(), correlation.encode(), idempotency.encode(),
            body,
        ))
        expected = hmac.new((secret or "").encode(), canonical, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(expected, supplied):
            return None, self._json(401, {"error": "invalid_signature"})
        user_id = int(
            params.get_param(tenant_scope + service_user_parameter)
            or params.get_param(service_user_parameter, "0")
        )
        user = request.env["res.users"].sudo().browse(user_id).exists()
        group_xmlid = "codestra_middleware_bridge.group_codestra_crm_api" if service_user_parameter == "codestra.crm.service_user_id" else "codestra_middleware_bridge.group_codestra_middleware_bridge"
        group = request.env.ref(group_xmlid)
        if not user or group not in user.group_ids or not user.active:
            return None, self._json(403, {"error": "service_identity_rejected"})
        # auth="none" starts without an ORM user in Odoo 19. Establish the
        # verified service identity for the whole request/flush lifecycle.
        request.update_env(user=user.id)
        return {
            "event_id": event_id, "tenant_id": tenant,
            "correlation_id": correlation, "idempotency_key": idempotency,
            "request_hash": hashlib.sha256(body).hexdigest(), "user": user,
        }, None

    def _begin(self, operation, allow_event_replay=False, tenant_allowlist_parameter=None, service_user_parameter="codestra.middleware.service_user_id"):
        body = request.httprequest.get_data()
        auth, error = self._authenticate(body, tenant_allowlist_parameter, service_user_parameter)
        if error:
            return None, None, error
        evidence = request.env["codestra.middleware.request"].with_user(auth["user"])
        replay = evidence.search([("event_id", "=", auth["event_id"])], limit=1)
        if replay:
            if allow_event_replay and replay.request_hash == auth["request_hash"] and replay.operation == operation:
                value = json.loads(replay.response_json)
                value["duplicate"] = True
                return None, None, self._json(200, value)
            return None, None, self._json(409, {"error": "replayed_event_id"})
        prior = evidence.search([
            ("tenant_id", "=", auth["tenant_id"]),
            ("idempotency_key", "=", auth["idempotency_key"]),
        ], limit=1)
        if prior:
            if prior.request_hash != auth["request_hash"] or prior.operation != operation:
                return None, None, self._json(409, {"error": "idempotency_conflict"})
            value = json.loads(prior.response_json)
            value["duplicate"] = True
            return None, None, self._json(200, value)
        payload, error = self._body()
        return auth, payload, error

    def _complete(self, auth, operation, value, partner=None, status=200):
        event_model = request.env["codestra.integration.event"].with_user(auth["user"])
        # Only a deliberately configured synthetic environment records synthetic
        # evidence; a real command must not be audited as a test.
        synthetic = bool(request.env["ir.config_parameter"].sudo().get_param(
            "codestra.middleware.synthetic_test"
        ))
        event = event_model.register_event(
            "middleware.odoo." + operation, "middleware", "odoo",
            {"synthetic_test": synthetic, "partner_id": partner.id if partner else None},
            correlation_id=auth["correlation_id"],
            idempotency_key=f'middleware:{operation}:{auth["idempotency_key"]}',
        )
        request.env["codestra.integration.audit"].with_user(auth["user"])._append(
            event, "middleware." + operation, "success",
            {"partner_id": partner.id if partner else None, "tenant_id": auth["tenant_id"]},
        )
        value.update({"correlation_id": auth["correlation_id"], "duplicate": False})
        request.env["codestra.middleware.request"].with_user(auth["user"]).create({
            "event_id": auth["event_id"], "idempotency_key": auth["idempotency_key"],
            "request_hash": auth["request_hash"], "operation": operation,
            "correlation_id": auth["correlation_id"], "tenant_id": auth["tenant_id"],
            "response_json": json.dumps(value, sort_keys=True),
            "partner_id": partner.id if partner else False,
        })
        return self._json(status, value)

    def _partner(self, auth, partner_id):
        partner = request.env["res.partner"].with_user(auth["user"]).browse(partner_id).exists()
        if not partner or not (partner.name or "").startswith(PREFIX):
            return None
        return partner

    def _crm_scope(self, auth):
        user = auth["user"]
        group = request.env.ref("codestra_middleware_bridge.group_codestra_crm_api")
        units = user.call_center_business_unit_ids
        if group not in user.group_ids or len(units) != 1 or len(user.company_ids) != 1:
            return None
        unit = units[0]
        if unit.company_id != user.company_ids[0]:
            return None
        return unit

    def _crm_mapping(self, auth, external_id):
        return request.env["codestra.crm.external.mapping"].with_user(auth["user"]).search([
            ("customer_key", "=", auth["tenant_id"]), ("external_id", "=", external_id),
            ("model", "=", "crm.lead"),
        ], limit=1)

    @staticmethod
    def _crm_lead_value(lead, mapping):
        return {
            "external_id": mapping.external_id, "middleware_id": mapping.middleware_id,
            "name": lead.name, "contact_name": lead.contact_name,
            "email": lead.email_from, "phone": lead.phone,
            "company_name": lead.partner_name, "description": lead.description,
            "source": lead.source_id.name if lead.source_id else None,
            "campaign": lead.campaign_id.name if lead.campaign_id else None,
            "form_type": lead.codestra_form_type, "form_version": lead.codestra_form_version,
            "source_site": lead.codestra_source_site,
            "sms_consent": lead.codestra_sms_consent,
            "email_marketing_consent": lead.codestra_email_marketing_consent,
            "phone_consent": lead.codestra_phone_consent,
            "consent_correlation_id": lead.codestra_consent_correlation_id,
            "consent_status": lead.consent_status,
            "allow_external_contact": lead.codestra_allow_external_contact,
            "review_required": lead.codestra_review_required,
            "initial_stage": lead.codestra_initial_stage,
            "do_not_call": lead.do_not_call,
            "contact_eligibility": lead.contact_eligibility,
            "contact_eligibility_reason": lead.contact_eligibility_reason,
            "status": "active" if lead.active else "archived",
            "created_at": lead.create_date.isoformat() if lead.create_date else None,
            "updated_at": lead.write_date.isoformat() if lead.write_date else None,
        }

    def _crm_values(self, payload, allowed, unit, user):
        unsupported = sorted(set(payload) - allowed)
        if unsupported:
            return None, self._json(422, {"error": "unsupported_fields", "fields": unsupported})
        for field_name in (
            "sms_consent", "email_marketing_consent", "phone_consent",
            "allow_external_contact", "do_not_call", "review_required",
        ):
            if field_name in payload and not isinstance(payload[field_name], bool):
                return None, self._json(422, {"error": "invalid_boolean", "field": field_name})
        if payload.get("consent_status", "unknown") not in {
            "unknown", "granted", "denied", "not_applicable",
        }:
            return None, self._json(422, {"error": "invalid_consent_status"})
        if payload.get("suppression_reason", "optout") not in {
            "dnc", "optout", "complaint", "legal", "invalid", "fraud",
        }:
            return None, self._json(422, {"error": "invalid_suppression_reason"})
        if payload.get("initial_stage", "new") not in {"new", "review_pending"}:
            return None, self._json(422, {"error": "invalid_initial_stage"})
        if payload.get("review_required") and (
            payload.get("initial_stage") != "review_pending"
            or payload.get("allow_external_contact") is not False
        ):
            return None, self._json(422, {"error": "unsafe_review_state"})
        if payload.get("do_not_call") and payload.get("phone_consent"):
            return None, self._json(422, {"error": "conflicting_phone_consent"})
        # External contact is only representable when consent was granted for at
        # least one channel. This rejects the "unknown consent, contact allowed"
        # and "granted with every channel false" combinations the contract
        # otherwise permits.
        if payload.get("allow_external_contact") and (
            payload.get("consent_status") != "granted"
            or not any(
                payload.get(name)
                for name in ("phone_consent", "email_marketing_consent", "sms_consent")
            )
        ):
            return None, self._json(422, {"error": "consent_does_not_permit_contact"})
        values = {}
        mapping = {
            "name": "name", "contact_name": "contact_name", "email": "email_from",
            "phone": "phone", "company_name": "partner_name", "description": "description",
            "external_id": "external_source_id", "customer_reference": "source_detail",
        }
        for source, target in mapping.items():
            if source in payload:
                values[target] = payload[source]
        consent_mapping = {
            "form_type": "codestra_form_type", "form_version": "codestra_form_version",
            "source_site": "codestra_source_site", "consent_timestamp": "codestra_consent_timestamp",
            "consent_disclosure_version": "codestra_consent_disclosure_version",
            "sms_consent": "codestra_sms_consent",
            "email_marketing_consent": "codestra_email_marketing_consent",
            "phone_consent": "codestra_phone_consent",
            "consent_correlation_id": "codestra_consent_correlation_id",
            "allow_external_contact": "codestra_allow_external_contact",
            "review_required": "codestra_review_required",
            "initial_stage": "codestra_initial_stage",
            "requested_by": "codestra_requested_by",
            "provenance_method": "codestra_provenance_method",
            "provenance_reference": "codestra_provenance_reference",
            "provenance_legal_basis": "codestra_provenance_legal_basis",
            "provenance_digest": "codestra_provenance_digest",
        }
        for source, target in consent_mapping.items():
            if source in payload:
                values[target] = payload[source]
        if payload.get("source"):
            record = request.env["utm.source"].with_user(user).search(
                [("name", "=", payload["source"])], limit=1
            )
            if not record:
                return None, self._json(422, {"error": "unknown_source"})
            values["source_id"] = record.id
        # crm.lead.campaign_id is redefined by codestra_cc_crm as cc.campaign, so
        # the campaign code resolves against the governed workspace scoped to the
        # authorized business unit, never against utm.campaign.
        if payload.get("campaign"):
            campaign = request.env["cc.campaign"].with_user(user).search([
                ("code", "=", payload["campaign"]),
                ("cc_business_unit_id.legacy_business_unit_id", "=", unit.id),
            ], limit=1)
            if not campaign:
                return None, self._json(422, {"error": "unknown_campaign"})
            values["campaign_id"] = campaign.id
            # Governed campaign records require an explicit source-list key.
            values["cc_source_list_key"] = (
                payload.get("customer_reference")
                or payload.get("external_id")
                or payload.get("source")
                or "codestra-middleware"
            )
        if "tags" in payload:
            tags = payload["tags"]
            if (
                not isinstance(tags, list)
                or len(tags) > 50
                or any(not isinstance(tag, str) or not tag or len(tag) > 128 for tag in tags)
                or len(tags) != len(set(tags))
            ):
                return None, self._json(422, {"error": "invalid_tags"})
            records = request.env["crm.tag"].with_user(user).search([("name", "in", tags)])
            unknown = sorted(set(tags) - set(records.mapped("name")))
            if unknown:
                return None, self._json(422, {"error": "unknown_tags", "tags": unknown})
            values["tag_ids"] = [(6, 0, records.ids)]
        if "initial_stage" in payload:
            stage_xmlid = (
                "codestra_middleware_bridge.crm_stage_middleware_review_pending"
                if payload["initial_stage"] == "review_pending"
                else "codestra_middleware_bridge.crm_stage_middleware_intake"
            )
            values["stage_id"] = request.env.ref(stage_xmlid).id
        values.update({"company_id": unit.company_id.id, "business_unit_id": unit.id})
        return values, None

    def _apply_crm_compliance(self, auth, lead, payload, unit):
        consent_status = payload.get("consent_status", "unknown")
        allow_external_contact = payload.get("allow_external_contact", False)
        do_not_call = bool(payload.get("do_not_call") or consent_status == "denied")
        channel_values = {
            "phone": bool(payload.get("phone_consent")),
            "email": bool(payload.get("email_marketing_consent")),
            "sms": bool(payload.get("sms_consent")),
        }
        # Fail closed: a channel is only preferred when consent was actually
        # granted for it. No fallback to whatever contact detail happens to
        # exist on the lead.
        consent_permits_contact = (
            consent_status == "granted" and any(channel_values.values())
        )
        if do_not_call or not allow_external_contact or not consent_permits_contact:
            preferred = "none"
        else:
            preferred = next(
                channel for channel in ("phone", "email", "sms") if channel_values[channel]
            )
        reason = payload.get("suppression_reason", "optout")
        lead.write({
            "consent_status": consent_status,
            "do_not_call": do_not_call,
            "do_not_contact_reason": (
                reason if do_not_call else "middleware_contact_not_allowed"
                if not allow_external_contact else False
            ),
            "preferred_contact_method": preferred,
        })

        if consent_status in {"granted", "denied"}:
            consent_model = request.env["call.center.consent"].with_user(auth["user"])
            consent_source = payload.get("consent_source") or "codestra-middleware"
            evidence_reference = (
                payload.get("consent_evidence_reference")
                or payload.get("consent_correlation_id")
                or auth["correlation_id"]
            )
            channels = (
                [channel for channel, granted in channel_values.items() if granted]
                if consent_status == "granted"
                else list(channel_values)
            )
            for channel in channels:
                consent_model.create({
                    "lead_id": lead.id,
                    "business_unit_id": unit.id,
                    "channel": channel,
                    "status": consent_status,
                    "consented_at": payload.get("consent_timestamp") or fields.Datetime.now(),
                    "source": consent_source,
                    "evidence_reference": evidence_reference,
                })

        identifiers = []
        if do_not_call or consent_status == "denied":
            identifiers.append(("phone", lead.phone))
        if consent_status == "denied":
            identifiers.extend((
                ("email", lead.email_from),
                ("external_id", lead.external_source_id),
            ))
        suppression_model = request.env["call.center.suppression"].with_user(auth["user"])
        for identifier_type, identifier in identifiers:
            digest = suppression_model.hash_identifier(identifier)
            if not digest:
                continue
            suppression = suppression_model.search([
                ("business_unit_id", "=", unit.id),
                ("identifier_type", "=", identifier_type),
                ("identifier_hash", "=", digest),
            ], limit=1)
            values = {
                "reason": reason,
                "source": payload.get("consent_source") or "codestra-middleware",
                "active": True,
            }
            if suppression:
                suppression.write(values)
            else:
                suppression_model.create({
                    **values,
                    "business_unit_id": unit.id,
                    "identifier_type": identifier_type,
                    "identifier_hash": digest,
                })
        lead.action_check_contact_eligibility()

    def _command_to_crm_payload(self, command, auth):
        if set(command) != self.COMMAND_FIELDS:
            return None, self._json(422, {"error": "invalid_command_fields"})
        if (
            command.get("command_type") != "crm.lead.upsert"
            or command.get("command_version") != "1.0"
            or command.get("target") != "odoo-19"
            or command.get("capability") != "ODOO_WRITE"
        ):
            return None, self._json(422, {"error": "unsupported_command"})
        try:
            uuid.UUID(str(command.get("command_id")))
        except (TypeError, ValueError, AttributeError):
            return None, self._json(422, {"error": "invalid_command_id"})
        for field_name in (
            "tenant_id", "requested_by", "correlation_id", "idempotency_key"
        ):
            value = command.get(field_name)
            if not isinstance(value, str) or not value.strip():
                return None, self._json(422, {
                    "error": "invalid_command_identity", "field": field_name,
                })
        if (
            command.get("command_id") != auth["event_id"]
            or command.get("tenant_id") != auth["tenant_id"]
            or command.get("correlation_id") != auth["correlation_id"]
            or command.get("idempotency_key") != auth["idempotency_key"]
        ):
            return None, self._json(422, {"error": "command_header_mismatch"})
        payload = command.get("payload")
        if not isinstance(payload, dict) or set(payload) != self.COMMAND_PAYLOAD_FIELDS:
            return None, self._json(422, {"error": "invalid_command_payload_fields"})
        provenance = payload.get("provenance")
        consent = payload.get("consent")
        lead = payload.get("lead")
        if (
            not isinstance(provenance, dict)
            or not self.PROVENANCE_FIELDS.issuperset(provenance)
            or not {"method", "captured_by", "source_reference", "legal_basis"}.issubset(provenance)
            or not isinstance(consent, dict)
            or not self.CONSENT_FIELDS.issuperset(consent)
            or not {"status", "channels"}.issubset(consent)
            or not isinstance(lead, dict)
            or not self.LEAD_FIELDS.issuperset(lead)
            or not {"name", "description", "contact", "company", "tags"}.issubset(lead)
        ):
            return None, self._json(422, {"error": "invalid_nested_command_fields"})
        channels = consent.get("channels")
        if not isinstance(channels, dict) or set(channels) != {"email", "sms", "phone"}:
            return None, self._json(422, {"error": "invalid_consent_channels"})
        if any(not isinstance(value, bool) for value in channels.values()):
            return None, self._json(422, {"error": "invalid_consent_channels"})
        if consent.get("status") not in {
            "granted", "denied", "not_applicable", "unknown",
        }:
            return None, self._json(422, {"error": "invalid_consent_status"})
        if provenance.get("method") not in {
            "submitted_by_person", "crawler_discovery", "scraper_import",
        } or provenance.get("legal_basis") not in {
            "consent", "legitimate_interest_review_required", "contract_request",
            "unknown_review_required",
        }:
            return None, self._json(422, {"error": "invalid_provenance"})
        for field_name in ("captured_by", "source_reference"):
            value = provenance.get(field_name)
            if not isinstance(value, str) or not value.strip():
                return None, self._json(422, {
                    "error": "invalid_provenance", "field": field_name,
                })
        digest = provenance.get("content_digest")
        if digest is not None and (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            return None, self._json(422, {"error": "invalid_provenance_digest"})
        contact = lead.get("contact") or {}
        company = lead.get("company") or {}
        if (
            not isinstance(contact, dict)
            or not {"name", "email", "phone", "preferred_language"}.issuperset(contact)
            or not isinstance(company, dict)
            or not {"name", "domain", "industry"}.issuperset(company)
        ):
            return None, self._json(422, {"error": "invalid_lead_subject"})
        if (
            payload.get("review_required") is True
            and (
                payload.get("initial_stage") != "review_pending"
                or payload.get("allow_external_contact") is not False
            )
        ):
            return None, self._json(422, {"error": "unsafe_review_state"})
        if not all(isinstance(payload.get(field), bool) for field in ("review_required", "allow_external_contact")):
            return None, self._json(422, {"error": "invalid_command_boolean"})
        if payload.get("initial_stage") not in {"new", "review_pending"}:
            return None, self._json(422, {"error": "invalid_initial_stage"})
        for field_name in ("lead_source", "source_record_id"):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                return None, self._json(422, {
                    "error": "invalid_command_payload", "field": field_name,
                })
        if not isinstance(lead.get("name"), str) or not lead["name"].strip():
            return None, self._json(422, {"error": "missing_lead_name"})
        captured_at = consent.get("captured_at")
        if captured_at:
            try:
                parsed_captured_at = datetime.fromisoformat(
                    str(captured_at).replace("Z", "+00:00")
                )
                if parsed_captured_at.tzinfo:
                    parsed_captured_at = parsed_captured_at.astimezone(
                        timezone.utc
                    ).replace(tzinfo=None)
                captured_at = fields.Datetime.to_string(parsed_captured_at)
            except (TypeError, ValueError):
                return None, self._json(422, {"error": "invalid_consent_timestamp"})
        return {
            "name": lead["name"],
            "description": lead.get("description"),
            "contact_name": contact.get("name"),
            "email": contact.get("email"),
            "phone": contact.get("phone"),
            "company_name": company.get("name"),
            "source": payload["lead_source"],
            "campaign": lead.get("campaign_code"),
            "external_id": payload["source_record_id"],
            "middleware_id": command["command_id"],
            "initial_stage": payload["initial_stage"],
            "review_required": payload["review_required"],
            "allow_external_contact": payload["allow_external_contact"],
            "form_type": provenance["method"],
            "source_site": provenance["source_reference"],
            "consent_timestamp": captured_at,
            "consent_disclosure_version": consent.get("policy_version"),
            "email_marketing_consent": channels["email"],
            "sms_consent": channels["sms"],
            "phone_consent": channels["phone"],
            "consent_status": consent["status"],
            "consent_correlation_id": command["correlation_id"],
            "consent_source": provenance["captured_by"],
            "consent_evidence_reference": provenance.get("content_digest") or provenance["source_reference"],
            "do_not_call": consent["status"] == "denied",
            "suppression_reason": "optout",
            "requested_by": command["requested_by"],
            "provenance_method": provenance["method"],
            "provenance_reference": provenance["source_reference"],
            "provenance_legal_basis": provenance["legal_basis"],
            "provenance_digest": provenance.get("content_digest"),
            "tags": lead["tags"],
        }, None

    def _prepare_update_values(self, lead, values):
        """Strip immutable campaign ownership from an update.

        codestra_cc_crm treats campaign_id and cc_source_list_key as immutable,
        so an unchanged binding is dropped and a changed one is a conflict
        rather than an AccessError surfaced as a 500.
        """
        incoming = values.pop("campaign_id", None)
        values.pop("cc_source_list_key", None)
        if incoming is not None and incoming != lead.campaign_id.id:
            return self._json(409, {"error": "campaign_binding_immutable"})
        return None

    def _reject_stale_update(self, lead, payload):
        """Reject a command that carries older consent than the stored record."""
        incoming = payload.get("consent_timestamp")
        existing = lead.codestra_consent_timestamp
        if not incoming or not existing:
            return None
        parsed = fields.Datetime.to_datetime(incoming)
        if parsed and parsed < existing:
            return self._json(409, {
                "error": "stale_command",
                "stored_consent_timestamp": existing.isoformat(),
            })
        return None

    def _create_crm_lead(self, auth, payload, unit):
        values, error = self._crm_values(
            payload, self.CRM_LEAD_CREATE_FIELDS, unit, auth["user"]
        )
        if error:
            return None, None, error
        if not payload.get("name") or not payload.get("external_id") or not payload.get("middleware_id"):
            return None, None, self._json(422, {"error": "missing_required_fields"})
        values.update({"type": "lead", "user_id": auth["user"].id})
        lead = request.env["crm.lead"].with_user(auth["user"]).with_company(unit.company_id).create(values)
        mapping = request.env["codestra.crm.external.mapping"].with_user(auth["user"]).create({
            "customer_key": auth["tenant_id"], "external_id": payload["external_id"],
            "middleware_id": payload["middleware_id"], "model": "crm.lead", "record_id": lead.id,
            "company_id": unit.company_id.id, "business_unit_id": unit.id,
            "service_user_id": auth["user"].id,
        })
        self._apply_crm_compliance(auth, lead, payload, unit)
        return lead, mapping, None

    @http.route("/codestra/middleware/v1/crm/leads", type="http", auth="none", methods=["POST"], csrf=False)
    def crm_lead_create(self):
        auth, payload, error = self._begin("crm.lead.create", allow_event_replay=True, tenant_allowlist_parameter="codestra.crm.tenant_ids", service_user_parameter="codestra.crm.service_user_id")
        if error: return error
        unit = self._crm_scope(auth)
        if not unit: return self._json(403, {"error": "crm_service_scope_rejected"})
        lead, mapping, error = self._create_crm_lead(auth, payload, unit)
        if error: return error
        return self._complete(auth, "crm.lead.create", self._crm_lead_value(lead, mapping), status=201)

    @http.route(
        "/codestra/middleware/v1/commands/crm.lead.upsert",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def crm_lead_upsert_command(self):
        auth, command, error = self._begin(
            "crm.lead.upsert",
            allow_event_replay=True,
            tenant_allowlist_parameter="codestra.crm.tenant_ids",
            service_user_parameter="codestra.crm.service_user_id",
        )
        if error:
            return error
        unit = self._crm_scope(auth)
        if not unit:
            return self._json(403, {"error": "crm_service_scope_rejected"})
        payload, error = self._command_to_crm_payload(command, auth)
        if error:
            return error
        mapping = self._crm_mapping(auth, payload["external_id"])
        status = 200
        outcome = "updated"
        if mapping:
            lead = request.env["crm.lead"].with_user(auth["user"]).browse(mapping.record_id).exists()
            if not lead or lead.company_id != unit.company_id or lead.business_unit_id != unit:
                return self._json(409, {"error": "external_mapping_scope_conflict"})
            values, error = self._crm_values(
                payload, self.CRM_LEAD_CREATE_FIELDS, unit, auth["user"]
            )
            if error:
                return error
            error = self._reject_stale_update(lead, payload)
            if error:
                return error
            error = self._prepare_update_values(lead, values)
            if error:
                return error
            lead.write(values)
            self._apply_crm_compliance(auth, lead, payload, unit)
        else:
            lead, mapping, error = self._create_crm_lead(auth, payload, unit)
            if error:
                return error
            status = 201
            outcome = "created"
        result = self._crm_lead_value(lead, mapping)
        result.update({"command_id": command["command_id"], "outcome": outcome})
        return self._complete(auth, "crm.lead.upsert", result, status=status)

    @http.route("/codestra/middleware/v1/crm/leads/<string:external_id>", type="http", auth="none", methods=["GET", "PATCH"], csrf=False)
    def crm_lead(self, external_id):
        operation = "crm.lead.read" if request.httprequest.method == "GET" else "crm.lead.update"
        auth, payload, error = self._begin(operation, allow_event_replay=True, tenant_allowlist_parameter="codestra.crm.tenant_ids", service_user_parameter="codestra.crm.service_user_id")
        if error: return error
        unit = self._crm_scope(auth)
        mapping = unit and self._crm_mapping(auth, external_id)
        if not mapping: return self._json(404, {"error": "lead_not_found"})
        lead = request.env["crm.lead"].with_user(auth["user"]).browse(mapping.record_id).exists()
        if not lead or lead.company_id != unit.company_id or lead.business_unit_id != unit:
            return self._json(404, {"error": "lead_not_found"})
        if operation.endswith("update"):
            values, error = self._crm_values(payload, self.CRM_LEAD_PATCH_FIELDS, unit, auth["user"])
            if error: return error
            error = self._prepare_update_values(lead, values)
            if error: return error
            lead.write(values)
        return self._complete(auth, operation, self._crm_lead_value(lead, mapping))

    @http.route("/codestra/middleware/v1/crm/activities", type="http", auth="none", methods=["POST"], csrf=False)
    def crm_activity_create(self):
        auth, payload, error = self._begin("crm.activity.create", allow_event_replay=True, tenant_allowlist_parameter="codestra.crm.tenant_ids", service_user_parameter="codestra.crm.service_user_id")
        if error: return error
        allowed = {"lead_external_id", "activity_type", "summary", "note", "due_date", "middleware_id"}
        unsupported = sorted(set(payload) - allowed)
        if unsupported: return self._json(422, {"error": "unsupported_fields", "fields": unsupported})
        unit = self._crm_scope(auth); mapping = unit and self._crm_mapping(auth, str(payload.get("lead_external_id", "")))
        if not mapping: return self._json(404, {"error": "lead_not_found"})
        activity_refs = {"todo": "mail.mail_activity_data_todo", "call": "mail.mail_activity_data_call", "email": "mail.mail_activity_data_email"}
        ref = activity_refs.get(str(payload.get("activity_type", "todo")))
        if not ref or not payload.get("summary"): return self._json(422, {"error": "invalid_activity"})
        lead = request.env["crm.lead"].with_user(auth["user"]).browse(mapping.record_id).exists()
        if not lead or lead.business_unit_id != unit: return self._json(404, {"error": "lead_not_found"})
        activity = request.env["mail.activity"].with_user(auth["user"]).create({
            "activity_type_id": request.env.ref(ref).id, "summary": payload["summary"],
            "note": payload.get("note"), "date_deadline": payload.get("due_date") or fields.Date.today(),
            "res_model_id": request.env["ir.model"]._get_id("crm.lead"),
            "res_id": lead.id, "user_id": auth["user"].id,
        })
        return self._complete(auth, "crm.activity.create", {
            "external_id": payload.get("middleware_id"), "lead_external_id": mapping.external_id,
            "status": "scheduled", "created_at": activity.create_date.isoformat(),
        }, status=201)

    @http.route("/codestra/middleware/v1/email-events", type="http", auth="none", methods=["POST"], csrf=False)
    def email_event(self):
        auth, payload, error = self._begin("email.status", allow_event_replay=True, tenant_allowlist_parameter="codestra.middleware.email_tenant_ids")
        if error: return error
        status_by_type = {
            "klyrow.email.delivered": "delivered",
            "klyrow.email.bounced": "bounced",
            "klyrow.email.deferred": "deferred",
        }
        event_type = str(payload.get("event_type", ""))
        status = status_by_type.get(event_type)
        detail = payload.get("payload") or {}
        message_id = str(detail.get("message_id", ""))
        occurred_at = payload.get("occurred_at") or detail.get("timestamp")
        if not status or not message_id or not occurred_at:
            return self._json(422, {"error": "invalid_email_status_event"})
        occurred_at = str(occurred_at).replace("T", " ").removesuffix("Z").split(".", 1)[0]
        record = request.env["codestra.email.delivery.status"].with_user(auth["user"]).create({
            "event_id": auth["event_id"], "correlation_id": auth["correlation_id"],
            "message_id": message_id, "tenant_id": auth["tenant_id"],
            "customer_id": payload.get("customer_id"), "provider": "klyrow",
            "event_type": event_type, "status": status, "occurred_at": occurred_at,
        })
        return self._complete(auth, "email.status", {
            "record_id": record.id, "model": record._name, "status": record.status,
            "event_id": record.event_id, "message_id": record.message_id,
        }, status=201)

    @http.route("/codestra/middleware/v1/contacts", type="http", auth="none", methods=["POST"], csrf=False)
    def create_contact(self):
        auth, payload, error = self._begin("contact.create")
        if error: return error
        name = str(payload.get("name", ""))
        external_id = str(payload.get("external_id", ""))
        if not name.startswith(PREFIX) or not external_id.startswith(PREFIX):
            return self._json(422, {"error": "synthetic_tag_required"})
        partner = request.env["res.partner"].with_user(auth["user"]).create({
            "name": name, "email": payload.get("email"), "phone": payload.get("phone"),
            "codestra_integration_external_id": external_id,
            "codestra_integration_status": "test",
            "comment": "Synthetic middleware connectivity record; safe to archive.",
        })
        return self._complete(auth, "contact.create", self._contact_value(partner), partner, 201)

    @http.route("/codestra/middleware/v1/contacts/<int:partner_id>", type="http", auth="none", methods=["GET", "PATCH"], csrf=False)
    def contact(self, partner_id):
        operation = "contact.read" if request.httprequest.method == "GET" else "contact.update"
        auth, payload, error = self._begin(operation)
        if error: return error
        partner = self._partner(auth, partner_id)
        if not partner: return self._json(404, {"error": "synthetic_contact_not_found"})
        if operation == "contact.update":
            values = {key: payload[key] for key in ("email", "phone") if key in payload}
            if "name" in payload:
                if not str(payload["name"]).startswith(PREFIX):
                    return self._json(422, {"error": "synthetic_tag_required"})
                values["name"] = payload["name"]
            partner.write(values)
        return self._complete(auth, operation, self._contact_value(partner), partner)

    @http.route("/codestra/middleware/v1/contacts/<int:partner_id>/activities", type="http", auth="none", methods=["POST"], csrf=False)
    def activity(self, partner_id):
        auth, payload, error = self._begin("activity.create")
        if error: return error
        partner = self._partner(auth, partner_id)
        if not partner: return self._json(404, {"error": "synthetic_contact_not_found"})
        summary = str(payload.get("summary", ""))
        if not summary.startswith(PREFIX):
            return self._json(422, {"error": "synthetic_tag_required"})
        activity = request.env["mail.activity"].with_user(auth["user"]).create({
            "activity_type_id": request.env.ref("mail.mail_activity_data_todo").id,
            "summary": summary, "note": payload.get("note", "Synthetic connectivity activity"),
            "res_model_id": request.env["ir.model"]._get_id("res.partner"),
            "res_id": partner.id, "user_id": auth["user"].id,
        })
        return self._complete(auth, "activity.create", {"activity_id": activity.id, "partner_id": partner.id}, partner, 201)

    @http.route("/codestra/middleware/v1/contacts/<int:partner_id>/status", type="http", auth="none", methods=["POST"], csrf=False)
    def status(self, partner_id):
        auth, payload, error = self._begin("contact.status")
        if error: return error
        partner = self._partner(auth, partner_id)
        if not partner: return self._json(404, {"error": "synthetic_contact_not_found"})
        value = payload.get("status")
        if value not in {"test", "active", "inactive"}:
            return self._json(422, {"error": "invalid_status"})
        partner.write({"codestra_integration_status": value})
        return self._complete(auth, "contact.status", self._contact_value(partner), partner)

    @staticmethod
    def _contact_value(partner):
        return {
            "partner_id": partner.id, "external_id": partner.codestra_integration_external_id,
            "name": partner.name, "email": partner.email, "phone": partner.phone,
            "status": partner.codestra_integration_status,
        }
