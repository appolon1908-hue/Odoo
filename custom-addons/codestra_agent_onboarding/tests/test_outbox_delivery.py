import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.outbox_delivery import (
    MIDDLEWARE_EVENT_PATH,
    _event_document,
    _event_endpoint,
    _signed_headers,
    _iso_utc,
    _validate_ack,
)


@tagged("post_install", "-at_install")
class TestAgentOnboardingOutboxDelivery(TransactionCase):
    def _event(self, event_type="agent.provisioning.requested.v1"):
        return SimpleNamespace(
            event_type=event_type,
            event_uuid="9d4f15f7-339e-4d46-b754-1c6418b9daf1",
            created_at=datetime(
                2026, 9, 4, 16, 0, tzinfo=timezone.utc
            ),
            organization_public_id="tenant-1",
            correlation_id="correlation-agent-onboarding-1",
            causation_id=False,
            payload_json={
                "schema_version": "1.0",
                "event_type": event_type,
                "login": {"identifier": "agent@example.invalid"},
                "controls": {
                    "create_disabled": True,
                    "plaintext_password_allowed": False,
                    "production_dialing": False,
                },
            },
            aggregate_type="codestra.agent.onboarding",
            aggregate_uuid="6ab16b7e-362f-4b18-94ae-9f14b2478ad8",
            business_unit_code="COD",
            campaign_id=SimpleNamespace(id=42),
            record_environment="STAGING",
            deterministic_event_key=(
                "STAGING:onboarding:6ab16b7e:1:provision"
            ),
            payload_hash="a" * 64,
            schema_version="1.0",
        )

    def test_event_document_is_canonical_and_preserves_no_credentials(self):
        document = _event_document(
            self._event(),
            received_at=datetime(
                2026, 9, 4, 16, 1, tzinfo=timezone.utc
            ),
        )
        self.assertEqual(
            document["event_type"],
            "codestra.odoo.agent.provisioning_requested",
        )
        self.assertEqual(document["source"], "odoo-integration")
        self.assertEqual(document["idempotency_key"], document["event_id"])
        self.assertEqual(document["tenant_id"], "tenant-1")
        self.assertTrue(
            document["payload"]["controls"]["create_disabled"]
        )
        encoded = json.dumps(document, sort_keys=True)
        for forbidden in (
            '"password"',
            '"temporary_password"',
            '"token"',
            '"secret"',
            '"activation_link"',
            '"action_link"',
        ):
            self.assertNotIn(forbidden, encoded)

    def test_activation_event_uses_separate_canonical_type(self):
        document = _event_document(
            self._event("agent.activation-email.requested.v1")
        )
        self.assertEqual(
            document["event_type"],
            "codestra.odoo.agent.activation_email_requested",
        )

    def test_signed_headers_match_middleware_v1_contract(self):
        event = _event_document(self._event())
        body = json.dumps(
            event, sort_keys=True, separators=(",", ":")
        ).encode()
        headers = _signed_headers(
            token="synthetic-token",
            key=b"synthetic-hmac-key",
            body=body,
            timestamp="1788537600",
            event=event,
        )
        canonical = "\n".join(
            (
                "v1",
                "POST",
                MIDDLEWARE_EVENT_PATH,
                "1788537600",
                event["event_id"],
                "odoo-integration",
                hashlib.sha256(body).hexdigest(),
            )
        ).encode()
        expected = hmac.new(
            b"synthetic-hmac-key", canonical, hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            headers["X-Codestra-Signature"], f"sha256={expected}"
        )
        self.assertEqual(
            headers["Idempotency-Key"], event["event_id"]
        )
        self.assertEqual(
            headers["X-Codestra-Event-Id"], event["event_id"]
        )

    def test_endpoint_is_exact_and_credential_free(self):
        self.assertEqual(
            _event_endpoint(
                "https://middleware.internal/api/v1/odoo/events"
            ),
            "https://middleware.internal/api/v1/odoo/events",
        )
        for invalid in (
            "http://middleware.internal/api/v1/odoo/events",
            "https://user:secret@middleware.internal/api/v1/odoo/events",
            "https://middleware.internal/api/v1/odoo/events?redirect=1",
            "https://middleware.internal/v1/commands",
        ):
            with (
                self.subTest(invalid=invalid),
                self.assertRaises(ValidationError),
            ):
                _event_endpoint(invalid)

    def test_acknowledgement_must_bind_to_original_event(self):
        event = _event_document(self._event())
        accepted = {
            "event_id": event["event_id"],
            "tenant_id": event["tenant_id"],
            "status": "accepted",
            "duplicate": False,
            "correlation_id": event["correlation_id"],
        }
        self.assertEqual(_validate_ack(accepted, event), accepted)
        with self.assertRaises(ValidationError):
            _validate_ack({**accepted, "event_id": "different"}, event)

    def test_timestamp_normalization_preserves_utc_instant(self):
        cases = (
            datetime(2026, 9, 4, 16, 0),
            datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 4, 12, 0, tzinfo=timezone(timedelta(hours=-4))),
            "2026-09-04 16:00:00",
        )
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(_iso_utc(value), "2026-09-04T16:00:00Z")
