from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CampaignDesignProfile(models.Model):
    _name = "codestra.campaign.design.profile"
    _description = "Versioned Staging Campaign Design Profile"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="cascade")
    required_field_names = fields.Text(required=True)
    sla_first_response_minutes = fields.Integer(default=15, required=True)
    sla_follow_up_minutes = fields.Integer(default=1440, required=True)
    duplicate_window_days = fields.Integer(default=30, required=True)
    retention_days = fields.Integer(default=365, required=True)
    protected_field_names = fields.Text()
    assignment_policy = fields.Selection(
        [("round_robin", "Round Robin"), ("skill", "Skill"), ("manual", "Manual")],
        default="skill", required=True,
    )
    design_version = fields.Char(default="R1", required=True, readonly=True)
    integration_public_id = fields.Char(required=True, index=True, copy=False)
    active = fields.Boolean(default=False, help="Designs remain disabled until activation approval.")

    _code_unique = models.Constraint("unique(code)", "Design profile codes must be unique.")
    _public_id_unique = models.Constraint(
        "unique(integration_public_id)", "Design integration IDs must be unique."
    )

    @api.constrains("campaign_id", "business_unit_id")
    def _check_scope(self):
        for row in self:
            if row.campaign_id.business_unit_id != row.business_unit_id:
                raise ValidationError("Campaign design cannot cross business units.")


class CrmLead(models.Model):
    _inherit = "crm.lead"

    campaign_design_id = fields.Many2one("codestra.campaign.design.profile", index=True)
    source_idempotency_key = fields.Char(index=True, copy=False)
    consent_evidence_reference = fields.Char(copy=False, tracking=True)
    contact_permission = fields.Selection(
        [("unknown", "Unknown"), ("granted", "Granted"), ("revoked", "Revoked"), ("dnc", "DNC")],
        default="unknown", required=True, tracking=True,
    )
    service_country_code = fields.Char(size=2)
    service_timezone = fields.Char()
    service_area = fields.Char()
    requested_service_date = fields.Date()
    origin_address = fields.Char()
    destination_address = fields.Char()
    shipment_type = fields.Char()
    shipment_dimensions = fields.Char()
    shipment_weight = fields.Float()
    loan_product = fields.Char()
    requested_amount = fields.Monetary(currency_field="company_currency")
    jurisdiction_code = fields.Char(size=8)
    digital_service_type = fields.Char()
    project_scope = fields.Text()
    budget_range = fields.Char()
    target_platform = fields.Char()
    project_timeline = fields.Char()
    consultation_status = fields.Char()
    senior_product_service = fields.Char()
    caregiver_contact_id = fields.Many2one("res.partner", ondelete="restrict")
    repayment_program = fields.Char()
    repayment_servicer = fields.Char()
    service_category = fields.Char()
    service_address = fields.Char()
    geocode_reference = fields.Char(copy=False)
    availability_window = fields.Char()
    provider_match_reference = fields.Char(copy=False)
    estimate_reference = fields.Char(copy=False)
    provider_acceptance_state = fields.Selection(
        [("pending", "Pending"), ("accepted", "Accepted"), ("declined", "Declined")],
        default="pending",
    )
    lead_fee_state = fields.Selection(
        [("not_applicable", "Not Applicable"), ("pending", "Pending"), ("paid", "Paid"), ("refunded", "Refunded")],
        default="not_applicable",
    )
    reconciliation_state = fields.Selection(
        [("pending", "Pending"), ("delivered", "Delivered"), ("reconciled", "Reconciled"), ("failed", "Failed")],
        default="pending", required=True, copy=False, index=True,
    )

    _source_idempotency_unique = models.Constraint(
        "unique(company_id, source_idempotency_key)",
        "Source idempotency keys must be unique per company.",
    )

    @api.constrains("campaign_design_id", "contact_permission", "consent_evidence_reference")
    def _check_campaign_consent_and_required_fields(self):
        for lead in self:
            design = lead.campaign_design_id
            if not design:
                continue
            if design.business_unit_id != lead.business_unit_id:
                raise ValidationError("Lead and campaign design must share a business unit.")
            if design.campaign_id.consent_required and (
                lead.contact_permission != "granted" or not lead.consent_evidence_reference
            ):
                raise ValidationError("Consent evidence is required for this campaign.")
            if design.campaign_id.dnc_enforced and lead.contact_permission in {"dnc", "revoked"}:
                raise ValidationError("DNC or revoked contacts cannot enter this campaign.")
            missing = [
                name.strip() for name in design.required_field_names.split(",")
                if name.strip() in lead._fields and not lead[name.strip()]
            ]
            if missing:
                raise ValidationError("Missing campaign fields: %s" % ", ".join(sorted(missing)))


class AppointmentType(models.Model):
    _inherit = "codestra.appointment.type"

    customer_can_reschedule = fields.Boolean(default=True)
    customer_can_cancel = fields.Boolean(default=True)
    cancellation_notice_hours = fields.Integer(default=24)
    requires_provider_match = fields.Boolean(default=False)
    integration_public_id = fields.Char(index=True, copy=False)

    _integration_public_id_unique = models.Constraint(
        "unique(integration_public_id)", "Appointment integration IDs must be unique."
    )
