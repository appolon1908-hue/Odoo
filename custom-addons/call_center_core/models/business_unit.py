from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CallCenterBusinessUnit(models.Model):
    _name = "call.center.business.unit"
    _description = "Call Center Business Unit"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sequence, name"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, index=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    manager_id = fields.Many2one("res.users", tracking=True)
    brand = fields.Char(required=True, default="Codestra", tracking=True)
    director_id = fields.Many2one("res.users", tracking=True)
    director_role = fields.Char(required=True, default="Business Unit Director")
    default_currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    default_language_id = fields.Many2one(
        "res.lang",
        required=True,
        default=lambda self: self.env.ref("base.lang_en", raise_if_not_found=False),
    )
    primary_crm_team_id = fields.Many2one("crm.team", ondelete="restrict", tracking=True)
    timezone = fields.Selection(
        selection=lambda self: self._tz_get(),
        default=lambda self: self.env.user.tz or "UTC",
        required=True,
    )
    department_ids = fields.One2many(
        "call.center.department", "business_unit_id", string="Departments"
    )

    _code_unique = models.Constraint(
        "unique(code)", "Business-unit codes must be globally unique."
    )

    @api.model
    def _tz_get(self):
        return self.env["res.users"]._fields["tz"]._description_selection(self.env)

    @api.constrains(
        "primary_crm_team_id",
    )
    def _check_scoped_defaults(self):
        for unit in self:
            scoped = (unit.primary_crm_team_id,)
            for record in filter(None, scoped):
                if (
                    "business_unit_id" in record._fields
                    and record.business_unit_id != unit
                ):
                    raise ValidationError(
                        "Business-unit defaults must belong to the same business unit."
                    )


class CallCenterDepartment(models.Model):
    _name = "call.center.department"
    _description = "Call Center Department"
    _order = "business_unit_id, sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    business_unit_id = fields.Many2one(
        "call.center.business.unit", required=True, ondelete="cascade", index=True
    )
    manager_id = fields.Many2one("res.users")
    member_ids = fields.Many2many("res.users", string="Members")

    _code_unique = models.Constraint(
        "unique(code, business_unit_id)",
        "Department codes must be unique within a business unit.",
    )

    @api.constrains("business_unit_id", "manager_id", "member_ids")
    def _check_user_scope(self):
        for department in self:
            for user in department.manager_id | department.member_ids:
                if (
                    user.call_center_business_unit_ids
                    and department.business_unit_id
                    not in user.call_center_business_unit_ids
                ):
                    raise ValidationError(
                        "Department managers and members must be authorized for "
                        "the department business unit."
                    )


class BusinessUnitMixin(models.AbstractModel):
    _name = "call.center.business.unit.mixin"
    _description = "Business Unit Scoped Record"

    business_unit_id = fields.Many2one(
        "call.center.business.unit",
        required=True,
        index=True,
        default=lambda self: self.env.user.call_center_default_business_unit_id,
    )

    @api.constrains("business_unit_id")
    def _check_user_business_unit(self):
        if self.env.su or self.env.user.has_group("call_center_core.group_call_center_admin"):
            return
        allowed = self.env.user.call_center_business_unit_ids
        for record in self:
            if record.business_unit_id and record.business_unit_id not in allowed:
                raise ValidationError("You are not authorized for this business unit.")
