import hashlib

from psycopg2 import IntegrityError

from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..services.canonical_json import content_hash
from ..services.redaction import redact_and_validate


class IntegrationIdempotency(models.Model):
    _name = "codestra.integration.idempotency"
    _description = "Codestra Scoped Idempotency Ledger"

    name = fields.Char(required=True)
    scope = fields.Char(required=True, index=True)
    key_hash = fields.Char(required=True, index=True, readonly=True)
    request_hash = fields.Char(required=True, index=True, readonly=True)
    event_id = fields.Many2one("codestra.integration.event", required=True, ondelete="restrict", readonly=True)
    result_state = fields.Selection([("created", "Created"), ("replay", "Replay"), ("conflict", "Conflict")], default="created", readonly=True)
    result_reference = fields.Char(readonly=True)
    expires_at = fields.Datetime(readonly=True)
    conflict_count = fields.Integer(default=0, readonly=True)
    last_conflict_at = fields.Datetime(readonly=True)

    _scope_key_unique = models.Constraint(
        "UNIQUE(scope, key_hash)", "Idempotency key already exists in this scope."
    )

    def write(self, vals):
        if not self.env.context.get("integration_ledger_write"):
            raise AccessError("Idempotency records are service-managed and immutable.")
        return super().write(vals)

    def unlink(self):
        raise AccessError("Idempotency records cannot be deleted.")

    @api.model
    def register_idempotent_event(self, scope, raw_key, event_type, source, destination, payload, correlation_id=None):
        key_hash = hashlib.sha256(f"{scope}\0{raw_key}".encode()).hexdigest()
        request_hash = content_hash(redact_and_validate(payload))
        existing = self.search([("scope", "=", scope), ("key_hash", "=", key_hash)], limit=1)
        if existing:
            if existing.request_hash == request_hash:
                return {"status": "replay", "created": False, "replay": True,
                        "conflict": False, "event": existing.event_id}
            existing.with_context(integration_ledger_write=True).write({
                "conflict_count": existing.conflict_count + 1,
                "last_conflict_at": fields.Datetime.now(), "result_state": "conflict",
            })
            self.env["codestra.integration.audit"]._append(
                existing.event_id, "idempotency.conflict", "conflict",
                {"scope": scope, "key_hash": key_hash},
            )
            return {"status": "conflict", "created": False, "replay": False,
                    "conflict": True, "event": existing.event_id}
        event = self.env["codestra.integration.event"].register_event(
            event_type, source, destination, payload, correlation_id,
            idempotency_key=key_hash, idempotency_key_hash=key_hash,
        )
        try:
            with self.env.cr.savepoint():
                record = self.create({"name": f"{scope}:{key_hash[:12]}", "scope": scope,
                    "key_hash": key_hash, "request_hash": request_hash,
                    "event_id": event.id, "result_reference": event.event_uuid})
        except IntegrityError:
            event.unlink()
            return self.register_idempotent_event(scope, raw_key, event_type, source, destination, payload, correlation_id)
        return {"status": "created", "created": True, "replay": False,
                "conflict": False, "event": event, "idempotency": record}
