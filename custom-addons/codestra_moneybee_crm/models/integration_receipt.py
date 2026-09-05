from odoo import api, fields, models
from odoo.exceptions import AccessError


MONEYBEE_RECEIPT_CREATE_TOKEN = object()


class MoneyBeeIntegrationReceipt(models.Model):
    _name = "codestra.moneybee.integration.receipt"
    _description = "MoneyBee Middleware Integration Receipt"
    _order = "received_at desc, id desc"
    _check_company_auto = True

    _moneybee_command_id_uniq = models.Constraint(
        "unique(command_id)",
        "A MoneyBee Middleware command can be applied only once.",
    )

    command_id = fields.Char(required=True, index=True, readonly=True)
    source_event_id = fields.Char(required=True, index=True, readonly=True)
    tenant_id = fields.Char(required=True, index=True, readonly=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        readonly=True,
        ondelete="restrict",
    )
    principal_user_id = fields.Many2one(
        "res.users",
        required=True,
        index=True,
        readonly=True,
        ondelete="restrict",
    )
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
    partner_id = fields.Many2one(
        "res.partner",
        readonly=True,
        ondelete="set null",
        check_company=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        if (
            self.env.context.get("_moneybee_receipt_create_token")
            is not MONEYBEE_RECEIPT_CREATE_TOKEN
        ):
            raise AccessError(
                "MoneyBee command receipts are server-managed and cannot be "
                "created directly."
            )
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(
            "MoneyBee command receipts are immutable and cannot be modified."
        )

    def unlink(self):
        raise AccessError(
            "MoneyBee command receipts are immutable and cannot be deleted."
        )
