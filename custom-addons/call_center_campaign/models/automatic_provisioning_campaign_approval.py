import hashlib
import uuid

from odoo import fields, models
from odoo.exceptions import AccessError, ValidationError

from .automatic_provisioning_common import (
    APPROVAL_EVENT,
    DESIGN_MANIFEST_SCHEMA,
    SCHEMA_VERSION,
    canonical_json,
)

class CallCenterCampaignAutomaticProvisioningApproval(models.Model):
    _inherit = "call.center.campaign"

    def _validate_design_approval(self):
        self.ensure_one()
        revision = self.current_design_revision_id
        if not self.design_automation_enabled or not revision:
            raise ValidationError("Campaign design preview has not been requested.")
        if revision.revision != self.design_request_revision:
            raise ValidationError("Campaign design preview is stale.")
        if revision.state != "ready" or not revision.manifest_json:
            raise ValidationError("A complete middleware design preview is required.")
        local_errors = self._design_validation_errors()
        if local_errors:
            raise ValidationError(
                "Campaign design required inputs remain incomplete: "
                + ", ".join(local_errors)
            )
        if revision.validation_errors_json:
            raise ValidationError("Campaign design validation errors must be resolved.")
        reason = (self.design_approval_reason or "").strip()
        if not reason:
            raise ValidationError("A design approval reason is required.")
        revision._validate_manifest(revision.manifest_json)
        return True

    def _create_approval_event(self, revision, approved_at):
        self.ensure_one()
        event_key = (
            f"{self.provisioning_environment}:{self.integration_uuid}:"
            f"{revision.revision}:{APPROVAL_EVENT}"
        )
        event_uuid = str(uuid.uuid5(uuid.UUID(self.integration_uuid), event_key))
        correlation_id = str(
            uuid.uuid5(uuid.UUID(self.integration_uuid), f"correlation:{event_key}")
        )
        payload = {
            "schema_version": DESIGN_MANIFEST_SCHEMA,
            "event_id": event_uuid,
            "event_type": APPROVAL_EVENT,
            "environment": self.provisioning_environment,
            "integration_uuid": self.integration_uuid,
            "odoo_campaign_id": self.id,
            "campaign_code": self.code,
            "business_unit": self._business_unit_code(),
            "design_revision": revision.revision,
            "manifest_hash": revision.manifest_hash,
            "approved_by_user_id": self.env.user.id,
            "approved_at": fields.Datetime.to_string(approved_at),
            "audit_reason": self.design_approval_reason.strip(),
            "feature_flags": {
                "lead_publication": False,
                "agent_sync": False,
                "live_call_control": False,
                "production_dialing": False,
            },
        }
        digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        Outbox = self.env["codestra.runtime.integration.outbox"].sudo()
        existing = Outbox.search(
            [("deterministic_event_key", "=", event_key)], limit=1
        )
        if existing:
            if existing.payload_hash != digest:
                raise ValidationError("IMMUTABLE_APPROVAL_EVENT_BINDING_CONFLICT")
            return existing
        return Outbox._create_internal(
            {
                "event_uuid": event_uuid,
                "deterministic_event_key": event_key,
                "idempotency_key": event_key,
                "event_type": APPROVAL_EVENT,
                "schema_version": SCHEMA_VERSION,
                "record_environment": self.provisioning_environment.upper(),
                "aggregate_type": self._name,
                "aggregate_record_id": self.id,
                "aggregate_uuid": self.integration_uuid,
                "integration_uuid": self.integration_uuid,
                "business_unit_code": self._business_unit_code(),
                "campaign_id": self.id,
                "design_request_revision": revision.revision,
                "payload_json": payload,
                "payload_hash": digest,
                "correlation_id": correlation_id,
                "delivery_state": "pending",
                "next_attempt_at": fields.Datetime.now(),
            }
        )

    def _finalize_design_approval(self):
        self.ensure_one()
        revision = self.current_design_revision_id
        self._validate_design_approval()
        approved_at = revision.approved_at or fields.Datetime.now()
        event = self._create_approval_event(revision, approved_at)
        revision._system_write(
            {
                "state": "approved",
                "approved_by": self.env.user.id,
                "approved_at": approved_at,
                "approval_reason": self.design_approval_reason.strip(),
            }
        )
        self._system_write({"last_approval_event_uuid": event.event_uuid})
        return event

    def action_approve_design(self):
        if not self.env.user.has_group("call_center_core.group_call_center_manager"):
            raise AccessError("Only contact-center managers may approve campaign designs.")
        for campaign in self:
            if campaign.state == "approved" and campaign.automatic_design_state == "approved":
                continue
            campaign.write({"state": "approved"})
        return True
