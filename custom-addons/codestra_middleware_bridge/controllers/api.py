from __future__ import annotations

import hashlib
import hmac
import json
import time
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
        "consent_correlation_id",
    }
    CRM_LEAD_PATCH_FIELDS: ClassVar[set[str]] = {
        "name", "contact_name", "email", "phone", "company_name", "source",
        "campaign", "description",
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
        secret = params.get_param("codestra.middleware.inbound_hmac_secret")
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
        canonical = b"\n".join((
            timestamp.encode(), event_id.encode(), request.httprequest.method.encode(),
            request.httprequest.path.encode(), body,
        ))
        expected = hmac.new((secret or "").encode(), canonical, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(expected, supplied):
            return None, self._json(401, {"error": "invalid_signature"})
        user_id = int(params.get_param(service_user_parameter, "0"))
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
        event = event_model.register_event(
            "middleware.odoo." + operation, "middleware", "odoo",
            {"synthetic_test": True, "partner_id": partner.id if partner else None},
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
            "consent_correlation_id": lead.codestra_consent_correlation_id,
            "status": "active" if lead.active else "archived",
            "created_at": lead.create_date.isoformat() if lead.create_date else None,
            "updated_at": lead.write_date.isoformat() if lead.write_date else None,
        }

    def _crm_values(self, payload, allowed, unit, user):
        unsupported = sorted(set(payload) - allowed)
        if unsupported:
            return None, self._json(422, {"error": "unsupported_fields", "fields": unsupported})
        values = {}
        mapping = {
            "name": "name", "contact_name": "contact_name", "email": "email_from",
            "phone": "phone", "company_name": "partner_name", "description": "description",
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
            "consent_correlation_id": "codestra_consent_correlation_id",
        }
        for source, target in consent_mapping.items():
            if source in payload:
                values[target] = payload[source]
        for source, model in (("source", "utm.source"), ("campaign", "utm.campaign")):
            if source in payload:
                record = request.env[model].with_user(user).search([("name", "=", payload[source])], limit=1)
                if not record:
                    return None, self._json(422, {"error": "unknown_" + source})
                values[source + "_id"] = record.id
        values.update({"company_id": unit.company_id.id, "business_unit_id": unit.id})
        return values, None

    @http.route("/codestra/middleware/v1/crm/leads", type="http", auth="none", methods=["POST"], csrf=False)
    def crm_lead_create(self):
        auth, payload, error = self._begin("crm.lead.create", allow_event_replay=True, tenant_allowlist_parameter="codestra.crm.tenant_ids", service_user_parameter="codestra.crm.service_user_id")
        if error: return error
        unit = self._crm_scope(auth)
        if not unit: return self._json(403, {"error": "crm_service_scope_rejected"})
        values, error = self._crm_values(payload, self.CRM_LEAD_CREATE_FIELDS, unit, auth["user"])
        if error: return error
        if not payload.get("name") or not payload.get("external_id") or not payload.get("middleware_id"):
            return self._json(422, {"error": "missing_required_fields"})
        values.update({"type": "lead", "user_id": auth["user"].id})
        lead = request.env["crm.lead"].with_user(auth["user"]).with_company(unit.company_id).create(values)
        mapping = request.env["codestra.crm.external.mapping"].with_user(auth["user"]).create({
            "customer_key": auth["tenant_id"], "external_id": payload["external_id"],
            "middleware_id": payload["middleware_id"], "model": "crm.lead", "record_id": lead.id,
            "company_id": unit.company_id.id, "business_unit_id": unit.id,
            "service_user_id": auth["user"].id,
        })
        return self._complete(auth, "crm.lead.create", self._crm_lead_value(lead, mapping), status=201)

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
