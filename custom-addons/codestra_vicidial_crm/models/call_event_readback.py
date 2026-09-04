from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class VicidialCallEventReadback(models.Model):
    _inherit = "codestra.vicidial.call.event"

    @api.model
    def codestra_readback(self, event_id, tenant_id):
        """Return bounded evidence for one previously accepted call event.

        The endpoint using this method is intentionally read-only.  It exposes
        only identifiers and hashes required by Middleware to reconcile an
        uncertain delivery outcome; phone numbers, notes, recordings, and raw
        payloads are never returned.
        """
        event_id = str(event_id or "").strip()
        tenant_id = str(tenant_id or "").strip()
        if not event_id or len(event_id) > 255:
            raise ValidationError("A bounded call event ID is required.")
        if not tenant_id or len(tenant_id) > 128:
            raise ValidationError("A bounded tenant ID is required.")

        event = self.sudo().search([("idempotency_key", "=", event_id)], limit=1)
        if not event:
            return False
        if not event.call_id or event.call_id.tenant_id != tenant_id:
            raise AccessError("Call event tenant binding rejected.")

        return {
            "schema_version": "1.0",
            "event_id": event.idempotency_key,
            "tenant_id": tenant_id,
            "call_id": event.call_id.call_id,
            "event_type": event.event_type,
            "sequence": event.sequence,
            "processing_state": event.processing_state,
            "payload_hash": event.payload_hash,
            "correlation_id": event.correlation_id,
            "occurred_at": fields.Datetime.to_string(event.occurred_at)
            if event.occurred_at
            else None,
            "call_state": event.call_id.state,
        }
