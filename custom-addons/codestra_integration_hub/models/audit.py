import json

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
    def _append(
        self,
        event,
        action,
        result,
        metadata,
        *,
        actor_role=None,
        correlation_id=None,
        subject_model=None,
        subject_id=None,
    ):
        """Append one actor-attributed record to the globally serialized chain."""
        if not isinstance(metadata, dict):
            raise ValidationError("Audit metadata must be an object.")
        if actor_role not in {
            None,
            "system",
            "user",
            "agent",
            "supervisor",
            "qa",
            "admin",
            "service",
        }:
            raise ValidationError("Audit actor role is invalid.")

        actor_user_id = self.env.user.id
        if event:
            event.ensure_one()
            event = event.exists()
            if not event:
                raise ValidationError("Audit event anchor is unavailable.")
            if correlation_id and event.correlation_id != correlation_id:
                raise ValidationError("Audit correlation does not match the event anchor.")
            correlation_id = event.correlation_id

        subject_model = subject_model or metadata.get("model_name")
        subject_id = subject_id or metadata.get("record_res_id")
        correlation_id = (correlation_id or "").strip()
        if not event and (not correlation_id or not subject_model or not subject_id):
            raise ValidationError("Eventless audits require correlation and subject anchors.")

        enriched_metadata = dict(metadata)
        enriched_metadata["_audit_projection_version"] = 1
        if subject_model:
            enriched_metadata.setdefault("model_name", subject_model)
        if subject_id:
            enriched_metadata.setdefault("record_res_id", int(subject_id))
        clean = redact_and_validate(enriched_metadata)

        if event:
            name = f"{action}:{event.event_uuid or event.id}"
            payload_hash = event.payload_hash
        else:
            name = f"{action}:{correlation_id}:{subject_model}:{int(subject_id)}"
            payload_hash = content_hash(
                {
                    "correlation_id": correlation_id,
                    "subject_model": subject_model,
                    "subject_id": int(subject_id),
                    "metadata": clean,
                }
            )

        writer = self.sudo()
        writer.env.cr.execute(
            """
            SELECT id
              FROM ir_module_module
             WHERE name = %s
             FOR UPDATE
            """,
            ["codestra_integration_hub"],
        )
        if not writer.env.cr.fetchone():
            raise ValidationError("Integration audit chain lock is unavailable.")

        previous = writer.search([], order="id desc", limit=1)
        values = {
            "name": name,
            "event_id": event.id if event else False,
            "action": action,
            "actor_id": actor_user_id,
            "actor_user_id": actor_user_id,
            "actor_role": actor_role or ("system" if self.env.is_superuser() else "user"),
            "result": result,
            "success": result == "success",
            "correlation_id": correlation_id,
            "payload_hash": payload_hash,
            "metadata_redacted": canonical_json(clean),
            "previous_hash": previous.record_hash or "",
            "occurred_at": fields.Datetime.now(),
            "model_name": subject_model or False,
            "record_res_id": int(subject_id) if subject_id else False,
            "after_json": canonical_json(clean.get("after", {})) if "after" in clean else False,
        }
        hashed_values = {
            key: values[key]
            for key in (
                "name",
                "event_id",
                "action",
                "actor_id",
                "actor_user_id",
                "actor_role",
                "result",
                "success",
                "correlation_id",
                "payload_hash",
                "metadata_redacted",
                "previous_hash",
                "occurred_at",
            )
        }
        values["record_hash"] = content_hash(hashed_values)
        return writer.with_context(integration_audit_create=True).create(values)

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

            try:
                metadata = json.loads(record.metadata_redacted or "{}")
            except (TypeError, ValueError) as exc:
                raise ValidationError("Integration audit metadata is not canonical JSON.") from exc
            if metadata.get("_audit_projection_version") == 1:
                projected_model = metadata.get("model_name") or False
                projected_res_id = int(metadata.get("record_res_id") or 0) or False
                projected_after = (
                    canonical_json(metadata["after"])
                    if "after" in metadata
                    else False
                )
                if (
                    record.model_name != projected_model
                    or record.record_res_id != projected_res_id
                    or record.after_json != projected_after
                ):
                    raise ValidationError("Integration audit projection verification failed.")
            previous = record.record_hash
        return True
