from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase


class TestKlyrowBusinessProjection(TransactionCase):
    def payload(self, event_type, *, operation="0", event="0", data=None, occurred_at="2026-09-13T00:00:00Z"):
        return {
            "operation_id": "op_" + operation.zfill(32),
            "event_id": "evt_" + event.zfill(8),
            "event_type": event_type,
            "event_version": 1,
            "source": "klyrow",
            "tenant_id": "tenant-1",
            "correlation_id": "correlation-1",
            "causation_id": "cause-1",
            "occurred_at": occurred_at,
            "data": data or {},
            "trace_context": {},
        }

    def test_missing_tenant_is_retryable_then_daily_projection_is_upserted(self):
        model = self.env["codestra.klyrow.business.projection"]
        usage = self.payload(
            "klyrow.usage.daily",
            operation="1",
            event="1",
            data={
                "date": "2026-09-12",
                "unit": "accepted_message",
                "quantity": 5,
                "snapshot_at": "2026-09-13T00:00:00Z",
            },
        )
        record, outcome = model.apply_event(usage, "1" * 64)
        self.assertFalse(record)
        self.assertEqual(outcome, "tenant_projection_missing")

        tenant, outcome = model.apply_event(
            self.payload(
                "klyrow.tenant.created",
                operation="2",
                event="2",
                data={"tenant_id": "tenant-1", "enabled": True},
            ),
            "2" * 64,
        )
        self.assertEqual(outcome, "created")
        self.assertEqual(tenant.event_family, "tenant")

        projection, outcome = model.apply_event(usage, "1" * 64)
        self.assertEqual(outcome, "created")
        self.assertEqual(projection.logical_key, "2026-09-12:accepted_message")
        self.assertEqual(len(projection), 1)

        revised = self.payload(
            "klyrow.usage.daily",
            operation="3",
            event="3",
            data={
                "date": "2026-09-12",
                "unit": "accepted_message",
                "quantity": 7,
                "snapshot_at": "2026-09-13T01:00:00Z",
            },
        )
        same_projection, outcome = model.apply_event(revised, "3" * 64)
        self.assertEqual(outcome, "updated")
        self.assertEqual(same_projection, projection)
        self.assertEqual(model.search_count([
            ("tenant_id", "=", "tenant-1"),
            ("event_family", "=", "usage_daily"),
        ]), 1)
        self.assertEqual(same_projection.last_event_id, "evt_00000003")

    def test_tenant_update_requires_existing_tenant_and_hash_is_exact(self):
        model = self.env["codestra.klyrow.business.projection"]
        update = self.payload(
            "klyrow.tenant.updated",
            operation="6",
            event="6",
            data={"tenant_id": "tenant-1", "enabled": False},
        )
        record, outcome = model.apply_event(update, "6" * 64)
        self.assertFalse(record)
        self.assertEqual(outcome, "tenant_projection_missing")
        with self.assertRaises(ValidationError):
            model.apply_event(update, "not-a-sha256")

    def test_stale_projection_does_not_regress_and_records_cannot_be_deleted(self):
        model = self.env["codestra.klyrow.business.projection"]
        tenant, _ = model.apply_event(
            self.payload(
                "klyrow.tenant.created",
                operation="4",
                event="4",
                data={"tenant_id": "tenant-1", "enabled": True},
                occurred_at="2026-09-13T02:00:00Z",
            ),
            "4" * 64,
        )
        stale, outcome = model.apply_event(
            self.payload(
                "klyrow.tenant.updated",
                operation="5",
                event="5",
                data={"tenant_id": "tenant-1", "enabled": False},
                occurred_at="2026-09-13T01:00:00Z",
            ),
            "5" * 64,
        )
        self.assertEqual(outcome, "ignored_stale")
        self.assertEqual(stale, tenant)
        self.assertEqual(tenant.last_event_id, "evt_00000004")
        with self.assertRaises(AccessError):
            tenant.unlink()
