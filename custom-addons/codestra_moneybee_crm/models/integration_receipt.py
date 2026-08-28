from odoo import fields, models


class MoneyBeeIntegrationReceipt(models.Model):
    _name = "codestra.moneybee.integration.receipt"
    _description = "MoneyBee Middleware Integration Receipt"
    _order = "received_at desc, id desc"

    _sql_constraints = [
        (
            "moneybee_command_id_uniq",
            "unique(command_id)",
            "A MoneyBee Middleware command can be applied only once.",
        ),
    ]

    command_id = fields.Char(required=True, index=True, readonly=True)
    source_event_id = fields.Char(required=True, index=True, readonly=True)
    tenant_id = fields.Char(required=True, index=True, readonly=True)
    schema_version = fields.Integer(required=True, readonly=True)
    command_type = fields.Char(required=True, index=True, readonly=True)
    payload_hash = fields.Char(required=True, index=True, readonly=True)
    status = fields.Selection(
        [
            ("RECEIVED", "Received"),
            ("APPLIED", "Applied"),
            ("FAILED", "Failed"),
        ],
        required=True,
        default="RECEIVED",
        index=True,
        readonly=True,
    )
    received_at = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )
    applied_at = fields.Datetime(readonly=True)
    error_code = fields.Char(readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True, ondelete="set null")
