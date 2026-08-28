from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CodestraContactCenterShift(models.Model):
    _name = "codestra.cc.shift"
    _description = "Codestra Contact Center Shift"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "start_at desc, employee_id"
    _check_company_auto = True

    name = fields.Char(
        required=True,
        readonly=True,
        copy=False,
        index=True,
        default=lambda self: _("New"),
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        ondelete="restrict",
        check_company=True,
        index=True,
        tracking=True,
    )
    agent_id = fields.Many2one(
        "codestra.vicidial.agent",
        string="Telephony Identity",
        ondelete="restrict",
        tracking=True,
    )
    resource_calendar_id = fields.Many2one(
        "resource.calendar",
        string="Working Schedule",
        ondelete="restrict",
    )
    start_at = fields.Datetime(required=True, index=True, tracking=True)
    end_at = fields.Datetime(required=True, index=True, tracking=True)
    timezone = fields.Char(required=True, default=lambda self: self.env.user.tz or "UTC")
    break_minutes = fields.Integer(default=0, required=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("published", "Published"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="draft",
        index=True,
        tracking=True,
        copy=False,
    )
    attendance_id = fields.Many2one(
        "hr.attendance",
        string="Verified Attendance",
        ondelete="restrict",
        tracking=True,
    )
    planned_hours = fields.Float(compute="_compute_metrics", store=True)
    actual_hours = fields.Float(compute="_compute_metrics", store=True)
    adherence_percent = fields.Float(compute="_compute_metrics", store=True)
    notes = fields.Text()

    _employee_shift_unique = models.Constraint(
        "unique(employee_id, start_at, end_at)",
        "An employee cannot have the same shift interval twice.",
    )

    @api.model_create_multi
    def create(self, values_list):
        sequence = self.env["ir.sequence"]
        for values in values_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = sequence.next_by_code("codestra.cc.shift") or _("New")
        return super().create(values_list)

    @api.constrains("start_at", "end_at", "break_minutes")
    def _check_interval(self):
        for record in self:
            if record.start_at and record.end_at and record.end_at <= record.start_at:
                raise ValidationError(_("Shift end must be after shift start."))
            if record.break_minutes < 0:
                raise ValidationError(_("Break minutes cannot be negative."))
            if record.start_at and record.end_at:
                interval_minutes = (record.end_at - record.start_at).total_seconds() / 60
                if record.break_minutes >= interval_minutes:
                    raise ValidationError(_("Break time must be shorter than the shift."))

    @api.constrains("employee_id", "attendance_id")
    def _check_attendance_employee(self):
        for record in self:
            if record.attendance_id and record.attendance_id.employee_id != record.employee_id:
                raise ValidationError(_("The attendance record must belong to the scheduled employee."))

    @api.depends(
        "start_at",
        "end_at",
        "break_minutes",
        "attendance_id.check_in",
        "attendance_id.check_out",
    )
    def _compute_metrics(self):
        for record in self:
            record.planned_hours = 0.0
            record.actual_hours = 0.0
            record.adherence_percent = 0.0
            if not record.start_at or not record.end_at:
                continue
            planned_seconds = max(
                0.0,
                (record.end_at - record.start_at).total_seconds() - (record.break_minutes * 60),
            )
            record.planned_hours = planned_seconds / 3600
            attendance = record.attendance_id
            if not attendance or not attendance.check_in or not attendance.check_out:
                continue
            overlap_start = max(record.start_at, attendance.check_in)
            overlap_end = min(record.end_at, attendance.check_out)
            actual_seconds = max(0.0, (overlap_end - overlap_start).total_seconds())
            record.actual_hours = actual_seconds / 3600
            if planned_seconds:
                record.adherence_percent = min(100.0, (actual_seconds / planned_seconds) * 100)

    def action_publish(self):
        for record in self:
            if record.state != "draft":
                raise UserError(_("Only draft shifts can be published."))
            record.state = "published"
        return True

    def action_complete(self):
        for record in self:
            if record.state != "published":
                raise UserError(_("Only published shifts can be completed."))
            if record.attendance_id and not record.attendance_id.check_out:
                raise ValidationError(_("An open attendance record cannot finalize adherence."))
            record.state = "completed"
        return True

    def action_cancel(self):
        for record in self:
            if record.state == "completed":
                raise UserError(_("Completed shifts cannot be cancelled."))
            record.state = "cancelled"
        return True

    def action_reset_to_draft(self):
        for record in self:
            if record.state not in {"published", "cancelled"}:
                raise UserError(_("Only published or cancelled shifts can return to draft."))
            record.state = "draft"
        return True
