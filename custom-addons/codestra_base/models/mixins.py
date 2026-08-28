from odoo import fields, models


class ExternalReferenceMixin(models.AbstractModel):
    _name = "codestra.external.reference.mixin"
    _description = "Codestra external reference metadata"
    _abstract = True

    external_reference = fields.Char(index=True, copy=False)
    source_system = fields.Char(index=True, copy=False)


class SyncStateMixin(models.AbstractModel):
    _name = "codestra.sync.state.mixin"
    _description = "Codestra synchronization state"
    _abstract = True

    sync_state = fields.Selection(
        [("clean", "Clean"), ("pending", "Pending"), ("processing", "Processing"),
         ("failed", "Failed"), ("ignored", "Ignored")],
        default="clean", required=True, index=True, copy=False,
    )
    sync_error = fields.Text(copy=False)
    last_sync_at = fields.Datetime(copy=False)
    sync_version = fields.Integer(default=1, copy=False)


class CorrelationMixin(models.AbstractModel):
    _name = "codestra.correlation.mixin"
    _description = "Codestra correlation metadata"
    _abstract = True

    correlation_id = fields.Char(index=True, copy=False)
    idempotency_key = fields.Char(index=True, copy=False)


class AuditMixin(models.AbstractModel):
    _name = "codestra.audit.mixin"
    _description = "Codestra safe business audit metadata"
    _abstract = True

    audit_note = fields.Text(copy=False)
    audit_source = fields.Char(index=True, copy=False)
