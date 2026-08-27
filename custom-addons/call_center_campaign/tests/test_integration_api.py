import base64
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

from ..controllers.integration_api import (
    CodestraIntegrationApiController,
    CodestraServiceOperationsController,
    _b64url,
    _effective_service_key,
)


@tagged("post_install", "-at_install")
class TestIntegrationApiContract(TransactionCase):
    def test_jwt_segments_require_canonical_base64url(self):
        encoded = base64.urlsafe_b64encode(b"synthetic").rstrip(b"=").decode()
        self.assertEqual(_b64url(encoded), b"synthetic")
        with self.assertRaisesRegex(ValueError, "non-canonical base64url"):
            _b64url(encoded[:-1] + "9")

    def test_null_optional_service_key_falls_back_to_azp(self):
        self.assertEqual(
            _effective_service_key(
                {"service_key": None, "azp": "codestra-middleware-staging"}
            ),
            "codestra-middleware-staging",
        )
        self.assertEqual(
            _effective_service_key(
                {"service_key": "unexpected", "azp": "approved"}
            ),
            "unexpected",
        )

    def test_canonical_route_catalog_is_complete(self):
        methods = (
            CodestraIntegrationApiController.capabilities,
            CodestraIntegrationApiController.claim_outbox,
            CodestraIntegrationApiController.read_outbox,
            CodestraIntegrationApiController.renew_outbox,
            CodestraIntegrationApiController.acknowledge_outbox,
            CodestraIntegrationApiController.fail_outbox,
            CodestraIntegrationApiController.release_outbox,
            CodestraIntegrationApiController.create_result,
            CodestraIntegrationApiController.read_result,
            CodestraIntegrationApiController.reconcile_result,
            CodestraIntegrationApiController.read_trace,
            CodestraIntegrationApiController.read_trace_by_record,
            CodestraIntegrationApiController.read_audit,
            CodestraIntegrationApiController.read_desired_state,
        )
        routes = {
            route for method in methods for route in method.original_routing["routes"]
        }
        expected = {
            "/api/v1/integration/capabilities",
            "/api/v1/integration/outbox/claims",
            "/api/v1/integration/outbox/<string:outbox_id>",
            "/api/v1/integration/outbox/<string:outbox_id>/lease/renew",
            "/api/v1/integration/outbox/<string:outbox_id>/acknowledgements",
            "/api/v1/integration/outbox/<string:outbox_id>/failures",
            "/api/v1/integration/outbox/<string:outbox_id>/release",
            "/api/v1/integration/results",
            "/api/v1/integration/results/<string:result_public_id>",
            "/api/v1/integration/results/<string:result_public_id>/reconcile",
            "/api/v1/integration/traces/<string:correlation_id>",
            "/api/v1/integration/traces",
            (
                "/api/v1/integration/desired-state/"
                "<string:aggregate_type>/<string:public_id>"
            ),
            "/api/v1/integration/agents/<string:public_id>",
            "/api/v1/integration/leads/<string:public_id>",
            "/api/v1/integration/campaigns/<string:public_id>",
            "/api/v1/integration/audit/<int:audit_id>",
        }
        self.assertEqual(routes, expected)

    def test_operations_routes_are_explicit(self):
        methods = (
            CodestraServiceOperationsController.health_live,
            CodestraServiceOperationsController.health_ready,
            CodestraServiceOperationsController.service_attestation,
            CodestraServiceOperationsController.metrics,
        )
        routes = {
            route for method in methods for route in method.original_routing["routes"]
        }
        self.assertEqual(
            routes,
            {
                "/health/live",
                "/health/ready",
                "/.well-known/codestra-service",
                "/metrics",
            },
        )

    def test_expired_nonce_cleanup_preserves_current_replay_guards(self):
        nonce_model = self.env["codestra.integration.callback.nonce"].sudo()
        expired = nonce_model.create(
            {
                "service_id": "synthetic-expired",
                "nonce": "expired-nonce",
                "expires_at": fields.Datetime.now() - timedelta(seconds=1),
            }
        )
        current = nonce_model.create(
            {
                "service_id": "synthetic-current",
                "nonce": "current-nonce",
                "expires_at": fields.Datetime.now() + timedelta(minutes=5),
            }
        )
        nonce_model._cron_purge_expired()
        self.assertFalse(expired.exists())
        self.assertTrue(current.exists())
