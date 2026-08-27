import uuid

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..services.canonical_json import canonical_json, content_hash
from ..services.redaction import redact_and_validate


class IntegrationEvent(models.Model):
    _name = "codestra.integration.event"
    _inherit = ["codestra.integration.event", "codestra.audit.mixin"]

    event_uuid = fields.Char(required=True, default=lambda self: str(uuid.uuid4()), index=True, copy=False)
    source = fields.Char(required=True, index=True)
    destination = fields.Char(required=True, index=True)
    causation_id = fields.Char(index=True, copy=False)
    idempotency_key_hash = fields.Char(index=True, copy=False)
    payload_redacted = fields.Text(readonly=True, copy=False)
    schema_version = fields.Char(default="1", required=True)
    attempt_count = fields.Integer(default=0, copy=False)
    max_attempts = fields.Integer(default=3)
    processing_started_at = fields.Datetime(copy=False)
    validated_at = fields.Datetime(copy=False)
    queued_at = fields.Datetime(copy=False)
    failed_at = fields.Datetime(copy=False)
    ignored_at = fields.Datetime(copy=False)
    last_error_code = fields.Char(copy=False)
    last_error_message = fields.Text(copy=False)
    active = fields.Boolean(default=True)
    delivery_ids = fields.One2many("codestra.integration.delivery", "event_id")

    _event_uuid_unique = models.Constraint("UNIQUE(event_uuid)", "Event UUID must be unique.")
    _attempt_count_nonnegative = models.Constraint(
        "CHECK(attempt_count >= 0 AND max_attempts >= 0)",
        "Attempt counts cannot be negative.",
    )

    @api.constrains("state", "dead_letter_id")
    def _check_dead_letter_state(self):
        for record in self:
            if record.state == "dead_letter" and not record.dead_letter_id:
                raise ValidationError("Dead-letter events require a dead-letter record.")

    @api.model_create_multi
    def create(self, vals_list):
        clean = []
        for vals in vals_list:
            vals = dict(vals)
            if "payload" in vals:
                payload = vals.pop("payload")
                redacted = redact_and_validate(payload)
                vals["payload_redacted"] = canonical_json(redacted)
                vals["payload_json"] = vals["payload_redacted"]
                vals["payload_hash"] = content_hash(redacted)
            clean.append(vals)
        return super().create(clean)

    def write(self, vals):
        vals = dict(vals)
        if "payload" in vals:
            payload = vals.pop("payload")
            redacted = redact_and_validate(payload)
            vals.update(
                payload_redacted=canonical_json(redacted),
                payload_json=canonical_json(redacted),
                payload_hash=content_hash(redacted),
            )
        for record in self:
            if record.state == "processed" and vals.get("state") == "processing":
                raise ValidationError("Processed events cannot return to processing.")
            if record.state == "ignored" and vals.get("state") in ("queued", "processing", "retry"):
                raise ValidationError("Ignored events cannot be retried.")
        return super().write(vals)

    @api.model
    def register_event(self, event_type, source, destination, payload, correlation_id=None, **values):
        redacted = redact_and_validate(payload)
        payload_digest = content_hash(redacted)
        event_uuid = values.pop("event_uuid", str(uuid.uuid4()))
        return self.create({
            "name": self.env["ir.sequence"].next_by_code("codestra.integration.event") or event_uuid,
            "event_uuid": event_uuid,
            "event_type": event_type,
            "source": source,
            "destination": destination,
            "source_system": source,
            "destination_system": destination,
            "correlation_id": correlation_id,
            "idempotency_key": values.pop("idempotency_key", event_uuid),
            "payload_redacted": canonical_json(redacted),
            "payload_json": canonical_json(redacted),
            "payload_hash": payload_digest,
            **values,
        })

    def _transition(self, allowed, target, timestamp_field=None, extra=None):
        self.ensure_one()
        if self.state not in allowed:
            raise ValidationError(f"Illegal event transition: {self.state} -> {target}.")
        vals = {"state": target, **(extra or {})}
        if timestamp_field:
            vals[timestamp_field] = fields.Datetime.now()
        self.write(vals)
        self.env["codestra.integration.audit"]._append(
            self, f"event.{target}", "success", {"state": target}
        )
        return self

    def validate_event(self):
        return self._transition(("new",), "validated", "validated_at")

    def queue_event(self):
        return self._transition(("validated", "retry"), "queued", "queued_at")

    def mark_processing(self):
        return self._transition(("queued",), "processing", "processing_started_at")

    def mark_processed(self):
        return self._transition(("processing",), "processed", "processed_at")

    def schedule_retry(self, error_code=None, error_message=None, next_retry_at=None):
        self.ensure_one()
        if self.state == "ignored":
            raise ValidationError("Ignored events cannot be retried.")
        next_count = self.attempt_count + 1
        if next_count >= self.max_attempts:
            return self.mark_failed(error_code, error_message)
        return self._transition(
            ("processing", "failed"), "retry", extra={
                "attempt_count": next_count,
                "retry_count": next_count,
                "next_retry_at": next_retry_at,
                "last_error_code": error_code,
                "last_error_message": error_message,
                "last_error": error_message,
            },
        )

    def mark_failed(self, error_code=None, error_message=None):
        return self._transition(
            ("processing", "retry", "queued"), "failed", "failed_at",
            {"last_error_code": error_code, "last_error_message": error_message,
             "last_error": error_message},
        )

    def move_to_dead_letter(self, reason_code, reason):
        self.ensure_one()
        if self.state not in ("failed", "retry"):
            raise ValidationError("Only failed or retry events can be dead-lettered.")
        dead = self.env["codestra.integration.dead.letter"].create_for_event(
            self, reason_code, reason
        )
        return self._transition(("failed", "retry"), "dead_letter", extra={"dead_letter_id": dead.id})

    def mark_ignored(self, reason=None):
        return self._transition(
            ("new", "validated", "queued", "failed"), "ignored", "ignored_at",
            {"last_error_message": reason},
        )

    @api.model
    def _cron_report_retry_eligible(self):
        return self.search_count([("state", "=", "retry"), ("active", "=", True)])
