import hashlib
import time
import uuid

from odoo.addons.call_center_campaign.controllers.integration_api import (
    CodestraIntegrationApiController,
    IntegrationRejected,
    _validate_request_binding,
)
from odoo.tests.common import TransactionCase, tagged

from ..controllers.integration_readback import (
    CodestraTelephonyIntegrationApiController,
    _hash_value,
    _mapping_document,
    _projection_document,
)


@tagged("post_install", "-at_install")
class TestTelephonyApiContract(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env.ref("call_center_core.business_unit_digital")
        cls.campaign = cls.env["call.center.campaign"].create(
            {
                "name": "Synthetic Telephony API Campaign",
                "code": f"API{uuid.uuid4().hex[:7].upper()}",
                "business_unit_id": cls.unit.id,
                "direction": "outbound",
                "purpose_code": "TEST",
                "design_automation_enabled": True,
            }
        )
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Synthetic Telephony API Agent",
                "codestra_employee_number": f"AGT-{uuid.uuid4().hex[:10]}",
            }
        )
        cls.projection = cls.env["codestra.telephony.desired.state"].create(
            {
                "record_environment": "TEST",
                "employee_id": cls.employee.id,
                "business_unit_id": cls.unit.id,
                "campaign_id": cls.campaign.id,
                "desired_enabled": False,
                "desired_campaign_membership": False,
                "desired_callback_permission": False,
                "desired_transfer_permission": False,
                "desired_external_call_permission": False,
            }
        )
        cls.mapping = cls.env["codestra.telephony.target.mapping"].create(
            {
                "environment": "TEST",
                "employee_id": cls.employee.id,
                "agent_public_id": cls.employee.codestra_employee_number,
                "business_unit_id": cls.unit.id,
                "business_unit_public_id": cls.unit.code,
                "campaign_id": cls.campaign.id,
                "campaign_public_id": cls.campaign.code,
                "target_system": "ASTERISK_ENDPOINT",
                "target_resource_type": "ENDPOINT",
                "target_public_id": f"EPT-{uuid.uuid4()}",
                "desired_state_version": cls.projection.desired_state_version,
                "mapping_status": "PROVISIONING",
            }
        )

    def test_route_catalog_is_read_only_except_result_callback(self):
        methods = (
            CodestraTelephonyIntegrationApiController.read_telephony_projection,
            CodestraTelephonyIntegrationApiController.search_telephony_projections,
            CodestraTelephonyIntegrationApiController.read_telephony_mapping,
            CodestraTelephonyIntegrationApiController.search_telephony_mappings,
            CodestraTelephonyIntegrationApiController.read_reconciliation_run,
            CodestraTelephonyIntegrationApiController.read_reconciliation_drift,
        )
        routes = {
            route for method in methods for route in method.original_routing["routes"]
        }
        routes.update(
            CodestraIntegrationApiController.create_result.original_routing["routes"]
        )
        self.assertEqual(
            routes,
            {
                "/api/v1/integration/results",
                (
                    "/api/v1/integration/telephony/projections/"
                    "<string:projection_public_id>"
                ),
                "/api/v1/integration/telephony/projections",
                (
                    "/api/v1/integration/telephony/mappings/"
                    "<string:mapping_public_id>"
                ),
                "/api/v1/integration/telephony/mappings",
                (
                    "/api/v1/integration/reconciliation/runs/"
                    "<string:run_public_id>"
                ),
                (
                    "/api/v1/integration/reconciliation/drifts/"
                    "<string:drift_public_id>"
                ),
            },
        )
        self.assertNotIn(
            "routes",
            CodestraTelephonyIntegrationApiController.create_result.original_routing,
        )
        for method in methods:
            self.assertEqual(method.original_routing["methods"], ["GET"])

    def test_readback_documents_are_scoped_and_redacted(self):
        projection = _projection_document(self.projection)
        mapping = _mapping_document(self.mapping)
        self.assertEqual(
            projection["projection_public_id"], self.projection.state_public_id
        )
        self.assertEqual(mapping["mapping_public_id"], self.mapping.mapping_public_id)
        protected_names = {
            "password",
            "secret",
            "token",
            "authorization",
            "payload",
        }
        self.assertFalse(protected_names.intersection(projection))
        self.assertFalse(protected_names.intersection(mapping))

    def test_hash_contract_rejects_non_sha256_values(self):
        self.assertEqual(_hash_value("sha256:" + "a" * 64, "result_hash"), "a" * 64)
        for invalid in ("", "a" * 63, "g" * 64):
            with self.assertRaises(IntegrationRejected):
                _hash_value(invalid, "result_hash")

    def test_request_binding_validates_hash_trace_and_replay(self):
        raw = b'{"synthetic":true}'
        nonce = f"nonce-{uuid.uuid4()}"
        headers = {
            "X-Codestra-Timestamp": str(int(time.time())),
            "X-Codestra-Nonce": nonce,
            "X-Codestra-Body-SHA256": hashlib.sha256(raw).hexdigest(),
            "traceparent": (
                "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
            ),
        }
        claims = {"azp": "synthetic-middleware"}
        nonce_model = self.env["codestra.integration.callback.nonce"].sudo()
        self.assertEqual(
            _validate_request_binding(headers, raw, claims, nonce_model),
            hashlib.sha256(raw).hexdigest(),
        )
        with self.assertRaises(IntegrationRejected):
            _validate_request_binding(headers, raw, claims, nonce_model)

        stale = dict(headers)
        stale["X-Codestra-Nonce"] = f"nonce-{uuid.uuid4()}"
        stale["X-Codestra-Timestamp"] = str(int(time.time()) - 600)
        with self.assertRaises(IntegrationRejected):
            _validate_request_binding(stale, raw, claims, nonce_model)

        altered = dict(headers)
        altered["X-Codestra-Nonce"] = f"nonce-{uuid.uuid4()}"
        altered["X-Codestra-Body-SHA256"] = "0" * 64
        with self.assertRaises(IntegrationRejected):
            _validate_request_binding(altered, raw, claims, nonce_model)

        invalid_trace = dict(headers)
        invalid_trace["X-Codestra-Nonce"] = f"nonce-{uuid.uuid4()}"
        invalid_trace["traceparent"] = "invalid"
        with self.assertRaises(IntegrationRejected):
            _validate_request_binding(invalid_trace, raw, claims, nonce_model)
