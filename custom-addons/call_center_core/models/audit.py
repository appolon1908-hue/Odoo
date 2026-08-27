import json

from odoo import api, fields, models
from odoo.exceptions import AccessError


class CallCenterAuditEvent(models.Model):
    _name = "call.center.audit.event"
    _description = "Call Center Audit Event"
    _order = "occurred_at desc, id desc"
    _log_access = True

    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    actor_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, index=True
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    business_unit_id = fields.Many2one("call.center.business.unit", index=True)
    branch_id = fields.Many2one("call.center.branch", index=True)
    event_type = fields.Char(required=True, index=True)
    model_name = fields.Char(required=True, index=True)
    record_id = fields.Integer(required=True, index=True)
    reason = fields.Char()
    previous_values_json = fields.Text(default="{}")
    new_values_json = fields.Text(default="{}")
    automation_reference = fields.Char(index=True)
    source_system = fields.Char(default="odoo", required=True, index=True)
    correlation_id = fields.Char(index=True)
    idempotency_key = fields.Char(index=True)
    evidence_reference = fields.Char()
    archived = fields.Boolean(default=False)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            for key in ("previous_values_json", "new_values_json"):
                value = values.get(key)
                if value and not isinstance(value, str):
                    values[key] = json.dumps(value, sort_keys=True, default=str)
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Audit events are immutable.")

    def unlink(self):
        raise AccessError("Audit events are immutable.")
