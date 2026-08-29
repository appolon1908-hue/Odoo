import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestMiddlewareCrmIntakeHttp(HttpCase):
    secret = "synthetic-middleware-crm-secret"
    tenant = "synthetic-tenant"
    route = "/codestra/middleware/v1/commands/crm.lead.upsert"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["call.center.business.unit"].create({
            "name": "Synthetic Middleware Unit",
            "code": f"MW-{uuid.uuid4().hex[:8]}",
            "company_id": cls.env.company.id,
        })
        service_group = cls.env.ref(
            "codestra_middleware_bridge.group_codestra_crm_api"
        )
        cls.service_user = cls.env["res.users"].create({
            "name": "Synthetic Middleware CRM Service",
            "login": f"middleware-crm-{uuid.uuid4()}@example.invalid",
            "company_id": cls.env.company.id,
            "company_ids": [(6, 0, cls.env.company.ids)],
            "call_center_business_unit_ids": [(6, 0, cls.unit.ids)],
            "call_center_default_business_unit_id": cls.unit.id,
            "call_center_primary_role": "integration_service",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, service_group.id])],
        })
        cls.source = cls.env["utm.source"].create({"name": "synthetic-form"})
        cls.tag = cls.env["crm.tag"].create({"name": "synthetic-intake"})
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("codestra.middleware.tenant_id", cls.tenant)
        params.set_param("codestra.middleware.inbound_hmac_secret", cls.secret)
        params.set_param("codestra.crm.tenant_ids", cls.tenant)
        params.set_param("codestra.crm.service_user_id", cls.service_user.id)
        if not cls.service_user.has_group(
            "call_center_core.group_call_center_integration_service"
        ):
            raise AssertionError("CRM service user is missing integration authorization")
        if cls.service_user.has_group("call_center_core.group_call_center_manager"):
            raise AssertionError("CRM service user must not receive manager authorization")
        if cls.service_user.has_group("call_center_core.group_call_center_admin"):
            raise AssertionError("CRM service user must not receive administrator authorization")

    def command(self, *, consent_status="granted", allow_contact=True, review=False):
        command_id = str(uuid.uuid4())
        return {
            "command_id": command_id,
            "command_type": "crm.lead.upsert",
            "command_version": "1.0",
            "target": "odoo-19",
            "tenant_id": self.tenant,
            "requested_by": "synthetic-middleware-test",
            "correlation_id": f"correlation-{command_id}",
            "idempotency_key": f"idempotency-{command_id}",
            "capability": "ODOO_WRITE",
            "payload": {
                "lead_source": self.source.name,
                "source_record_id": f"source-{command_id}",
                "initial_stage": "review_pending" if review else "new",
                "review_required": review,
                "allow_external_contact": allow_contact,
                "provenance": {
                    "method": "submitted_by_person",
                    "captured_by": "synthetic-form-service",
                    "source_reference": f"synthetic://form/{command_id}",
                    "legal_basis": "consent",
                    "content_digest": "a" * 64,
                },
                "consent": {
                    "status": consent_status,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "policy_version": "synthetic-v1",
                    "channels": {
                        "email": consent_status == "granted",
                        "sms": False,
                        "phone": consent_status == "granted",
                    },
                },
                "lead": {
                    "name": "Synthetic Middleware Lead",
                    "description": "Synthetic end-to-end intake evidence.",
                    "contact": {
                        "name": "Synthetic Contact",
                        "email": "synthetic@example.invalid",
                        "phone": "+18095550199",
                        "preferred_language": "en",
                    },
                    "company": {
                        "name": "Synthetic Company",
                        "domain": "example.invalid",
                        "industry": "Testing",
                    },
                    "campaign_code": None,
                    "tags": [self.tag.name],
                },
            },
        }

    def post(self, command, *, correlation_id=None):
        raw = json.dumps(command, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        event_id = command["command_id"]
        canonical = b"\n".join((
            timestamp.encode(),
            event_id.encode(),
            b"POST",
            self.route.encode(),
            raw,
        ))
        signature = hmac.new(
            self.secret.encode(), canonical, hashlib.sha256
        ).hexdigest()
        return self.url_open(
            self.route,
            data=raw,
            headers={
                "Content-Type": "application/json",
                "X-Codestra-Timestamp": timestamp,
                "X-Codestra-Event-ID": event_id,
                "X-Codestra-Signature": f"sha256={signature}",
                "X-Tenant-ID": command["tenant_id"],
                "X-Correlation-ID": correlation_id or command["correlation_id"],
                "Idempotency-Key": command["idempotency_key"],
            },
            timeout=20,
        )

    def lead_for(self, command):
        self.env.invalidate_all()
        return self.env["crm.lead"].search([
            ("external_source_id", "=", command["payload"]["source_record_id"])
        ])

    def test_granted_intake_creates_real_lead_and_consent_ledger(self):
        command = self.command()
        response = self.post(command)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["outcome"], "created")
        lead = self.lead_for(command)
        self.assertEqual(len(lead), 1)
        self.assertEqual(lead.type, "lead")
        self.assertEqual(lead.business_unit_id, self.unit)
        self.assertEqual(lead.consent_status, "granted")
        self.assertFalse(lead.do_not_call)
        self.assertTrue(lead.codestra_allow_external_contact)
        self.assertEqual(lead.contact_eligibility, "eligible")
        self.assertEqual(set(lead.consent_ids.mapped("channel")), {"email", "phone"})
        self.assertEqual(set(lead.consent_ids.mapped("status")), {"granted"})

        duplicate = self.post(command)
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertTrue(duplicate.json()["duplicate"])
        self.assertEqual(len(self.lead_for(command)), 1)

    def test_denied_intake_creates_hashed_suppression_and_blocks_contact(self):
        command = self.command(consent_status="denied", allow_contact=False)
        response = self.post(command)
        self.assertEqual(response.status_code, 201, response.text)
        lead = self.lead_for(command)
        self.assertEqual(lead.consent_status, "denied")
        self.assertTrue(lead.do_not_call)
        self.assertEqual(lead.preferred_contact_method, "none")
        self.assertEqual(lead.contact_eligibility, "blocked")
        suppressions = self.env["call.center.suppression"].sudo().search([
            ("business_unit_id", "=", self.unit.id),
            ("source", "=", "synthetic-form-service"),
        ])
        self.assertEqual(
            set(suppressions.mapped("identifier_type")),
            {"phone", "email", "external_id"},
        )
        self.assertNotIn(lead.phone.lower(), suppressions.mapped("identifier_hash"))
        self.assertTrue(all(len(value) == 64 for value in suppressions.mapped("identifier_hash")))

    def test_review_pending_is_blocked_without_fabricating_suppression(self):
        command = self.command(
            consent_status="unknown", allow_contact=False, review=True
        )
        response = self.post(command)
        self.assertEqual(response.status_code, 201, response.text)
        lead = self.lead_for(command)
        self.assertTrue(lead.codestra_review_required)
        self.assertEqual(lead.codestra_initial_stage, "review_pending")
        self.assertEqual(lead.preferred_contact_method, "none")
        self.assertEqual(lead.contact_eligibility, "blocked")
        self.assertFalse(self.env["call.center.suppression"].sudo().search([
            ("business_unit_id", "=", self.unit.id),
            ("identifier_hash", "=", self.env["call.center.suppression"].sudo().hash_identifier(lead.phone)),
        ]))

    def test_command_and_signed_headers_must_match(self):
        command = self.command()
        response = self.post(command, correlation_id="different-correlation")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["error"], "command_header_mismatch")
        self.assertFalse(self.lead_for(command))
