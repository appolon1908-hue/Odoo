from unittest.mock import patch
from uuid import uuid4

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from ..models import outbox
from ..transport import SmsTransportError


@tagged("post_install", "-at_install")
class TestSmsOutbox(TransactionCase):
    def setUp(self):
        super().setUp()
        self.unit = self.env.ref("call_center_core.business_unit_transport")
        self.campaign = self.env["call.center.campaign"].create({
            "name": "SMS synthetic campaign", "code": "SMS-FIXTURE", "business_unit_id": self.unit.id,
            "calling_hour_start": 0, "calling_hour_end": 24,
        })
        self.lead = self.env["crm.lead"].create({
            "name": "SMS synthetic lead", "business_unit_id": self.unit.id,
            "company_id": self.unit.company_id.id, "call_center_campaign_id": self.campaign.id,
            "phone": "+49123456789", "codestra_sms_consent": True,
            "migration_review_required": False,
        })
        self.message = self.env["mail.message"].create({
            "model": "crm.lead", "res_id": self.lead.id, "body": "Synthetic SMS",
            "message_type": "sms", "subtype_id": self.env.ref("mail.mt_note").id,
        })
        self.sms = self.env["sms.sms"].create({
            "number": self.lead.phone, "body": "Synthetic SMS", "mail_message_id": self.message.id,
        })
        self.config = {"tenant_id": "tenant-fixture", "company_id": self.unit.company_id.id,
                       "business_unit_id": self.unit.id, "sender": "Fixture", "billing_account_id": "billing-fixture"}
        self.jobs = self.env["codestra.sms.outbox"]

    def enqueue(self):
        with patch.object(outbox, "configuration", return_value=self.config):
            return self.jobs._enqueue(self.sms)

    def response(self, job, status="queued"):
        return {"messageId": job.message_id or str(uuid4()), "tenantId": job.tenant_id,
                "idempotencyKey": job.idempotency_key, "correlationId": job.correlation_id,
                "channel": "sms", "direction": "outbound", "status": status,
                "metadata": {"odooSmsUuid": self.sms.uuid}}

    def test_enqueue_is_durable_idempotent_and_does_not_call_provider(self):
        with patch.object(outbox, "MiddlewareSmsClient") as transport:
            job = self.enqueue()
            self.assertEqual(job, self.enqueue())
            transport.assert_not_called()
        self.assertEqual(self.sms.state, "process")
        self.assertFalse(self.sms.to_delete)
        self.assertEqual(job.payload["metadata"]["consent"], "granted")
        with self.assertRaises(AccessError):
            self.sms.write({"body": "Changed after acceptance"})
        with self.assertRaises(AccessError):
            job.write({"state": "done"})
        with self.assertRaises(AccessError):
            self.sms.unlink()

    def test_consent_scope_and_actual_destination_are_enforced(self):
        for config in ({**self.config, "company_id": self.unit.company_id.id + 1000},
                       {**self.config, "business_unit_id": self.unit.id + 1000}):
            with self.assertRaises(SmsTransportError):
                self.jobs._policy(self.lead, self.sms.number, config)
        with self.assertRaises(SmsTransportError):
            self.jobs._policy(self.lead, "+49123456788", self.config)
        self.lead.codestra_sms_consent = False
        with self.assertRaises(SmsTransportError):
            self.enqueue()

    def test_newer_revocation_and_suppression_override_consent(self):
        self.env["call.center.consent"].create({
            "business_unit_id": self.unit.id, "lead_id": self.lead.id, "channel": "sms",
            "status": "revoked", "source": "synthetic-test", "evidence_reference": "fixture",
        })
        with self.assertRaises(SmsTransportError):
            self.enqueue()

    def test_submission_is_not_delivery_and_stale_status_cannot_regress(self):
        job = self.enqueue()
        job._apply(self.response(job))
        self.assertEqual(self.sms.state, "process")
        job._apply(self.response(job, "dispatched"))
        self.assertEqual(self.sms.state, "pending")
        job._apply(self.response(job, "delivered"))
        self.assertEqual(self.sms.state, "sent")
        self.assertEqual(job.communication_id.status, "DELIVERED")
        job._apply(self.response(job, "queued"))
        self.assertEqual(self.sms.state, "sent")

    def test_cross_tenant_acknowledgement_cannot_update_odoo(self):
        job = self.enqueue()
        response = self.response(job)
        response["tenantId"] = "other-tenant"
        with self.assertRaises(SmsTransportError):
            job._apply(response)
        self.assertFalse(job.message_id)

    def test_native_send_queues_through_bridge_without_iap(self):
        with patch("odoo.addons.codestra_sms_middleware.models.sms.enabled", return_value=True), \
                patch.object(outbox, "configuration", return_value=self.config), \
                patch.object(outbox, "MiddlewareSmsClient") as transport:
            self.sms.send()
            transport.assert_not_called()
        self.assertEqual(self.jobs.search_count([("sms_id", "=", self.sms.id)]), 1)
        self.assertEqual(self.sms.state, "process")

    def test_unknown_outcome_uses_get_only_even_when_delivery_disabled(self):
        from unittest.mock import Mock
        job = self.enqueue()
        job._update({"state": "indeterminate"})
        client = Mock()
        job._readback(client, "synthetic-token")
        self.assertNotIn("payload", client.message.call_args.kwargs)
        self.assertEqual(client.message.call_args.kwargs["key"], job.idempotency_key)

    def test_cron_commits_uncertain_intent_before_post_and_never_posts_again(self):
        from odoo import fields
        job = self.enqueue()
        calls = []
        with patch.object(outbox, "configuration", return_value=self.config), \
                patch.object(outbox, "delivery_enabled", return_value=True) as delivery, \
                patch.object(outbox, "MiddlewareSmsClient") as factory, \
                patch.object(self.env.cr, "commit") as commit:
            client = factory.return_value
            client.token.return_value = "synthetic-token"

            def request(**kwargs):
                calls.append(kwargs)
                if "payload" in kwargs:
                    self.assertTrue(commit.called)
                    self.assertEqual(job.state, "indeterminate")
                    raise SmsTransportError("TRANSPORT_OR_RESPONSE_ERROR")
                return self.response(job, "delivered")

            client.message.side_effect = request
            self.jobs._cron_process()
            self.assertEqual(job.state, "indeterminate")
            job._update({"next_attempt_at": fields.Datetime.now()})
            delivery.return_value = False
            self.jobs._cron_process()
        self.assertEqual(sum("payload" in call for call in calls), 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.sms.state, "sent")
