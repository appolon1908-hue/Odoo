from datetime import datetime, timezone
from uuid import uuid4

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import AccessError

from ..controllers.contract import validate_ack


class CrmLead(models.Model):
    _inherit = "crm.lead"

    codestra_lead_uid = fields.Char(index=True, copy=False, readonly=True)
    _codestra_lead_uid_uniq = models.Constraint(
        "UNIQUE(codestra_lead_uid)", "Lead UID must be unique."
    )


class LeadAutomationReceipt(models.Model):
    _name = "codestra.lead.automation.receipt"
    _description = "Lead automation acknowledgement evidence"
    _order = "create_date desc"
    automation_event_id = fields.Char(required=True, index=True, readonly=True)
    environment = fields.Char(required=True, readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True)
    request_hash = fields.Char(required=True, readonly=True)
    company_id = fields.Many2one("res.company", ondelete="restrict", index=True, readonly=True)
    acknowledgement_id = fields.Char(required=True, readonly=True, index=True)
    acknowledgement_json = fields.Json(required=True, readonly=True)
    business_unit_id = fields.Many2one("call.center.business.unit", ondelete="restrict", index=True, readonly=True)
    campaign_id = fields.Many2one("call.center.campaign", ondelete="restrict", index=True, readonly=True)
    automation_action = fields.Char(required=True, readonly=True)
    result = fields.Char(required=True, readonly=True)
    _environment_idempotency_uniq = models.Constraint(
        "UNIQUE(environment,idempotency_key)",
        "Duplicate lead automation idempotency key.",
    )
    _ack_uniq = models.Constraint(
        "UNIQUE(environment,acknowledgement_id)", "Duplicate acknowledgement ID."
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("codestra_lead_automation_internal"):
            raise AccessError("Lead automation evidence is system controlled.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Lead automation evidence is append-only.")

    def unlink(self):
        raise AccessError("Lead automation evidence is append-only.")

    @api.model
    def _company_from_signed_key(self, company_key):
        """Resolve only the exact company identity authenticated in the HMAC body."""
        company_id = int(company_key.removeprefix("COMPANY-"))
        return self.env["res.company"].sudo().browse(company_id).exists()

    @api.model
    def _scoped_model(self, company, model_name):
        """Elevate only after company identity and policy scope are established."""
        return (
            self.with_user(SUPERUSER_ID)
            .with_company(company)
            .env[model_name]
        )

    @api.model
    def apply_authorized(self, body, environment, idempotency_key, request_hash):
        action = body["automation_action"]
        lead = False
        consent = body["consent_snapshot"]
        result = "DENIED"
        applied_fields = []
        unchanged_fields = []
        rejected_fields = []
        company = self._company_from_signed_key(body["company_key"])
        unit = campaign = config = policy = False
        scoped = self.with_company(company).env if company else None
        if scoped:
            unit = self._scoped_model(company, "call.center.business.unit").search(
                [("code", "=ilike", body["business_unit_key"]), ("company_id", "=", company.id)], limit=1
            )
            campaign = self._scoped_model(company, "call.center.campaign").search(
                [("code", "=", body["campaign_key"]), ("business_unit_id", "=", unit.id)], limit=1
            )
            config = self._scoped_model(company, "codestra.lead.automation.config").search(
                [("environment", "=", environment), ("business_unit_id", "=", unit.id), ("campaign_id", "=", campaign.id), ("enabled", "=", True)], limit=1
            )
            policy = self._scoped_model(company, "codestra.lead.automation.policy").search(
                [("environment", "=", environment), ("business_unit_id", "=", unit.id),
                 ("campaign_id", "=", campaign.id), ("policy_version", "=", body["policy_version"]),
                 ("action", "=", action), ("channel", "=", "internal"),
                 ("purpose", "=", consent["consent_purpose"]),
                 ("decision", "=", "ALLOW"), ("active", "=", True),
                 ("effective_from", "<=", fields.Datetime.now()),
                 "|", ("effective_until", "=", False), ("effective_until", ">", fields.Datetime.now())], limit=1
            )
        if consent["dnc_status"]:
            result = "DNC_BLOCKED"
        elif consent["consent_status"] in {"denied", "expired", "unknown"}:
            result = "CONSENT_BLOCKED"
        elif not unit or not campaign or not config or not policy:
            result = "DENIED"
            rejected_fields = sorted(body["attributes"])
        elif action == "CREATE_LEAD":
            lead_uid = f"LEAD-{uuid4().hex}"
            lead = (
                self._scoped_model(company, "crm.lead")
                .create(
                    {
                        # The scraper certification lane is intentionally
                        # recognizable and blocked from outbound automation.
                        # Do not derive this display name from untrusted input.
                        "name": f"ZZ_CDX_SCRAPER_CANARY_{body['automation_event_id']}",
                        "type": "lead",
                        "codestra_lead_uid": lead_uid,
                        "business_unit_id": unit.id,
                        "call_center_campaign_id": campaign.id,
                        "is_codestra_call_center_lead": True,
                    }
                )
            )
            applied_fields = ["lead_uid"]
            result = "APPLIED"
        else:
            lead = (
                self._scoped_model(company, "crm.lead")
                .search([("codestra_lead_uid", "=", body.get("lead_uid"))], limit=1)
            )
            if not lead or lead.business_unit_id != unit or lead.call_center_campaign_id != campaign:
                lead = False
                result = "DENIED"
                rejected_fields = sorted(body["attributes"])
            else:
                # Business-unit attributes are policy inputs, not arbitrary crm.lead
                # column names. A later approved mapping may apply a subset.
                result = "NO_CHANGE"
                unchanged_fields = sorted(body["attributes"])
        lead_uid = lead.codestra_lead_uid if lead else body.get("lead_uid", "LEAD-unassigned")
        ack = {
            "contract_version": "1.1",
            "automation_event_id": body["automation_event_id"],
            "automation_action": action,
            "lead_uid": lead_uid,
            "odoo_record_id": lead.id if lead else None,
            "result": result,
            "applied_fields": applied_fields,
            "unchanged_fields": unchanged_fields,
            "rejected_fields": rejected_fields,
            "company_key": body["company_key"],
            "business_unit_key": body["business_unit_key"],
            "campaign_key": body["campaign_key"],
            "policy_version": body["policy_version"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "idempotent_replay": False,
        }
        validate_ack(ack, body)
        self.with_user(SUPERUSER_ID).with_context(
            codestra_lead_automation_internal=True
        ).create(
            {
                "automation_event_id": body["automation_event_id"],
                "environment": environment,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "company_id": company.id if company else False,
                "acknowledgement_id": f"ACK-{uuid4().hex}",
                "acknowledgement_json": ack,
                "business_unit_id": unit.id if unit else False,
                "campaign_id": campaign.id if campaign else False,
                "automation_action": action,
                "result": result,
            }
        )
        return ack
