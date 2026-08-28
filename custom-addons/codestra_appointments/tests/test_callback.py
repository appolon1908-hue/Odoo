from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestCallbackState(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["call.center.business.unit"].sudo().with_context(active_test=False).search(
            [("code", "=", "COD")], limit=1
        )
        if not cls.unit:
            cls.unit = cls.env["call.center.business.unit"].sudo().create({
                "name": "COD Synthetic Tests", "code": "COD", "brand": "Codestra"
            })
        cls.campaign = cls.env["call.center.campaign"].sudo().with_context(active_test=False).search([
            ("code", "=", "TEST_SYN")
        ], limit=1)
        if not cls.campaign:
            cls.campaign = cls.env["call.center.campaign"].sudo().create({
                "name": "Callback Synthetic Tests",
                "code": "TEST_SYN",
                "business_unit_id": cls.unit.id,
            })
        elif cls.campaign.business_unit_id != cls.unit:
            # Production clones can already contain an inactive fixture under a
            # test tenant. Rebind it only inside this rolled-back test transaction.
            cls.env.cr.execute(
                "UPDATE call_center_campaign SET business_unit_id = %s WHERE id = %s",
                (cls.unit.id, cls.campaign.id),
            )
            cls.campaign.invalidate_recordset(["business_unit_id"])

    def _callback(self, **values):
        payload = {
            "business_unit_id": self.unit.id,
            "campaign_id": self.campaign.id,
            "assigned_agent_id": self.env.user.id,
            "phone_number": "+15555550199",
            "normalized_phone": "+15555550199",
            "scheduled_at": fields.Datetime.now() + timedelta(hours=1),
            "customer_timezone": "UTC",
            "reason": "TEST_SYN callback contract",
            "correlation_id": "TEST-SYN-CORRELATION",
            "idempotency_key": "TEST-SYN-IDEMPOTENCY-%s" % fields.Datetime.now(),
            "compliance_allowed": True,
            "compliance_evidence": {
                "consent": True,
                "within_calling_hours": True,
                "campaign_allowed": True,
            },
        }
        payload.update(values)
        return self.env["codestra.callback"].create(payload)

    def test_terminal_transition_rejected(self):
        callback = self._callback(state="completed")
        with self.assertRaises(ValidationError):
            callback.action_transition("due", "TEST-SYN-CORRELATION")

    def test_callback_can_precede_a_telephony_call(self):
        callback = self._callback()
        self.assertFalse(callback.call_id)
        self.assertFalse(callback.lead_id)
        self.assertEqual(callback.campaign_id, self.campaign)
        self.assertFalse(callback.vicidial_campaign_id)
        self.assertEqual(callback.owner_id, self.env.user)

    def test_disabled_sync_does_not_enqueue(self):
        callback = self._callback()
        with patch.dict("os.environ", {"CODESTRA_CALLBACK_SYNC_ENABLED": "false"}):
            callback.action_schedule()
        self.assertFalse(self.env["codestra.callback.sync.job"].search([
            ("callback_id", "=", callback.id)
        ]))

    def test_schedule_enqueues_one_idempotent_create(self):
        callback = self._callback()
        jobs = self.env["codestra.callback.sync.job"]
        with patch.dict("os.environ", {"CODESTRA_CALLBACK_SYNC_ENABLED": "true"}):
            callback.action_schedule()
            first = jobs.search([("callback_id", "=", callback.id)])
            duplicate = jobs._enqueue(callback, "create", callback.correlation_id)
        self.assertEqual(len(first), 1)
        self.assertEqual(first, duplicate)
        self.assertEqual(first.operation, "create")

    def test_configuration_accepts_only_exact_private_keycloak_http(self):
        values = {
            "CODESTRA_CALLBACK_SYNC_ENABLED": "true",
            "CODESTRA_CALLBACK_API_BASE_URL": "https://api.codestra.co/api/v1",
            "CODESTRA_CALLBACK_TOKEN_URL": (
                "http://keycloak:8080/realms/codestra/protocol/openid-connect/token"
            ),
            "CODESTRA_CALLBACK_CLIENT_ID": "codestra-odoo-callback-service",
            "CODESTRA_CALLBACK_CLIENT_SECRET_FILE": "/run/secrets/callback",
            "CODESTRA_CALLBACK_CA_FILE": "/etc/ssl/certs/ca-certificates.crt",
            "CODESTRA_CALLBACK_ALLOWED_TENANT": "COD",
            "CODESTRA_CALLBACK_ALLOWED_CAMPAIGN": "TEST_SYN",
        }
        jobs = self.env["codestra.callback.sync.job"]
        with patch.dict("os.environ", values, clear=True):
            self.assertEqual(jobs._configuration()["token_url"], values["CODESTRA_CALLBACK_TOKEN_URL"])
        values["CODESTRA_CALLBACK_TOKEN_URL"] = "http://auth.example.test:8080/token"
        with patch.dict("os.environ", values, clear=True), self.assertRaises(ValidationError):
            jobs._configuration()

    def test_acknowledgement_persists_canonical_identity(self):
        callback = self._callback(state="scheduled", version=2)
        job = self.env["codestra.callback.sync.job"].create({
            "callback_id": callback.id,
            "operation": "create",
            "idempotency_key": "TEST-SYN-ACK",
            "correlation_id": callback.correlation_id,
            "callback_version": callback.version,
        })
        job._apply_result({"id": "018f0000-0000-7000-8000-000000000001",
                           "version": 1, "state": "SCHEDULED"})
        self.assertEqual(callback.middleware_callback_uuid,
                         "018f0000-0000-7000-8000-000000000001")
        self.assertEqual(callback.middleware_version, 1)
        self.assertEqual(callback.middleware_sync_state, "synced")
        self.assertEqual(job.state, "done")

    def test_reconcile_updates_state_once_without_feedback_job(self):
        callback = self._callback(
            state="scheduled", version=2,
            middleware_callback_uuid="018f0000-0000-7000-8000-000000000002",
            middleware_version=1,
        )
        job = self.env["codestra.callback.sync.job"].create({
            "callback_id": callback.id,
            "operation": "reconcile",
            "idempotency_key": "TEST-SYN-RECONCILE",
            "correlation_id": callback.correlation_id,
            "callback_version": callback.version,
        })
        job._apply_result({"id": callback.middleware_callback_uuid,
                           "version": 3, "state": "COMPLETED",
                           "completion_disposition": "SYNTHETIC_COMPLETE",
                           "completion_notes": "Completed without PSTN"})
        self.assertEqual(callback.state, "completed")
        self.assertEqual(callback.middleware_version, 3)
        self.assertEqual(callback.completion_disposition, "SYNTHETIC_COMPLETE")
        self.assertEqual(callback.completion_notes, "Completed without PSTN")
        history = callback.history_ids.filtered(
            lambda row: row.event_type == "callback.reconciled"
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(len(self.env["codestra.callback.sync.job"].search([
            ("callback_id", "=", callback.id)
        ])), 1)

    def test_payload_denies_non_synthetic_campaign(self):
        campaign = self.env["call.center.campaign"].sudo().with_context(active_test=False).search([
            ("business_unit_id", "=", self.unit.id),
            ("id", "!=", self.campaign.id),
        ], limit=1)
        callback = self._callback(campaign_id=campaign.id)
        with self.assertRaises(ValidationError):
            self.env["codestra.callback.sync.job"]._create_payload(callback)
