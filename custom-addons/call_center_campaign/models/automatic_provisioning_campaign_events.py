import hashlib
import uuid

from odoo import models
from odoo.exceptions import AccessError, ValidationError

from .automatic_provisioning_common import (
    DESIGN_REQUEST_EVENT,
    SCHEMA_VERSION,
    canonical_json,
)

class CallCenterCampaignAutomaticProvisioningEvents(models.Model):
    _inherit = "call.center.campaign"

    def _ensure_revision_record(self, event, validation_errors=None):
        self.ensure_one()
        Revision = self.env["call.center.campaign.design.revision"].sudo()
        revision = Revision.search(
            [
                ("integration_uuid", "=", self.integration_uuid),
                ("revision", "=", event.design_request_revision),
            ],
            limit=1,
        )
        if revision:
            if (
                revision.event_uuid != event.event_uuid
                or revision.request_payload_hash != event.payload_hash
                or revision.campaign_id != self
            ):
                raise ValidationError("IMMUTABLE_DESIGN_REVISION_BINDING_CONFLICT")
            return revision
        prior = Revision.search(
            [
                ("campaign_id", "=", self.id),
                ("state", "in", ["requested", "hash_only", "ready", "approved"]),
            ]
        )
        if prior:
            prior._system_write({"state": "superseded"})
        return Revision._create_internal(
            {
                "campaign_id": self.id,
                "integration_uuid": self.integration_uuid,
                "revision": event.design_request_revision,
                "event_uuid": event.event_uuid,
                "environment": event.record_environment.lower(),
                "state": "requested",
                "request_payload_hash": event.payload_hash,
                "validation_errors_json": validation_errors or [],
                "requested_at": event.created_at,
            }
        )

    def _create_design_request_event(self, revision=None):
        self.ensure_one()
        automatic = self.automatic_design_managed or self.env.context.get(
            "_codestra_automatic_default"
        )
        if not automatic:
            return super()._create_design_request_event(revision=revision)
        if (
            not self.purpose_code
            or self.purpose_code == "UNSPECIFIED"
            or self._normalize_purpose_code(self.purpose_code) != self.purpose_code
        ):
            raise ValidationError(
                "Automatic campaign design requires a canonical purpose code."
            )
        if not self.integration_uuid:
            self._write_integration_state({"integration_uuid": str(uuid.uuid4())})
        revision = revision or self.design_request_revision + 1
        event_key = f"{DESIGN_REQUEST_EVENT}:{self.integration_uuid}:{revision}"
        event_uuid = str(uuid.uuid5(uuid.UUID(self.integration_uuid), event_key))
        correlation_id = str(
            uuid.uuid5(uuid.UUID(self.integration_uuid), f"correlation:{event_key}")
        )
        payload = self._design_request_payload(event_uuid, correlation_id)
        digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        Outbox = self.env["codestra.runtime.integration.outbox"].sudo()
        existing = Outbox.search(
            [("deterministic_event_key", "=", event_key)], limit=1
        )
        if existing:
            if existing.payload_hash != digest:
                raise ValidationError("Existing design event has a conflicting payload hash.")
            self._ensure_revision_record(
                existing, payload["validation"]["errors"]
            )
            return existing
        event = Outbox._create_internal(
            {
                "event_uuid": event_uuid,
                "deterministic_event_key": event_key,
                "idempotency_key": event_key,
                "event_type": DESIGN_REQUEST_EVENT,
                "schema_version": SCHEMA_VERSION,
                "record_environment": self.provisioning_environment.upper(),
                "aggregate_type": self._name,
                "aggregate_record_id": self.id,
                "aggregate_uuid": self.integration_uuid,
                "integration_uuid": self.integration_uuid,
                "business_unit_code": self._business_unit_code(),
                "campaign_id": self.id,
                "design_request_revision": revision,
                "payload_json": payload,
                "payload_hash": digest,
                "correlation_id": correlation_id,
                "delivery_state": "pending",
                # A new event is due immediately; only retries need a deadline.
                # A wall-clock deadline can be newer than PostgreSQL now()
                # throughout the transaction that created the campaign.
                "next_attempt_at": False,
            }
        )
        self._write_integration_state(
            {
                "design_request_revision": revision,
                "design_request_state": "pending",
                "last_design_event_uuid": event_uuid,
            }
        )
        reset_values = {"design_approval_reason": False}
        if self.state == "approved":
            reset_values["state"] = "draft"
        self._system_write(reset_values)
        self._ensure_revision_record(event, payload["validation"]["errors"])
        return event

    def action_request_design_preview(self):
        if not self.env.user.has_group("call_center_core.group_call_center_manager"):
            raise AccessError("Only contact-center managers may request campaign designs.")
        self._lock_automatic_design_rows()
        for campaign in self:
            if not campaign.automatic_design_managed:
                campaign._system_write({"automatic_design_managed": True})
            if not campaign.design_automation_enabled:
                campaign.with_context(_codestra_automatic_default=True).write(
                    {"design_automation_enabled": True}
                )
            else:
                campaign._create_design_request_event()
        return True
