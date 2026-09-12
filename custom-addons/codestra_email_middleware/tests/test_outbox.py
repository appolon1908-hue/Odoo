from unittest.mock import Mock, patch
from uuid import uuid4

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from ..models import outbox
from ..transport import EmailTransportError


@tagged("post_install", "-at_install")
class TestEmailOutbox(TransactionCase):
    def setUp(self):
        super().setUp()
        self.mail = self.env["mail.mail"].create({
            "email_from": "sender@example.com",
            "email_to": "recipient@example.net",
            "subject": "Transactional fixture",
            "body_html": "<p>Synthetic transactional message</p>",
            "state": "outgoing",
            "auto_delete": False,
        })
        self.config = {
            "tenant_id": "tenant-fixture",
            "company_id": self.env.company.id,
            "sender": "sender@example.com",
        }
        self.jobs = self.env["codestra.email.outbox"]

    def enqueue(self):
        with patch.object(outbox, "configuration", return_value=self.config):
            return self.jobs._enqueue(self.mail)

    def response(self, job, status="queued"):
        return {
            "messageId": job.message_id or str(uuid4()),
            "tenantId": job.tenant_id,
            "idempotencyKey": job.idempotency_key,
            "correlationId": job.correlation_id,
            "channel": "email",
            "direction": "outbound",
            "status": status,
            "providerReference": "postal-fixture",
            "metadata": {"odooMailId": str(self.mail.id)},
        }

    def events(self, job, event_type):
        return {"items": [{
            "eventId": str(uuid4()),
            "messageId": job.message_id,
            "type": "klyrow.email." + event_type,
            "status": "failed" if event_type != "delivered" else "delivered",
        }]}

    def test_enqueue_is_local_idempotent_and_immutable(self):
        with patch.object(outbox, "MiddlewareEmailClient") as transport:
            job = self.enqueue()
            self.assertEqual(job, self.enqueue())
            transport.assert_not_called()
        self.assertEqual(job.delivery_state, "requested")
        self.assertEqual(self.mail.codestra_email_state, "requested")
        self.assertEqual(job.payload["metadata"]["category"], "transactional")
        with self.assertRaises(AccessError):
            self.mail.write({"subject": "Changed after acceptance"})
        with self.assertRaises(AccessError):
            job.write({"state": "done"})
        with self.assertRaises(AccessError):
            self.mail.unlink()

    def test_scope_sender_recipient_and_attachment_checks_fail_closed(self):
        with patch.object(outbox, "configuration", return_value={
            **self.config, "company_id": self.env.company.id + 1000,
        }), self.assertRaises(EmailTransportError):
            self.jobs._enqueue(self.mail)
        self.mail.email_from = "other@example.com"
        with self.assertRaises(EmailTransportError):
            self.enqueue()
        self.mail.email_from = "sender@example.com"
        self.mail.email_cc = "copy@example.net"
        with self.assertRaises(EmailTransportError):
            self.enqueue()

    def test_provider_acceptance_is_not_delivery_and_events_preserve_reason(self):
        job = self.enqueue()
        job._apply(self.response(job, "dispatched"))
        self.assertEqual(job.delivery_state, "provider_accepted")
        self.assertEqual(self.mail.state, "outgoing")
        job._apply(self.response(job, "failed"), self.events(job, "bounced"))
        self.assertEqual(job.delivery_state, "bounced")
        self.assertEqual(self.mail.codestra_email_state, "bounced")
        self.assertEqual(self.mail.state, "exception")

    def test_out_of_order_bounce_does_not_regress_delivered_projection(self):
        job = self.enqueue()
        events = {"items": [
            {"type": "klyrow.email.delivered"},
            {"type": "klyrow.email.bounced"},
        ]}
        job._apply(self.response(job, "delivered"), events)
        self.assertEqual(job.delivery_state, "delivered")
        self.assertEqual(job.state, "done")
        self.assertEqual(self.mail.state, "sent")

    def test_post_delivery_complaint_remains_observable(self):
        job = self.enqueue()
        job._apply(self.response(job, "delivered"), self.events(job, "delivered"))
        job._apply(self.response(job, "delivered"), self.events(job, "complained"))
        self.assertEqual(job.delivery_state, "complained")
        self.assertEqual(job.state, "failed")
        self.assertEqual(self.mail.codestra_email_state, "complained")
        self.assertEqual(self.mail.state, "exception")

    def test_authenticated_callback_projects_without_polling_or_regression(self):
        job = self.enqueue()
        job._apply(self.response(job, "dispatched"))
        changed = job._apply_callback(
            state="delivered", tenant=job.tenant_id,
            correlation=job.correlation_id, message_id=job.message_id,
            provider_reference="postal-callback",
        )
        self.assertTrue(changed)
        self.assertEqual(job.state, "done")
        self.assertFalse(job.next_attempt_at)
        self.assertEqual(self.mail.codestra_email_state, "delivered")
        changed = job._apply_callback(
            state="bounced", tenant=job.tenant_id,
            correlation=job.correlation_id, message_id=job.message_id,
        )
        self.assertFalse(changed)
        self.assertEqual(job.delivery_state, "delivered")
        job._apply_callback(
            state="complained", tenant=job.tenant_id,
            correlation=job.correlation_id, message_id=job.message_id,
        )
        self.assertEqual(job.delivery_state, "complained")
        self.assertEqual(self.mail.state, "exception")

    def test_callback_identity_is_fail_closed(self):
        job = self.enqueue()
        job._apply(self.response(job, "queued"))
        with self.assertRaisesRegex(EmailTransportError, "CALLBACK_IDENTITY_MISMATCH"):
            job._apply_callback(
                state="delivered", tenant="another-tenant",
                correlation=job.correlation_id, message_id=job.message_id,
            )

    def test_delivered_projection_survives_refresh(self):
        job = self.enqueue()
        job._apply(self.response(job, "delivered"), self.events(job, "delivered"))
        self.assertEqual(job.delivery_state, "delivered")
        self.assertEqual(self.mail.state, "sent")
        self.assertEqual(self.mail.codestra_email_state, "delivered")
        self.mail.invalidate_recordset()
        self.assertEqual(self.mail.codestra_email_state, "delivered")

    def test_unknown_post_outcome_uses_get_and_event_read_only(self):
        job = self.enqueue()
        job._update({"state": "indeterminate", "message_id": str(uuid4())})
        client = Mock()
        client.message.return_value = self.response(job)
        client.events.return_value = {"items": []}
        job._readback(client, "synthetic-token")
        self.assertNotIn("payload", client.message.call_args.kwargs)
        self.assertEqual(client.events.call_args.kwargs["message_id"], job.message_id)

    def test_cron_commits_intent_before_single_post_then_reconciles(self):
        job = self.enqueue()
        calls = []
        with patch.object(outbox, "configuration", return_value=self.config), \
                patch.object(outbox, "delivery_enabled", return_value=True) as delivery, \
                patch.object(outbox, "MiddlewareEmailClient") as factory, \
                patch.object(self.env.cr, "commit") as commit:
            client = factory.return_value
            client.token.return_value = "synthetic-token"

            def request(**kwargs):
                calls.append(kwargs)
                if "payload" in kwargs:
                    self.assertTrue(commit.called)
                    self.assertEqual(job.state, "indeterminate")
                    raise EmailTransportError("TRANSPORT_OR_RESPONSE_ERROR")
                return self.response(job, "delivered")

            client.message.side_effect = request
            client.events.return_value = self.events(job, "delivered")
            self.jobs._cron_process()
            self.assertEqual(job.state, "indeterminate")
            job._update({"next_attempt_at": fields.Datetime.now()})
            delivery.return_value = False
            self.jobs._cron_process()
        self.assertEqual(sum("payload" in call for call in calls), 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.mail.state, "sent")
