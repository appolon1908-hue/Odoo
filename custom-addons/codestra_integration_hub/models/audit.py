from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from ..services.canonical_json import canonical_json, content_hash
from ..services.redaction import redact_and_validate


class IntegrationAudit(models.Model):
    _inherit = "codestra.integration.audit"
    _order = "id desc"

    name = fields.Char(required=True, readonly=True)
    event_id = fields.Many2one("codestra.integration.event", ondelete="restrict", readonly=True, index=True)
    actor_id = fields.Many2one("res.users", readonly=True)
    actor_role = fields.Char(readonly=True)
    result = fields.Char(readonly=True)
    payload_hash = fields.Char(readonly=True)
    metadata_redacted = fields.Text(readonly=True)
    previous_hash = fields.Char(readonly=True)
    record_hash = fields.Char(required=True, readonly=True, index=True)

    @api.model
    def _append(self, event, action, result, metadata):
        clean = redact_and_validate(metadata)
        previous = self.search([], order="id desc", limit=1)
        values = {
            "name": f"{action}:{event.event_uuid or event.id}", "event_id": event.id,
            "action": action, "actor_id": self.env.user.id,
            "actor_user_id": self.env.user.id, "actor_role": "system" if self.env.is_superuser() else "user",
            "result": result, "success": result == "success",
            "correlation_id": event.correlation_id, "payload_hash": event.payload_hash,
            "metadata_redacted": canonical_json(clean), "previous_hash": previous.record_hash or "",
            "occurred_at": fields.Datetime.now(),
        }
        values["record_hash"] = content_hash({key: values[key] for key in sorted(values) if key != "record_hash"})
        return self.with_context(integration_audit_create=True).create(values)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("integration_audit_create"):
            raise AccessError("Audit records may only be appended by Integration Hub services.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Integration audit is append-only.")

    def unlink(self):
        raise AccessError("Integration audit is append-only.")

    def verify_chain(self):
        previous = ""
        for record in self.search([], order="id asc"):
            if record.previous_hash != previous:
                raise ValidationError("Integration audit chain verification failed.")
            expected = content_hash({
                "name": record.name, "event_id": record.event_id.id,
                "action": record.action, "actor_id": record.actor_id.id,
                "actor_user_id": record.actor_user_id.id,
                "actor_role": record.actor_role, "result": record.result,
                "success": record.success, "correlation_id": record.correlation_id,
                "payload_hash": record.payload_hash,
                "metadata_redacted": record.metadata_redacted,
                "previous_hash": record.previous_hash, "occurred_at": record.occurred_at,
            })
            if record.record_hash != expected:
                raise ValidationError("Integration audit record hash verification failed.")
            previous = record.record_hash
        return True
