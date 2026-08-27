import hashlib

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CallCenterComplianceRule(models.Model):
    _name = "call.center.compliance.rule"
    _description = "Configurable Contact Compliance Rule"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]
    _order = "priority, name"

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    priority = fields.Integer(default=10)
    campaign_id = fields.Many2one("call.center.campaign", ondelete="cascade")
    country_id = fields.Many2one("res.country")
    state_id = fields.Many2one("res.country.state")
    region = fields.Char()
    channel = fields.Selection(
        [("phone", "Phone"), ("email", "Email"), ("sms", "SMS"), ("all", "All")],
        default="phone",
        required=True,
    )
    consent_required = fields.Boolean(default=True)
    recording_disclosure_required = fields.Boolean(default=True)
    ai_disclosure_required = fields.Boolean(default=True)
    calling_hour_start = fields.Float(default=9.0)
    calling_hour_end = fields.Float(default=17.0)
    retention_days = fields.Integer(default=365)
    recording_retention_days = fields.Integer(default=90)
    transcript_retention_days = fields.Integer(default=90)

    @api.constrains(
        "calling_hour_start", "calling_hour_end", "retention_days",
        "recording_retention_days", "transcript_retention_days"
    )
    def _check_limits(self):
        for rule in self:
            if not 0 <= rule.calling_hour_start < rule.calling_hour_end <= 24:
                raise ValidationError("Calling hours must be an increasing 0–24 range.")
            if min(rule.retention_days, rule.recording_retention_days, rule.transcript_retention_days) < 0:
                raise ValidationError("Retention periods cannot be negative.")


class CallCenterConsent(models.Model):
    _name = "call.center.consent"
    _description = "Customer Consent Record"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]
    _order = "consented_at desc, id desc"

    lead_id = fields.Many2one("crm.lead", ondelete="cascade", index=True)
    partner_id = fields.Many2one("res.partner", ondelete="cascade", index=True)
    channel = fields.Selection(
        [("phone", "Phone"), ("email", "Email"), ("sms", "SMS")],
        required=True,
        index=True,
    )
    status = fields.Selection(
        [("granted", "Granted"), ("revoked", "Revoked"), ("expired", "Expired")],
        required=True,
        default="granted",
        tracking=True,
    )
    consented_at = fields.Datetime(required=True, default=fields.Datetime.now)
    expires_at = fields.Datetime()
    source = fields.Char(required=True)
    evidence_reference = fields.Char(
        required=True, help="Protected reference; do not store raw sensitive evidence."
    )
    revoked_at = fields.Datetime(readonly=True)
    revoked_reason = fields.Char(readonly=True)

    @api.constrains("lead_id", "partner_id")
    def _check_subject(self):
        for consent in self:
            if bool(consent.lead_id) == bool(consent.partner_id):
                raise ValidationError("Consent must reference exactly one lead or contact.")

    def action_revoke(self):
        self.write(
            {
                "status": "revoked",
                "revoked_at": fields.Datetime.now(),
                "revoked_reason": self.env.context.get("revocation_reason", "Opt-out"),
            }
        )

    def unlink(self):
        raise AccessError("Consent history is immutable; revoke instead.")


class CallCenterSuppression(models.Model):
    _name = "call.center.suppression"
    _description = "Contact Suppression Entry"
    _inherit = ["call.center.business.unit.mixin"]
    _order = "create_date desc"

    identifier_type = fields.Selection(
        [("phone", "Phone"), ("email", "Email"), ("external_id", "External ID")],
        required=True,
    )
    identifier_hash = fields.Char(required=True, index=True)
    reason = fields.Selection(
        [("dnc", "Do Not Call"), ("optout", "Opt-Out"), ("complaint", "Complaint"),
         ("legal", "Legal Hold"), ("invalid", "Invalid Destination"),
         ("fraud", "Fraud / Risk")],
        required=True,
    )
    source = fields.Char(required=True)
    active = fields.Boolean(default=True, index=True)
    expires_at = fields.Datetime()
    notes = fields.Text(groups="call_center_core.group_call_center_compliance")

    _hash_unique = models.Constraint(
        "unique(identifier_type, identifier_hash, business_unit_id)",
        "A suppression identifier may appear only once per business unit.",
    )

    @api.model
    def hash_identifier(self, value):
        normalized = (value or "").strip().lower()
        return hashlib.sha256(normalized.encode()).hexdigest() if normalized else False
