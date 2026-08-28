from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CodestraTrainingCourse(models.Model):
    _name = "codestra.training.course"
    _description = "Codestra Training Course"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "code, version desc"
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, index=True, tracking=True)
    version = fields.Integer(required=True, default=1, tracking=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    description = fields.Text()
    passing_score = fields.Float(required=True, default=80.0, tracking=True)
    validity_days = fields.Integer(default=365, required=True)
    active = fields.Boolean(default=True, tracking=True)
    enrollment_ids = fields.One2many("codestra.training.enrollment", "course_id")

    _course_version_unique = models.Constraint(
        "unique(company_id, code, version)",
        "Course code and version must be unique within a company.",
    )

    @api.constrains("passing_score", "validity_days")
    def _check_policy(self):
        for record in self:
            if not 0 <= record.passing_score <= 100:
                raise ValidationError(_("Passing score must be between 0 and 100."))
            if record.validity_days < 0:
                raise ValidationError(_("Validity days cannot be negative."))


class CodestraTrainingEnrollment(models.Model):
    _name = "codestra.training.enrollment"
    _description = "Codestra Training Enrollment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "assigned_at desc, id desc"
    _check_company_auto = True

    course_id = fields.Many2one(
        "codestra.training.course",
        required=True,
        ondelete="restrict",
        check_company=True,
        index=True,
    )
    company_id = fields.Many2one(
        related="course_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        ondelete="restrict",
        check_company=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("assigned", "Assigned"),
            ("in_progress", "In Progress"),
            ("passed", "Passed"),
            ("failed", "Failed"),
            ("expired", "Expired"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="assigned",
        index=True,
        tracking=True,
        copy=False,
    )
    assigned_at = fields.Datetime(required=True, default=fields.Datetime.now, copy=False)
    completed_at = fields.Datetime(copy=False)
    expires_at = fields.Datetime(copy=False, index=True)
    score = fields.Float(tracking=True)
    attempts = fields.Integer(default=0, readonly=True, copy=False)
    agent_acknowledged = fields.Boolean(tracking=True)
    evaluator_id = fields.Many2one("res.users", readonly=True, copy=False)

    _course_employee_unique = models.Constraint(
        "unique(course_id, employee_id)",
        "An employee may be enrolled once in a course version.",
    )

    @api.constrains("score")
    def _check_score(self):
        for record in self:
            if not 0 <= record.score <= 100:
                raise ValidationError(_("Assessment score must be between 0 and 100."))

    def action_start(self):
        for record in self:
            if record.state != "assigned":
                raise UserError(_("Only assigned training can be started."))
            record.state = "in_progress"
        return True

    def action_evaluate(self):
        now = fields.Datetime.now()
        for record in self:
            if record.state not in {"assigned", "in_progress", "failed"}:
                raise UserError(_("This enrollment cannot be evaluated in its current state."))
            passed = record.score >= record.course_id.passing_score
            values = {
                "state": "passed" if passed else "failed",
                "attempts": record.attempts + 1,
                "completed_at": now,
                "evaluator_id": self.env.user.id,
                "expires_at": (
                    fields.Datetime.add(now, days=record.course_id.validity_days)
                    if passed and record.course_id.validity_days
                    else False
                ),
            }
            record.write(values)
        return True

    def action_expire(self):
        for record in self:
            if record.state != "passed":
                raise UserError(_("Only passed certifications can expire."))
            record.state = "expired"
        return True

    def action_cancel(self):
        for record in self:
            if record.state == "passed":
                raise UserError(_("Passed certification evidence cannot be cancelled."))
            record.state = "cancelled"
        return True
