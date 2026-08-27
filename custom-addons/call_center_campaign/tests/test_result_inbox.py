import uuid

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestIntegrationResultInbox(TransactionCase):
    def setUp(self):
        super().setUp()
        self.unit = self.env.ref("call_center_core.business_unit_digital")
        self.campaign = self.env["call.center.campaign"].create(
            {
                "name": "Synthetic Result Campaign",
                "code": f"COD-RESULT-{uuid.uuid4().hex[:8].upper()}",
                "business_unit_id": self.unit.id,
                "direction": "outbound",
                "purpose_code": "TEST",
                "design_automation_enabled": True,
            }
        )
        self.outbox = self.env["codestra.runtime.integration.outbox"].sudo().search(
            [("campaign_id", "=", self.campaign.id)], limit=1
        )

    def _values(self):
        result_id = str(uuid.uuid4())
        return {
            "name": result_id,
            "result_public_id": result_id,
            "schema_version": "1.0",
            "delivery_id": str(uuid.uuid4()),
            "event_id": self.outbox.event_uuid,
            "registration_id": str(uuid.uuid4()),
            "acknowledgement_id": str(uuid.uuid4()),
            "correlation_id": self.outbox.correlation_id,
            "workflow_id": "n8n-assigned-test-id",
            "workflow_version": "2.0.0",
            "execution_id": str(uuid.uuid4()),
            "execution_status": "SUCCEEDED",
            "result_classification": "RECONCILIATION_COMPLETE",
            "result_hash": "a" * 64,
            "organization_public_id": "ORG-TEST",
            "business_unit_id": self.unit.id,
            "campaign_id": self.campaign.id,
            "source_system": "codestra-middleware",
            "source_environment": "production",
            "policy_hash": "b" * 64,
            "originating_outbox_id": self.outbox.id,
            "originating_model": "call.center.campaign",
            "originating_res_id": self.campaign.id,
            "received_at": "2026-07-29 09:00:00",
            "acknowledged_at": "2026-07-29 09:00:00",
            "processing_status": "RECEIVED",
            "reconciliation_status": "RECONCILED",
            "payload_json_redacted": {"summary": "internal-only"},
            "request_hash": "c" * 64,
            "created_by_service": "codestra-middleware-odoo-results",
        }

    def test_result_requires_internal_callback_capability_and_is_immutable(self):
        values = self._values()
        with self.assertRaises(AccessError):
            self.env["codestra.integration.result.inbox"].create(values)
        record = (
            self.env["codestra.integration.result.inbox"]
            .sudo()
            ._create_from_callback(values)
        )
        self.assertEqual(record.originating_outbox_id, self.outbox)
        with self.assertRaises(AccessError):
            record.write({"processing_status": "PROCESSED"})
        record._mark_processed()
        self.assertEqual(record.processing_status, "PROCESSED")
        with self.assertRaises(ValidationError):
            record._mark_processed()
        with self.assertRaises(AccessError):
            record.unlink()

    def test_trace_is_read_only_and_links_authoritative_records(self):
        record = (
            self.env["codestra.integration.result.inbox"]
            .sudo()
            ._create_from_callback(self._values())
        )
        trace = self.env["codestra.integration.trace"].search(
            [("result_inbox_id", "=", record.id)]
        )
        self.assertEqual(trace.originating_outbox_id, self.outbox)
        self.assertEqual(trace.campaign_id, self.campaign)
        with self.assertRaises(AccessError):
            trace.write({"current_status": "FAILED"})
