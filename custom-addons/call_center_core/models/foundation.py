import re
from datetime import datetime
from zoneinfo import ZoneInfo

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


STATUS_LAYERS = [
    ("journey", "Client / Lead Journey"),
    ("disposition", "Call Attempt Disposition"),
    ("callback", "Callback Lifecycle"),
    ("appointment", "Appointment Lifecycle"),
    ("agent", "Agent Working State"),
    ("consent", "Consent / Compliance State"),
]


class CallCenterScopedAuditMixin(models.AbstractModel):
    _name = "call.center.scoped.audit.mixin"
    _description = "Reusable Call Center Audit Metadata"
    _abstract = True

    audit_company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    audit_business_unit_id = fields.Many2one("call.center.business.unit", index=True)
    audit_branch_id = fields.Many2one("call.center.branch", index=True)
    audit_source_system = fields.Char(default="odoo", required=True, index=True)
    audit_correlation_id = fields.Char(index=True, copy=False)
    audit_idempotency_key = fields.Char(index=True, copy=False)
    audit_reason = fields.Char(copy=False)
    audit_evidence_reference = fields.Char(copy=False)
    audit_archived = fields.Boolean(default=False, copy=False)


class CallCenterBranch(models.Model):
    _name = "call.center.branch"
    _description = "Call Center Branch / Office Location"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "company_id, code"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, index=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    country_id = fields.Many2one("res.country", required=True, index=True)
    state_id = fields.Many2one(
        "res.country.state", domain="[('country_id', '=', country_id)]"
    )
    timezone = fields.Selection(
        selection=lambda self: self.env["res.users"]._fields["tz"]._description_selection(self.env),
        default=lambda self: self.env.user.tz or "UTC",
        required=True,
    )
    street = fields.Char()
    street2 = fields.Char()
    city = fields.Char()
    zip = fields.Char()
    business_unit_ids = fields.Many2many(
        "call.center.business.unit",
        "call_center_branch_business_unit_rel",
        "branch_id",
        "business_unit_id",
        string="Business Units",
    )
    operating_calendar_id = fields.Many2one("resource.calendar", ondelete="restrict")
    calling_hours_policy_id = fields.Many2one(
        "call.center.calling.hours.policy", ondelete="restrict"
    )

    _code_company_unique = models.Constraint(
        "unique(company_id, code)", "Branch codes must be unique per company."
    )

    @api.constrains("company_id", "business_unit_ids", "calling_hours_policy_id")
    def _check_scope(self):
        for branch in self:
            if any(
                unit.company_id != branch.company_id for unit in branch.business_unit_ids
            ):
                raise ValidationError("Branch business units must belong to its company.")
            if (
                branch.calling_hours_policy_id
                and branch.calling_hours_policy_id.company_id != branch.company_id
            ):
                raise ValidationError(
                    "Branch and calling-hours policy companies must match."
                )


class CallCenterDepartment(models.Model):
    _inherit = "call.center.department"

    branch_id = fields.Many2one("call.center.branch", index=True)

    @api.constrains("branch_id", "business_unit_id")
    def _check_branch_scope(self):
        for department in self:
            if (
                department.branch_id
                and department.business_unit_id
                not in department.branch_id.business_unit_ids
            ):
                raise ValidationError(
                    "Department branch must include its business unit."
                )


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    call_center_branch_id = fields.Many2one(
        "call.center.branch", domain="[('company_id', '=', company_id)]", index=True
    )


class CallCenterCanonicalStatus(models.Model):
    _name = "call.center.canonical.status"
    _description = "Canonical Call Center Status"
    _order = "layer, sequence, code"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    layer = fields.Selection(STATUS_LAYERS, required=True, index=True)
    category = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    terminal = fields.Boolean(default=False)
    active = fields.Boolean(default=True)
    description = fields.Text()

    _code_layer_unique = models.Constraint(
        "unique(layer, code)", "Canonical status codes must be unique per layer."
    )


class CallCenterStatusTransition(models.Model):
    _name = "call.center.status.transition"
    _description = "Allowed Canonical Status Transition"
    _order = "from_status_id, to_status_id"

    from_status_id = fields.Many2one(
        "call.center.canonical.status",
        required=True,
        ondelete="restrict",
        index=True,
    )
    to_status_id = fields.Many2one(
        "call.center.canonical.status",
        required=True,
        ondelete="restrict",
        index=True,
    )
    requires_reason = fields.Boolean(default=False)
    supervisor_only = fields.Boolean(default=False)
    active = fields.Boolean(default=True)

    _transition_unique = models.Constraint(
        "unique(from_status_id, to_status_id)", "Status transitions must be unique."
    )
    _different_status = models.Constraint(
        "check(from_status_id != to_status_id)", "A transition must change status."
    )

    @api.constrains("from_status_id", "to_status_id")
    def _check_layer(self):
        for transition in self:
            if transition.from_status_id.layer != transition.to_status_id.layer:
                raise ValidationError(
                    "Canonical transitions cannot cross status layers."
                )


class CallCenterStatusTransitionAudit(models.Model):
    _name = "call.center.status.transition.audit"
    _description = "Immutable Canonical Status Transition Audit"
    _inherit = "call.center.scoped.audit.mixin"
    _order = "changed_at desc, id desc"

    changed_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True
    )
    actor_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, index=True
    )
    model_name = fields.Char(required=True, index=True)
    record_id = fields.Integer(required=True, index=True)
    previous_status_id = fields.Many2one(
        "call.center.canonical.status", required=True, ondelete="restrict"
    )
    new_status_id = fields.Many2one(
        "call.center.canonical.status", required=True, ondelete="restrict"
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            previous = self.env["call.center.canonical.status"].browse(
                values.get("previous_status_id")
            )
            new = self.env["call.center.canonical.status"].browse(
                values.get("new_status_id")
            )
            transition = self.env["call.center.status.transition"].search(
                [
                    ("from_status_id", "=", previous.id),
                    ("to_status_id", "=", new.id),
                    ("active", "=", True),
                ],
                limit=1,
            )
            if not transition:
                raise ValidationError(
                    "This canonical status transition is not allowed."
                )
            if transition.requires_reason and not values.get("audit_reason"):
                raise ValidationError("This transition requires a reason.")
            if transition.supervisor_only and not (
                self.env.su
                or self.env.user.has_group(
                    "call_center_core.group_call_center_supervisor"
                )
            ):
                raise AccessError("This transition requires a supervisor.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Status transition audit records are immutable.")

    def unlink(self):
        raise AccessError("Status transition audit records are immutable.")


class CrmStage(models.Model):
    _inherit = "crm.stage"

    canonical_journey_status_id = fields.Many2one(
        "call.center.canonical.status",
        domain="[('layer', '=', 'journey')]",
        ondelete="restrict",
        index=True,
    )


class CallCenterOperatingPeriod(models.Model):
    _name = "call.center.operating.period"
    _description = "Calling-Hours Operating Period"
    _order = "policy_id, weekday, hour_from"

    policy_id = fields.Many2one(
        "call.center.calling.hours.policy",
        required=True,
        ondelete="cascade",
        index=True,
    )
    weekday = fields.Selection(
        [
            ("0", "Monday"),
            ("1", "Tuesday"),
            ("2", "Wednesday"),
            ("3", "Thursday"),
            ("4", "Friday"),
            ("5", "Saturday"),
            ("6", "Sunday"),
        ],
        required=True,
        index=True,
    )
    hour_from = fields.Float(required=True)
    hour_to = fields.Float(required=True)
    overnight = fields.Boolean(default=False)

    @api.constrains("hour_from", "hour_to", "overnight")
    def _check_hours(self):
        for period in self:
            if not (0 <= period.hour_from < 24 and 0 <= period.hour_to <= 24):
                raise ValidationError(
                    "Operating-period hours must be within 0–24."
                )
            if period.overnight:
                if period.hour_from <= period.hour_to:
                    raise ValidationError(
                        "Overnight periods must cross midnight."
                    )
            elif period.hour_from >= period.hour_to:
                raise ValidationError(
                    "Daytime periods require start before end."
                )


class CallCenterCalendarException(models.Model):
    _name = "call.center.calendar.exception"
    _description = "Calling-Hours Holiday or Exceptional Closure"
    _order = "date_from desc"

    name = fields.Char(required=True)
    policy_id = fields.Many2one(
        "call.center.calling.hours.policy",
        required=True,
        ondelete="cascade",
        index=True,
    )
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    exception_type = fields.Selection(
        [
            ("closure", "Closed"),
            ("holiday", "Holiday"),
            ("special_hours", "Special Hours"),
        ],
        default="closure",
        required=True,
    )
    hour_from = fields.Float()
    hour_to = fields.Float()
    reason = fields.Char(required=True)

    @api.constrains(
        "date_from", "date_to", "exception_type", "hour_from", "hour_to"
    )
    def _check_exception(self):
        for exception in self:
            if exception.date_to < exception.date_from:
                raise ValidationError(
                    "Exception end date cannot precede start date."
                )
            if exception.exception_type == "special_hours" and not (
                0 <= exception.hour_from < exception.hour_to <= 24
            ):
                raise ValidationError(
                    "Special hours require a valid increasing range."
                )


class CallCenterCallingHoursPolicy(models.Model):
    _name = "call.center.calling.hours.policy"
    _description = "Call Center Calling-Hours Policy"
    _inherit = ["mail.thread", "call.center.scoped.audit.mixin"]
    _order = "company_id, code"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    timezone = fields.Selection(
        selection=lambda self: self.env["res.users"]._fields["tz"]._description_selection(self.env),
        required=True,
        default="UTC",
    )
    effective_from = fields.Date()
    effective_to = fields.Date()
    resource_calendar_id = fields.Many2one("resource.calendar", ondelete="restrict")
    period_ids = fields.One2many("call.center.operating.period", "policy_id")
    exception_ids = fields.One2many("call.center.calendar.exception", "policy_id")
    country_ids = fields.Many2many(
        "res.country", string="Permitted Countries"
    )
    supervisor_override_allowed = fields.Boolean(default=False)

    _code_company_unique = models.Constraint(
        "unique(company_id, code)",
        "Calling-hours policy codes must be unique per company.",
    )

    @api.constrains("effective_from", "effective_to")
    def _check_dates(self):
        for policy in self:
            if (
                policy.effective_from
                and policy.effective_to
                and policy.effective_to < policy.effective_from
            ):
                raise ValidationError(
                    "Policy end date cannot precede its start date."
                )

    def evaluate(self, moment=None, country=None, override=False, reason=None):
        self.ensure_one()
        moment = moment or fields.Datetime.now()
        if not isinstance(moment, datetime):
            moment = fields.Datetime.to_datetime(moment)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=ZoneInfo("UTC"))
        local = moment.astimezone(ZoneInfo(self.timezone))
        local_date = local.date()
        allowed = self.active
        decision_reason = "within_operating_period"
        if self.effective_from and local_date < self.effective_from:
            allowed, decision_reason = False, "before_effective_date"
        elif self.effective_to and local_date > self.effective_to:
            allowed, decision_reason = False, "after_effective_date"
        elif country and self.country_ids and country not in self.country_ids:
            allowed, decision_reason = False, "country_not_permitted"
        exception = self.exception_ids.filtered(
            lambda item: item.date_from <= local_date <= item.date_to
        )[:1]
        local_hour = local.hour + local.minute / 60
        if allowed and exception:
            if exception.exception_type in ("closure", "holiday"):
                allowed, decision_reason = False, exception.exception_type
            else:
                allowed = (
                    exception.hour_from <= local_hour < exception.hour_to
                )
                decision_reason = (
                    "special_hours" if allowed else "outside_special_hours"
                )
        if allowed and not exception:
            weekday = str(local.weekday())
            matching = self.period_ids.filtered(
                lambda item: item.weekday == weekday
            )
            previous_weekday = str((local.weekday() - 1) % 7)
            previous_overnight = self.period_ids.filtered(
                lambda item: item.weekday == previous_weekday and item.overnight
            )
            allowed = any(
                period.hour_from <= local_hour < period.hour_to
                if not period.overnight
                else local_hour >= period.hour_from
                for period in matching
            ) or any(
                local_hour < period.hour_to for period in previous_overnight
            )
            decision_reason = (
                "within_operating_period"
                if allowed
                else "outside_operating_period"
            )
        override_used = False
        if not allowed and override:
            if not self.supervisor_override_allowed:
                raise ValidationError(
                    "Supervisor override is disabled for this policy."
                )
            if not reason:
                raise ValidationError(
                    "Supervisor override requires a reason."
                )
            if not (
                self.env.su
                or self.env.user.has_group(
                    "call_center_core.group_call_center_supervisor"
                )
            ):
                raise AccessError("Only supervisors may override calling hours.")
            allowed, override_used, decision_reason = (
                True,
                True,
                "supervisor_override",
            )
        audit = self.env["call.center.calling.hours.decision"].sudo().create(
            {
                "policy_id": self.id,
                "evaluated_at": moment.astimezone(
                    ZoneInfo("UTC")
                ).replace(tzinfo=None),
                "country_id": country.id if country else False,
                "allowed": allowed,
                "decision_reason": decision_reason,
                "override_used": override_used,
                "override_reason": reason if override_used else False,
            }
        )
        return {
            "allowed": allowed,
            "reason": decision_reason,
            "audit_id": audit.id,
        }


class CallCenterCallingHoursDecision(models.Model):
    _name = "call.center.calling.hours.decision"
    _description = "Immutable Calling-Hours Decision Audit"
    _inherit = "call.center.scoped.audit.mixin"
    _order = "evaluated_at desc, id desc"

    policy_id = fields.Many2one(
        "call.center.calling.hours.policy",
        required=True,
        ondelete="restrict",
        index=True,
    )
    evaluated_at = fields.Datetime(required=True, index=True)
    country_id = fields.Many2one("res.country")
    allowed = fields.Boolean(required=True)
    decision_reason = fields.Char(required=True)
    override_used = fields.Boolean(default=False)
    override_reason = fields.Char()
    actor_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, index=True
    )

    def write(self, vals):
        raise AccessError("Calling-hours decisions are immutable.")

    def unlink(self):
        raise AccessError("Calling-hours decisions are immutable.")


class CallCenterPhoneFormat(models.Model):
    _name = "call.center.phone.format"
    _description = "Country Phone Format and Normalization Policy"
    _order = "country_id"

    name = fields.Char(required=True)
    country_id = fields.Many2one(
        "res.country", required=True, ondelete="restrict", index=True
    )
    country_calling_code = fields.Char(required=True)
    national_lengths = fields.Char(
        required=True,
        help="Comma-separated permitted national-number lengths.",
    )
    permitted_prefixes = fields.Char(
        help="Comma-separated national prefixes."
    )
    trunk_prefix = fields.Char(default="0")
    mobile_prefixes = fields.Char(
        help="Comma-separated authoritative mobile prefixes."
    )
    landline_prefixes = fields.Char(
        help="Comma-separated authoritative landline prefixes."
    )
    strip_non_digits = fields.Boolean(default=True)
    active = fields.Boolean(default=True)

    _country_unique = models.Constraint(
        "unique(country_id)",
        "Only one phone-format policy is allowed per country.",
    )

    def normalize(self, value):
        self.ensure_one()
        raw = (value or "").strip()
        if not raw:
            return {
                "valid": False,
                "reason": "empty",
                "e164": False,
                "number_type": "unknown",
            }
        digits = re.sub(r"\D", "", raw)
        calling_code = re.sub(r"\D", "", self.country_calling_code)
        if raw.startswith("+"):
            if not digits.startswith(calling_code):
                return {
                    "valid": False,
                    "reason": "country_code_mismatch",
                    "e164": False,
                    "number_type": "unknown",
                }
            national = digits[len(calling_code) :]
        else:
            national = digits
            trunk = re.sub(r"\D", "", self.trunk_prefix or "")
            if trunk and national.startswith(trunk):
                national = national[len(trunk) :]
        lengths = {
            int(item.strip())
            for item in self.national_lengths.split(",")
            if item.strip().isdigit()
        }
        if len(national) not in lengths:
            return {
                "valid": False,
                "reason": "invalid_national_length",
                "e164": False,
                "number_type": "unknown",
            }
        prefixes = [
            item.strip()
            for item in (self.permitted_prefixes or "").split(",")
            if item.strip()
        ]
        if prefixes and not any(
            national.startswith(prefix) for prefix in prefixes
        ):
            return {
                "valid": False,
                "reason": "prefix_not_permitted",
                "e164": False,
                "number_type": "unknown",
            }
        mobile = [
            item.strip()
            for item in (self.mobile_prefixes or "").split(",")
            if item.strip()
        ]
        landline = [
            item.strip()
            for item in (self.landline_prefixes or "").split(",")
            if item.strip()
        ]
        number_type = (
            "mobile"
            if any(national.startswith(prefix) for prefix in mobile)
            else (
                "landline"
                if any(national.startswith(prefix) for prefix in landline)
                else "unknown"
            )
        )
        return {
            "valid": True,
            "reason": "valid_format",
            "e164": f"+{calling_code}{national}",
            "number_type": number_type,
        }


class CallCenterSkillCategory(models.Model):
    _name = "call.center.skill.category"
    _description = "Call Center Skill Category"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        "unique(code)", "Skill-category codes must be unique."
    )


class CallCenterSkill(models.Model):
    _name = "call.center.skill"
    _description = "Managed Call Center Skill"
    _order = "category_id, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    category_id = fields.Many2one(
        "call.center.skill.category",
        required=True,
        ondelete="restrict",
        index=True,
    )
    skill_type = fields.Selection(
        [
            ("language", "Language"),
            ("product", "Product"),
            ("role", "Role"),
            ("compliance", "Compliance / Certification"),
            ("technical", "Technical"),
        ],
        required=True,
        default="product",
    )
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        "unique(code)", "Skill codes must be unique."
    )


class CallCenterAgentSkill(models.Model):
    _name = "call.center.agent.skill"
    _description = "Agent Skill Assignment"
    _inherit = ["mail.thread", "call.center.scoped.audit.mixin"]
    _order = "user_id, skill_id"

    user_id = fields.Many2one(
        "res.users", required=True, ondelete="cascade", index=True
    )
    skill_id = fields.Many2one(
        "call.center.skill", required=True, ondelete="restrict", index=True
    )
    proficiency = fields.Integer(default=1, required=True)
    language_level = fields.Selection(
        [
            ("a1", "A1"),
            ("a2", "A2"),
            ("b1", "B1"),
            ("b2", "B2"),
            ("c1", "C1"),
            ("c2", "C2"),
            ("native", "Native"),
        ]
    )
    certified = fields.Boolean(default=False)
    certification_reference = fields.Char()
    certification_expires_on = fields.Date()
    assigned_by_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, required=True
    )
    assigned_at = fields.Datetime(
        default=fields.Datetime.now, required=True
    )
    active = fields.Boolean(default=True)

    _user_skill_unique = models.Constraint(
        "unique(user_id, skill_id)",
        "A skill may be assigned to an agent only once.",
    )
    _proficiency_range = models.Constraint(
        "check(proficiency >= 1 AND proficiency <= 5)",
        "Skill proficiency must be between 1 and 5.",
    )

    @api.constrains(
        "certified", "certification_reference", "certification_expires_on"
    )
    def _check_certification(self):
        for assignment in self:
            if assignment.certified and not assignment.certification_reference:
                raise ValidationError(
                    "Certified skills require a certification reference."
                )


class ResUsers(models.Model):
    _inherit = "res.users"

    call_center_agent_skill_ids = fields.One2many(
        "call.center.agent.skill", "user_id", string="Managed Skills"
    )
