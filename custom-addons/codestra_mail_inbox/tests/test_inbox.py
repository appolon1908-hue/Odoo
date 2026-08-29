import base64
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraMailInbox(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.support = cls.env.ref("codestra_mail_inbox.team_codestra_support")
        cls.admin = cls.env.ref("codestra_mail_inbox.team_codestra_admin")
        users = cls.env["res.users"].with_context(no_reset_password=True)
        cls.support_user = users.create({"name": "Synthetic Support", "login": "synthetic-support", "group_ids": [Command.link(cls.env.ref("codestra_mail_inbox.group_mail_support_user").id)]})
        cls.admin_user = users.create({"name": "Synthetic Admin", "login": "synthetic-admin", "group_ids": [Command.link(cls.env.ref("codestra_mail_inbox.group_mail_admin_user").id)]})
        cls.other_user = users.create({"name": "Synthetic Other Brand", "login": "synthetic-other", "group_ids": [Command.link(cls.env.ref("codestra_mail_inbox.group_mail_support_user").id)]})
        cls.auditor = users.create({"name": "Synthetic Auditor", "login": "synthetic-auditor", "group_ids": [Command.link(cls.env.ref("codestra_mail_inbox.group_mail_auditor").id)]})
        cls.ingestion_user = users.create({
            "name": "Synthetic Middleware Ingestion",
            "login": "synthetic-middleware-ingestion",
            "group_ids": [
                Command.link(
                    cls.env.ref(
                        "codestra_mail_inbox.group_mail_ingestion_service"
                    ).id
                )
            ],
        })
        cls.support.member_ids = [Command.link(cls.support_user.id)]
        cls.admin.member_ids = [Command.link(cls.admin_user.id)]
        cls.env.ref("codestra_mail_inbox.team_beyvra_support").member_ids = [Command.link(cls.other_user.id)]
        cls.support.auditor_ids = [Command.link(cls.auditor.id)]

    def _payload(self, number=1, recipient="support@codestra.co", **updates):
        values = {
            "event_id": f"event-{number}", "idempotency_key": f"idem-{number}",
            "correlation_id": f"corr-{number}", "timestamp": fields.Datetime.now(),
            "message_id": f"<message-{number}@synthetic.invalid>", "recipient": recipient,
            "sender": "fixture@synthetic.invalid", "subject": f"Synthetic {number}",
            "body_html": "<p>Hello</p><script>alert(1)</script>", "raw_size": 100,
            "authenticated_identity": "codestra-middleware", "signature_valid": True,
        }
        values.update(updates)
        return values

    def test_01_exact_fourteen_aliases(self):
        teams = self.env["codestra.mail.team"].search([
            ("queue_type_id.code", "in", ["SUPPORT", "BILLING"]),
            ("brand_id.domain", "!=", "booked4seasons.com"),
        ])
        self.assertEqual(len(teams), 28)
        self.assertEqual(len(set(teams.mapped("alias_id.alias_full_name"))), 28)
        self.assertFalse(self.env["mail.alias"].search_count([("alias_name", "in", ["catchall", "*"])]))

    def test_01b_all_aliases_route_and_sender_is_fixed(self):
        ledger = self.env["codestra.mail.inbound.event"]
        teams = self.env["codestra.mail.team"].search([
            ("queue_type_id.code", "in", ["SUPPORT", "BILLING"]),
            ("brand_id.domain", "!=", "booked4seasons.com"),
        ], order="id")
        for offset, team in enumerate(teams, 100):
            recipient = team.alias_id.alias_full_name
            conversation = ledger.ingest_event(self._payload(offset, recipient=recipient))
            self.assertEqual(conversation.team_id, team)
            self.assertEqual(conversation.recipient, recipient)
            self.assertEqual(conversation.prepare_outbound(f"out-{offset}")["sender"], recipient)

    def test_02_routing_threading_and_html(self):
        ledger = self.env["codestra.mail.inbound.event"]
        conversation = ledger.ingest_event(self._payload(10))
        reply = ledger.ingest_event(self._payload(11, in_reply_to="<message-10@synthetic.invalid>"))
        self.assertEqual(conversation, reply)
        bodies = " ".join(conversation.message_ids.mapped("body"))
        self.assertNotIn("<script", bodies.lower())

    def test_03_duplicate_replay_and_unknown(self):
        ledger = self.env["codestra.mail.inbound.event"]
        payload = self._payload(20)
        ledger.ingest_event(payload)
        with self.assertRaises(ValidationError): ledger.ingest_event(payload)
        with self.assertRaises(ValidationError): ledger.ingest_event(self._payload(21, idempotency_key="idem-20"))
        with self.assertRaises(ValidationError): ledger.ingest_event(self._payload(22, recipient="unknown@codestra.co"))
        with self.assertRaises(ValidationError): ledger.ingest_event(self._payload(23, timestamp=fields.Datetime.now() - timedelta(hours=1)))

    def test_04_attachment_policy(self):
        ledger = self.env["codestra.mail.inbound.event"]
        conversation = ledger.ingest_event(self._payload(30, attachments=[{
            "filename": "safe.txt", "mimetype": "text/plain",
            "content_base64": base64.b64encode(b"safe").decode(),
        }, {
            "filename": "blocked.exe", "mimetype": "application/octet-stream",
            "content_base64": base64.b64encode(b"blocked").decode(),
        }]))
        self.assertTrue(self.env["ir.attachment"].search_count([("res_model", "=", conversation._name), ("res_id", "=", conversation.id), ("name", "=", "safe.txt")]))
        self.assertTrue(self.env["codestra.mail.quarantine"].search_count([("correlation_id", "=", "corr-30")]))
        with self.assertRaises(ValidationError): ledger.ingest_event(self._payload(31, attachments=[{
            "filename": "large.txt", "mimetype": "text/plain",
            "content_base64": base64.b64encode(b"x" * (5 * 1024 * 1024 + 1)).decode(),
        }]))

    def test_05_sender_spoofing(self):
        conversation = self.env["codestra.mail.inbound.event"].ingest_event(self._payload(40))
        event = conversation.prepare_outbound("outbound-40")
        self.assertEqual(event["sender"], "support@codestra.co")
        self.assertFalse(event["external_delivery_enabled"])
        with self.assertRaises(ValidationError): conversation.prepare_outbound("outbound-41", "admin@codestra.co")

    def test_06_access_isolation(self):
        conversation = self.env["codestra.mail.inbound.event"].ingest_event(self._payload(50))
        self.assertEqual(self.env["codestra.mail.conversation"].with_user(self.support_user).search_count([("id", "=", conversation.id)]), 1)
        self.assertEqual(self.env["codestra.mail.conversation"].with_user(self.admin_user).search_count([("id", "=", conversation.id)]), 0)
        self.assertEqual(self.env["codestra.mail.conversation"].with_user(self.other_user).search_count([("id", "=", conversation.id)]), 0)
        self.assertEqual(self.env["codestra.mail.conversation"].with_user(self.auditor).search_count([("id", "=", conversation.id)]), 1)
        with self.assertRaises(AccessError): conversation.with_user(self.support_user).write({"team_id": self.admin.id})
        with self.assertRaises(AccessError): conversation.with_user(self.auditor).write({"name": "Denied"})

    def test_07_dedicated_ingestion_role_is_required_and_sufficient(self):
        model = self.env["codestra.mail.inbound.event"]
        with self.assertRaises(AccessError):
            model.with_user(self.support_user).ingest_event(self._payload(70))

        conversation = model.with_user(self.ingestion_user).ingest_event(
            self._payload(71)
        )
        self.assertEqual(conversation.recipient, "support@codestra.co")
        self.assertFalse(
            self.ingestion_user.has_group(
                "codestra_mail_inbox.group_mail_support_manager"
            )
        )

    def test_08_service_role_provisioning_uses_existing_authority(self):
        group = self.env.ref(
            "codestra_mail_inbox.group_mail_ingestion_service"
        )
        self.ingestion_user.group_ids = [Command.unlink(group.id)]
        self.env["ir.config_parameter"].sudo().set_param(
            "codestra.middleware.service_user_id", self.ingestion_user.id
        )
        self.assertTrue(
            self.env["res.users"]._provision_codestra_mail_ingestion_service()
        )
        self.assertIn(group, self.ingestion_user.group_ids)
