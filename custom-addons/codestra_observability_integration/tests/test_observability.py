from copy import deepcopy

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models.observability import INCIDENT_HASH_KEYS, KPI_HASH_KEYS, _hash


@tagged("post_install", "-at_install")
class TestKyyowObservability(TransactionCase):
    def _with_projection(self, payload, keys):
        normalized = dict(payload)
        source_hash = normalized.get("source_payload_hash")
        if isinstance(source_hash, str) and not source_hash.startswith("sha256:"):
            normalized["source_payload_hash"] = "sha256:" + source_hash
        normalized["projection_hash"] = "sha256:" + _hash(
            {key: normalized[key] for key in keys}
        )
        return normalized

    def _kpi(self):
        return self._with_projection(
            {
                "event_id": "kpi-tenant-a-1",
                "schema_version": "kyyow.observability.kpi.v1",
                "tenant_id": "tenant-a",
                "metric_code": "sms.delivery_rate",
                "service_id": "middleware",
                "environment": "production",
                "period_reference": "2026-09-12T12:00:00Z",
                "period_start": "2026-09-12T12:00:00Z",
                "period_end": "2026-09-12T13:00:00Z",
                "value": 99.1,
                "unit": "percent",
                "dimensions": {"route": "primary"},
                "source": "prometheus",
                "source_revision": 1,
                "source_payload_hash": "a" * 64,
                "observed_at": "2026-09-12T13:00:00Z",
                "reconciliation_state": "accepted",
                "correlation_id": "corr-kpi-1",
            },
            KPI_HASH_KEYS,
        )

    def _incident(self):
        return self._with_projection(
            {
                "event_id": "incident-tenant-a-1",
                "schema_version": "kyyow.observability.incident.v1",
                "tenant_id": "tenant-a",
                "incident_id": "incident-1",
                "fingerprint": "fp-1",
                "alertname": "MiddlewareOdooDelivery",
                "group_key": "tenant-a/middleware",
                "severity": "critical",
                "state": "firing",
                "service_id": "middleware",
                "environment": "production",
                "host": "node-1",
                "summary": "Odoo delivery is failing",
                "labels": {"service": "middleware", "severity": "critical"},
                "first_seen_at": "2026-09-12T13:00:00Z",
                "last_seen_at": "2026-09-12T13:00:00Z",
                "resolved_at": None,
                "source_deployment": "middleware:abc123",
                "resource_version": 1,
                "source_payload_hash": "b" * 64,
                "observed_at": "2026-09-12T13:00:00Z",
                "correlation_id": "corr-incident-1",
            },
            INCIDENT_HASH_KEYS,
        )

    def test_kpi_replay_is_idempotent_and_immutable(self):
        model = self.env["kyyow.observability.kpi.snapshot"].sudo()
        payload = self._kpi()

        record, duplicate = model._from_payload(payload)
        self.assertFalse(duplicate)
        replay, duplicate = model._from_payload(payload)
        self.assertTrue(duplicate)
        self.assertEqual(record.id, replay.id)
        self.assertEqual(
            record.document()["period_start"],
            "2026-09-12T12:00:00Z",
        )

        with self.assertRaises(ValidationError):
            model._from_payload({**payload, "projection_hash": "sha256:" + "f" * 64})
        with self.assertRaises(AccessError):
            record.write({"value": 1.0})

    def test_incident_transitions_are_versioned_and_replayed(self):
        model = self.env["kyyow.observability.incident"].sudo()
        events = self.env["kyyow.observability.incident.event"].sudo()
        first = self._incident()

        record, duplicate = model._from_payload(first)
        self.assertFalse(duplicate)
        self.assertEqual(record.state, "firing")

        resolved = deepcopy(first)
        resolved.update(
            {
                "event_id": "incident-tenant-a-2",
                "state": "resolved",
                "resource_version": 2,
                "last_seen_at": "2026-09-12T13:05:00Z",
                "resolved_at": "2026-09-12T13:05:00Z",
                "observed_at": "2026-09-12T13:05:00Z",
                "correlation_id": "corr-incident-2",
                "source_payload_hash": "c" * 64,
            }
        )
        resolved = self._with_projection(resolved, INCIDENT_HASH_KEYS)
        updated, duplicate = model._from_payload(resolved)
        self.assertFalse(duplicate)
        self.assertEqual(record.id, updated.id)
        self.assertEqual(updated.state, "resolved")
        self.assertEqual(events.search_count([("incident_id", "=", record.id)]), 2)

        replay, duplicate = model._from_payload(resolved)
        self.assertTrue(duplicate)
        self.assertEqual(replay.id, record.id)

        stale = deepcopy(resolved)
        stale.update(
            {
                "event_id": "incident-tenant-a-3",
                "resource_version": 2,
                "correlation_id": "corr-incident-3",
            }
        )
        stale = self._with_projection(stale, INCIDENT_HASH_KEYS)
        with self.assertRaises(ValidationError):
            model._from_payload(stale)

    def test_sensitive_dimensions_are_rejected(self):
        model = self.env["kyyow.observability.kpi.snapshot"].sudo()
        payload = self._kpi()
        payload["dimensions"] = {"api_token": "must-not-enter-odoo"}
        with self.assertRaises(ValidationError):
            model._from_payload(payload)

    def test_incident_replay_retains_original_receipt_after_update(self):
        model = self.env['kyyow.observability.incident'].sudo()
        events = self.env['kyyow.observability.incident.event'].sudo()
        first = self._incident()
        record, _ = model._from_payload(first)
        event = events.search([('event_id', '=', first['event_id'])])
        receipt = deepcopy(event.receipt)
        later = self._with_projection({**first, 'event_id': 'later-event',
            'resource_version': 2, 'state': 'acknowledged',
            'correlation_id': 'later-correlation'}, INCIDENT_HASH_KEYS)
        model._from_payload(later)
        _, duplicate = model._from_payload(first)
        self.assertTrue(duplicate)
        self.assertEqual(event.receipt, receipt)
        self.assertEqual(receipt['state'], 'firing')
        self.assertEqual(receipt['resource_version'], 1)
        self.assertEqual(receipt['correlation_id'], first['correlation_id'])
        self.assertEqual(receipt['operation'], 'odoo.observability.incidents.upsert')
        with self.assertRaises(AccessError):
            event.write({'receipt': {}})

    def test_unknown_sensitive_and_wrong_operation_fields_are_rejected(self):
        for model_name, payload in (
            ('kyyow.observability.kpi.snapshot', self._kpi()),
            ('kyyow.observability.incident', self._incident()),
        ):
            model = self.env[model_name].sudo()
            for key in ('unknown', 'password', 'logs', 'traces', 'raw_samples', 'message_body'):
                with self.subTest(model=model_name, key=key), self.assertRaises(ValidationError):
                    model._from_payload({**payload, key: 'prohibited'})
            with self.assertRaises(ValidationError):
                model._from_payload({**payload, 'operation': 'unknown.operation'})
