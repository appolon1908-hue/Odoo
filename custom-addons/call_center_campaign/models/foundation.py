from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


DISPOSITION_CATEGORIES = [
    ("no_contact", "No Contact"),
    ("invalid_contact", "Invalid Contact"),
    ("human_contact", "Human Contact"),
    ("progress", "Progress"),
    ("negative", "Negative"),
    ("success", "Success"),
    ("compliance", "Compliance"),
    ("system", "System / Technical"),
]


class CallCenterTeam(models.Model):
    _inherit = "call.center.team"

    branch_id = fields.Many2one("call.center.branch", index=True)

    @api.constrains("branch_id", "business_unit_id")
    def _check_branch_scope(self):
        for team in self:
            if team.branch_id and team.business_unit_id not in team.branch_id.business_unit_ids:
                raise ValidationError("Team branch must include its business unit.")


class CallCenterCampaign(models.Model):
    _inherit = "call.center.campaign"

    authorized_user_ids = fields.Many2many(
        "res.users",
        "call_center_campaign_res_users_rel",
        "call_center_campaign_id",
        "res_users_id",
        string="Authorized Users",
    )
    branch_id = fields.Many2one("call.center.branch", index=True, tracking=True)
    operating_calendar_id = fields.Many2one("resource.calendar", ondelete="restrict")
    calling_hours_policy_id = fields.Many2one(
        "call.center.calling.hours.policy", ondelete="restrict", tracking=True
    )
    country_policy_ids = fields.One2many(
        "call.center.campaign.country.policy", "campaign_id"
    )
    skill_requirement_ids = fields.One2many(
        "call.center.skill.requirement", "campaign_id"
    )
    queue_ids = fields.One2many("call.center.queue", "campaign_id")

    @api.constrains(
        "branch_id", "business_unit_id", "calling_hours_policy_id"
    )
    def _check_foundation_scope(self):
        for campaign in self:
            if (
                campaign.branch_id
                and campaign.business_unit_id not in campaign.branch_id.business_unit_ids
            ):
                raise ValidationError("Campaign branch must include its business unit.")
            if (
                campaign.calling_hours_policy_id
                and campaign.calling_hours_policy_id.company_id
                != campaign.business_unit_id.company_id
            ):
                raise ValidationError(
                    "Campaign and calling-hours policy companies must match."
                )


class CallCenterQueue(models.Model):
    _name = "call.center.queue"
    _description = "Managed Call Center Queue Configuration"
    _inherit = [
        "mail.thread",
        "mail.activity.mixin",
        "call.center.business.unit.mixin",
        "call.center.scoped.audit.mixin",
    ]
    _order = "priority, code"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, index=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    campaign_id = fields.Many2one(
        "call.center.campaign", required=True, ondelete="restrict", index=True
    )
    team_id = fields.Many2one(
        "call.center.team", required=True, ondelete="restrict", index=True
    )
    branch_id = fields.Many2one("call.center.branch", ondelete="restrict", index=True)
    direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound"), ("blended", "Blended")],
        required=True,
        default="inbound",
    )
    queue_type = fields.Selection(
        [
            ("service", "Service"),
            ("sales", "Sales"),
            ("callback", "Callback"),
            ("retention", "Retention"),
            ("overflow", "Overflow"),
            ("specialist", "Specialist"),
        ],
        required=True,
        default="service",
    )
    priority = fields.Integer(default=10)
    service_level_seconds = fields.Integer(default=20)
    maximum_wait_seconds = fields.Integer(default=300)
    maximum_capacity = fields.Integer(default=1)
    overflow_queue_id = fields.Many2one(
        "call.center.queue", ondelete="restrict", index=True
    )
    fallback_destination = fields.Char(
        help="Logical fallback only; this does not configure live telephony."
    )
    skill_requirement_ids = fields.One2many(
        "call.center.skill.requirement", "queue_id"
    )
    allowed_role_codes = fields.Char(
        help="Comma-separated functional role codes; security groups remain authoritative."
    )
    active = fields.Boolean(default=False, tracking=True)
    vicidial_queue_reference = fields.Char(
        string="VICIdial Inbound Group / Queue Reference", index=True
    )
    external_id = fields.Char(index=True, copy=False)
    reconciliation_state = fields.Selection(
        [
            ("not_observed", "Not Observed"),
            ("in_sync", "In Sync"),
            ("drifted", "Drifted"),
            ("blocked", "Blocked"),
        ],
        default="not_observed",
        required=True,
        tracking=True,
        copy=False,
    )
    last_reconciled_at = fields.Datetime(readonly=True, copy=False)
    reconciliation_evidence = fields.Char(readonly=True, copy=False)
    live_membership_authority = fields.Char(
        default="VICIdial/Asterisk",
        readonly=True,
        help="Odoo never owns current callers or live queue membership.",
    )

    _code_company_unique = models.Constraint(
        "unique(company_id, code)", "Queue codes must be unique per company."
    )
    _external_id_unique = models.Constraint(
        "unique(external_id)", "Queue external IDs must be unique."
    )
    _positive_limits = models.Constraint(
        "check(priority >= 0 AND service_level_seconds >= 0 "
        "AND maximum_wait_seconds >= 0 AND maximum_capacity > 0)",
        "Queue limits must be non-negative and capacity must be positive.",
    )

    @api.constrains(
        "company_id",
        "business_unit_id",
        "campaign_id",
        "team_id",
        "branch_id",
        "overflow_queue_id",
    )
    def _check_scope(self):
        for queue in self:
            if queue.company_id != queue.business_unit_id.company_id:
                raise ValidationError("Queue company and business unit must match.")
            if queue.campaign_id.business_unit_id != queue.business_unit_id:
                raise ValidationError("Queue campaign and business unit must match.")
            if queue.team_id.business_unit_id != queue.business_unit_id:
                raise ValidationError("Queue team and business unit must match.")
            if queue.branch_id and queue.business_unit_id not in queue.branch_id.business_unit_ids:
                raise ValidationError("Queue branch must include its business unit.")
            if queue.overflow_queue_id:
                if queue.overflow_queue_id == queue:
                    raise ValidationError("A queue cannot overflow to itself.")
                if queue.overflow_queue_id.business_unit_id != queue.business_unit_id:
                    raise ValidationError("Overflow queues must share a business unit.")

    def write(self, vals):
        tracked = {
            "active",
            "campaign_id",
            "team_id",
            "overflow_queue_id",
            "fallback_destination",
            "reconciliation_state",
        }
        before = {
            record.id: {
                key: record[key].id if record._fields[key].type == "many2one" else record[key]
                for key in tracked & vals.keys()
            }
            for record in self
        }
        result = super().write(vals)
        for record in self:
            if tracked & vals.keys():
                self.env["call.center.audit.event"].sudo().create(
                    {
                        "company_id": record.company_id.id,
                        "business_unit_id": record.business_unit_id.id,
                        "branch_id": record.branch_id.id,
                        "event_type": "queue.changed",
                        "model_name": record._name,
                        "record_id": record.id,
                        "previous_values_json": before[record.id],
                        "new_values_json": {
                            key: (
                                record[key].id
                                if record._fields[key].type == "many2one"
                                else record[key]
                            )
                            for key in tracked & vals.keys()
                        },
                    }
                )
        return result


class CallCenterSkillRequirement(models.Model):
    _name = "call.center.skill.requirement"
    _description = "Campaign or Queue Skill Requirement"
    _inherit = "call.center.scoped.audit.mixin"
    _order = "campaign_id, queue_id, skill_id"

    campaign_id = fields.Many2one(
        "call.center.campaign", ondelete="cascade", index=True
    )
    queue_id = fields.Many2one("call.center.queue", ondelete="cascade", index=True)
    skill_id = fields.Many2one(
        "call.center.skill", required=True, ondelete="restrict", index=True
    )
    minimum_proficiency = fields.Integer(default=1, required=True)
    preferred_proficiency = fields.Integer(default=3, required=True)
    certification_required = fields.Boolean(default=False)
    active = fields.Boolean(default=True)

    _minimum_range = models.Constraint(
        "check(minimum_proficiency >= 1 AND minimum_proficiency <= 5 "
        "AND preferred_proficiency >= 1 AND preferred_proficiency <= 5 "
        "AND preferred_proficiency >= minimum_proficiency)",
        "Skill proficiency must be 1–5 and preferred cannot be below minimum.",
    )

    @api.constrains("campaign_id", "queue_id", "skill_id")
    def _check_owner(self):
        for requirement in self:
            if bool(requirement.campaign_id) == bool(requirement.queue_id):
                raise ValidationError(
                    "A skill requirement must belong to exactly one campaign or queue."
                )
            owner = requirement.campaign_id or requirement.queue_id
            requirement.audit_business_unit_id = owner.business_unit_id
            requirement.audit_company_id = owner.business_unit_id.company_id


class CallCenterCampaignCountryPolicy(models.Model):
    _name = "call.center.campaign.country.policy"
    _description = "Campaign Country and Calling Policy"
    _inherit = "call.center.scoped.audit.mixin"
    _order = "campaign_id, country_id"

    campaign_id = fields.Many2one(
        "call.center.campaign", required=True, ondelete="cascade", index=True
    )
    country_id = fields.Many2one(
        "res.country", required=True, ondelete="restrict", index=True
    )
    policy = fields.Selection(
        [("allowed", "Allowed"), ("blocked", "Blocked")],
        required=True,
        default="blocked",
    )
    international_dialing_allowed = fields.Boolean(default=False)
    calling_hours_policy_id = fields.Many2one(
        "call.center.calling.hours.policy", required=True, ondelete="restrict"
    )
    phone_format_id = fields.Many2one(
        "call.center.phone.format", required=True, ondelete="restrict"
    )
    consent_required = fields.Boolean(default=True)
    dnc_enforced = fields.Boolean(default=True)
    active = fields.Boolean(default=True)

    _campaign_country_unique = models.Constraint(
        "unique(campaign_id, country_id)",
        "A campaign may have only one policy per country.",
    )

    @api.constrains(
        "campaign_id",
        "country_id",
        "calling_hours_policy_id",
        "phone_format_id",
    )
    def _check_scope(self):
        for policy in self:
            if policy.phone_format_id.country_id != policy.country_id:
                raise ValidationError("Phone format and country policy must match.")
            company = policy.campaign_id.business_unit_id.company_id
            if policy.calling_hours_policy_id.company_id != company:
                raise ValidationError(
                    "Country calling-hours policy must share the campaign company."
                )
            policy.audit_business_unit_id = policy.campaign_id.business_unit_id
            policy.audit_company_id = company


class CodestraDisposition(models.Model):
    _name = "codestra.disposition"
    _description = "Shared Codestra Call Disposition"
    _inherit = [
        "mail.thread",
        "call.center.business.unit.mixin",
        "call.center.scoped.audit.mixin",
    ]
    _order = "campaign_id, code"

    code = fields.Char(required=True, index=True, tracking=True)
    name = fields.Char(required=True, tracking=True)
    category = fields.Selection(DISPOSITION_CATEGORIES, required=True, index=True)
    campaign_id = fields.Many2one(
        "call.center.campaign", required=True, ondelete="restrict", index=True
    )
    vicidial_status_code = fields.Char(required=True, index=True)
    canonical_status_id = fields.Many2one(
        "call.center.canonical.status",
        required=True,
        domain="[('layer', '=', 'disposition')]",
        ondelete="restrict",
    )
    human_contact = fields.Boolean(default=False)
    attempt = fields.Boolean(default=True)
    note_required = fields.Boolean(default=False)
    callback_required = fields.Boolean(default=False)
    retry_interval_minutes = fields.Integer(default=0)
    maximum_retries = fields.Integer(default=0)
    stage_change_policy = fields.Selection(
        [
            ("none", "No Stage Change"),
            ("optional", "Optional"),
            ("required", "Required"),
            ("supervisor", "Supervisor Only"),
        ],
        required=True,
        default="none",
    )
    allowed_next_stage_ids = fields.Many2many("crm.stage")
    compliance_block = fields.Boolean(default=False)
    terminal = fields.Boolean(default=False)
    agent_visible = fields.Boolean(default=True)
    supervisor_approval_required = fields.Boolean(default=False)
    active = fields.Boolean(default=True)

    _campaign_code_unique = models.Constraint(
        "unique(campaign_id, code)",
        "Disposition codes must be unique per campaign.",
    )
    _campaign_vicidial_unique = models.Constraint(
        "unique(campaign_id, vicidial_status_code)",
        "VICIdial status mappings must be unique per campaign.",
    )
    _retry_limits = models.Constraint(
        "check(retry_interval_minutes >= 0 AND maximum_retries >= 0)",
        "Disposition retry limits cannot be negative.",
    )

    @api.constrains(
        "campaign_id",
        "business_unit_id",
        "callback_required",
        "maximum_retries",
        "stage_change_policy",
        "allowed_next_stage_ids",
    )
    def _check_mapping(self):
        for disposition in self:
            if disposition.campaign_id.business_unit_id != disposition.business_unit_id:
                raise ValidationError(
                    "Disposition campaign and business unit must match."
                )
            if disposition.callback_required and disposition.maximum_retries < 1:
                raise ValidationError(
                    "Callback dispositions require at least one retry."
                )
            if (
                disposition.stage_change_policy == "required"
                and not disposition.allowed_next_stage_ids
            ):
                raise ValidationError(
                    "Required stage changes need at least one allowed next stage."
                )
            if any(
                not stage.canonical_journey_status_id
                for stage in disposition.allowed_next_stage_ids
            ):
                raise ValidationError(
                    "Every allowed CRM stage must map to a canonical journey status."
                )


class CallCenterAuditEvent(models.Model):
    _inherit = "call.center.audit.event"

    campaign_id = fields.Many2one("call.center.campaign", index=True)


class CrmLead(models.Model):
    _inherit = "crm.lead"

    phone_validation_result = fields.Selection(
        [
            ("not_checked", "Not Checked"),
            ("valid_format", "Valid Format"),
            ("invalid", "Invalid"),
            ("blocked_country", "Blocked Country"),
            ("consent_blocked", "Consent / DNC Blocked"),
        ],
        default="not_checked",
        required=True,
        readonly=True,
        copy=False,
    )
    phone_validation_reason = fields.Char(readonly=True, copy=False)
    phone_number_type = fields.Selection(
        [("mobile", "Mobile"), ("landline", "Landline"), ("unknown", "Unknown")],
        default="unknown",
        readonly=True,
        copy=False,
    )
