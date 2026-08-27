from datetime import timezone
from zoneinfo import ZoneInfo

from odoo import fields, models
from odoo.exceptions import ValidationError


class CrmLead(models.Model):
    _inherit = "crm.lead"

    consent_status = fields.Selection(
        [("unknown", "Unknown"), ("granted", "Granted"), ("revoked", "Revoked"),
         ("expired", "Expired")],
        default="unknown",
        required=True,
        tracking=True,
    )
    do_not_call = fields.Boolean(default=False, index=True, tracking=True)
    do_not_contact_reason = fields.Char(tracking=True)
    consent_ids = fields.One2many("call.center.consent", "lead_id")
    contact_eligibility = fields.Selection(
        [("unchecked", "Unchecked"), ("eligible", "Eligible"),
         ("blocked", "Blocked"), ("outside_hours", "Outside Calling Hours")],
        default="unchecked",
        required=True,
        index=True,
        tracking=True,
    )
    contact_eligibility_reason = fields.Char(readonly=True)
    contact_eligibility_checked_at = fields.Datetime(readonly=True)

    def _active_compliance_rule(self):
        self.ensure_one()
        domain = [
            ("active", "=", True),
            ("business_unit_id", "=", self.business_unit_id.id),
            "|",
            ("campaign_id", "=", self.call_center_campaign_id.id),
            ("campaign_id", "=", False),
        ]
        return self.env["call.center.compliance.rule"].search(domain, order="priority", limit=1)

    def action_check_contact_eligibility(self):
        now_utc = fields.Datetime.now().replace(tzinfo=timezone.utc)
        suppression_model = self.env["call.center.suppression"]
        for lead in self:
            reasons = []
            state = "eligible"
            if lead.do_not_call or lead.preferred_contact_method == "none":
                reasons.append("do_not_contact")
            identifiers = [
                ("phone", lead.normalized_phone),
                ("email", lead.normalized_email),
                ("external_id", lead.external_source_id),
            ]
            for kind, value in identifiers:
                digest = suppression_model.hash_identifier(value)
                if digest and suppression_model.search_count(
                    [
                        ("business_unit_id", "=", lead.business_unit_id.id),
                        ("identifier_type", "=", kind),
                        ("identifier_hash", "=", digest),
                        ("active", "=", True),
                        "|",
                        ("expires_at", "=", False),
                        ("expires_at", ">", fields.Datetime.now()),
                    ]
                ):
                    reasons.append(f"suppressed_{kind}")
            rule = lead._active_compliance_rule()
            if rule and rule.consent_required:
                valid_consent = lead.consent_ids.filtered(
                    lambda consent: consent.channel == "phone"
                    and consent.status == "granted"
                    and (not consent.expires_at or consent.expires_at > fields.Datetime.now())
                )
                if not valid_consent:
                    reasons.append("consent_required")
            if reasons:
                state = "blocked"
            elif rule:
                tz_name = (
                    lead.call_center_campaign_id.timezone
                    or lead.business_unit_id.timezone
                    or "UTC"
                )
                local_hour = now_utc.astimezone(ZoneInfo(tz_name)).hour + (
                    now_utc.astimezone(ZoneInfo(tz_name)).minute / 60
                )
                if not rule.calling_hour_start <= local_hour < rule.calling_hour_end:
                    state = "outside_hours"
                    reasons.append("outside_calling_hours")
            lead.write(
                {
                    "contact_eligibility": state,
                    "contact_eligibility_reason": ",".join(reasons) or False,
                    "contact_eligibility_checked_at": fields.Datetime.now(),
                }
            )
            self.env["call.center.audit.event"].sudo().create(
                {
                    "business_unit_id": lead.business_unit_id.id,
                    "event_type": "lead.contact_eligibility.checked",
                    "model_name": lead._name,
                    "record_id": lead.id,
                    "new_values_json": {"state": state, "reasons": reasons},
                }
            )
        return True

    def assert_contact_allowed(self):
        for lead in self:
            lead.action_check_contact_eligibility()
            if lead.contact_eligibility != "eligible":
                raise ValidationError(
                    f"Contact is blocked: {lead.contact_eligibility_reason or lead.contact_eligibility}"
                )
        return True
