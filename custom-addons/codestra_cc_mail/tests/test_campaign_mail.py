import base64
from datetime import timedelta

from odoo import SUPERUSER_ID, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCampaignMailIsolation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["cc.business.unit"]._adopt_legacy_records()
        cls.Campaign = cls.env["cc.campaign"].with_context(active_test=False)
        cls.Route = cls.env["cc.mail.route"]
        cls.Event = cls.env["cc.mail.inbound.event"]
        cls.Thread = cls.env["cc.mail.thread"]
        cls.campaign_a = cls.Campaign.search(
            [("code", "=", "COD-WEB-OUT")], limit=1
        )
        cls.campaign_b = cls.Campaign.search(
            [("id", "!=", cls.campaign_a.id)], limit=1
        )
        cls.requester = cls._create_user(
            "Mail Requester",
            "mail-requester@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.approver = cls._create_user(
            "Mail Approver",
            "mail-approver@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.service = cls._create_user(
            "Campaign Mail Service",
            "campaign-mail-service@example.invalid",
            [
                "base.group_user",
                "codestra_identity_provisioning.group_provisioning_service",
                "codestra_cc_mail.group_cc_mail_ingestion_service",
            ],
        )
        cls.agent_a = cls._create_user(
            "Campaign A Mail Agent",
            "campaign-a-mail-agent@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.agent_b = cls._create_user(
            "Campaign B Mail Agent",
            "campaign-b-mail-agent@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.membership_a = cls._activate_membership(
            cls.agent_a, cls.campaign_a, "MAIL-MEMBERSHIP-A"
        )
        cls.membership_b = cls._activate_membership(
            cls.agent_b, cls.campaign_b, "MAIL-MEMBERSHIP-B"
        )
        cls.route_a = cls._create_route(
            cls.campaign_a, "a-support", "MAIL-ROUTE-A"
        )
        cls.route_b = cls._create_route(
            cls.campaign_b, "b-support", "MAIL-ROUTE-B"
        )
        (
            cls.sender_a,
            cls.group_a,
            cls.distribution_a,
        ) = cls._configure_route_identity(cls.route_a, cls.membership_a, "a")
        (
            cls.sender_b,
            cls.group_b,
            cls.distribution_b,
        ) = cls._configure_route_identity(cls.route_b, cls.membership_b, "b")

    @classmethod
    def _create_user(cls, name, login, group_xmlids):
        groups = cls.env["res.groups"].browse(
            [cls.env.ref(xmlid).id for xmlid in group_xmlids]
        )
        return cls.env["res.users"].create(
            {"name": name, "login": login, "group_ids": [(6, 0, groups.ids)]}
        )

    @classmethod
    def _activate_membership(cls, user, campaign, ticket):
        employee = cls.env["hr.employee"].create(
            {
                "name": user.name,
                "user_id": user.id,
                "company_id": cls.env.company.id,
            }
        )
        membership = cls.env["cc.campaign.membership"].with_user(
            cls.requester
        ).create(
            {
                "user_id": user.id,
                "employee_id": employee.id,
                "campaign_id": campaign.id,
                "role": "agent",
                "requested_by_id": cls.requester.id,
                "source_ticket": ticket,
                "starts_at": fields.Datetime.now(),
            }
        )
        membership.with_user(cls.requester).action_submit_identity()
        operation = membership.with_user(cls.approver).action_approve_identity()
        operation.with_user(cls.service).action_record_readback(
            {
                target: {"status": "matched", "evidence_hash": "a" * 64}
                for target in operation.required_targets
            },
            f"staging://campaign-mail/{ticket.lower()}",
        )
        membership.with_user(cls.approver).action_activate()
        return membership

    @classmethod
    def _create_route(cls, campaign, local_part, ticket):
        route = cls.Route.with_user(cls.requester).create(
            {
                "name": f"{campaign.code} Support",
                "campaign_id": campaign.id,
                "route_class": "support",
                "direction": "both",
                "local_part": local_part,
                "domain": "staging.invalid",
                "source_ticket": ticket,
                "requested_by_id": cls.requester.id,
            }
        )
        route.with_user(cls.requester).action_submit()
        route.with_user(cls.approver).action_approve_for_staging()
        return route

    @classmethod
    def _configure_route_identity(cls, route, membership, suffix):
        sender = cls.env["cc.mail.sender.identity"].with_user(
            cls.requester
        ).create(
            {
                "campaign_id": route.campaign_id.id,
                "route_id": route.id,
                "display_name": route.name,
                "from_address": route.address,
                "reply_to_address": route.address,
                "signature_html": f"<p>{route.campaign_id.code} team</p>",
                "legal_footer_html": "<p>Staging only</p>",
                "tracking_domain": "tracking.staging.invalid",
            }
        )
        sender.with_user(cls.service).action_record_staging_readback(
            "b" * 64, "c" * 64
        )
        group = cls.env["cc.mail.distribution.group"].with_user(
            cls.requester
        ).create(
            {
                "name": f"{route.name} Distribution",
                "campaign_id": route.campaign_id.id,
                "route_id": route.id,
                "external_group_key": f"staging-{suffix}-support",
            }
        )
        group.with_user(cls.service).action_record_staging_readback("d" * 64)
        distribution = cls.env["cc.mail.distribution.membership"].with_user(
            cls.requester
        ).create(
            {
                "campaign_id": route.campaign_id.id,
                "distribution_group_id": group.id,
                "membership_id": membership.id,
            }
        )
        distribution.with_user(cls.service).action_record_staging_readback(
            "e" * 64
        )
        return sender, group, distribution

    def _payload(self, number, route=None, token=None, **updates):
        route = route or self.route_a
        values = {
            "event_id": f"cc-mail-event-{number}",
            "idempotency_key": f"cc-mail-idem-{number}",
            "correlation_id": f"cc-mail-correlation-{number}",
            "occurred_at": fields.Datetime.now(),
            "message_id": f"<cc-mail-{number}@staging.invalid>",
            "recipient": route.address,
            "sender": f"customer-{number}@example.invalid",
            "subject": f"Synthetic campaign mail {number}",
            "thread_token": token or f"thread-token-{number}",
            "body_html": "<p>Safe body</p><script>alert(1)</script>",
            "raw_size": 256,
            "integrity_hash": "f" * 64,
        }
        values.update(updates)
        return values

    def _ingest(self, payload):
        return self.Event.with_user(self.service).ingest_staging_event(payload)

    def test_route_approval_is_separate_unique_and_fail_closed(self):
        parameters = self.env["ir.config_parameter"].with_user(SUPERUSER_ID)
        self.assertEqual(parameters.get_param("CC_ENABLE_EMAIL_SEND"), "false")
        self.assertEqual(
            parameters.get_param("CC_ENABLE_EMAIL_INBOUND_MUTATION"), "false"
        )
        self.assertEqual(self.route_a.state, "testing")
        self.assertFalse(self.route_a.external_send_enabled)
        self.assertFalse(self.route_a.inbound_mutation_enabled)
        self.assertEqual(self.route_a.address, "a-support@staging.invalid")
        with self.assertRaises(ValidationError):
            self.Route.with_user(self.requester).create(
                {
                    "name": "Duplicate A Support",
                    "campaign_id": self.campaign_a.id,
                    "route_class": "support",
                    "direction": "inbound",
                    "local_part": "another-a-support",
                    "domain": "staging.invalid",
                    "source_ticket": "MAIL-DUPLICATE",
                    "requested_by_id": self.requester.id,
                }
            )
        with self.assertRaises(AccessError):
            self.route_a.with_user(self.approver).write(
                {"external_send_enabled": True}
            )

    def test_distribution_membership_cannot_cross_campaign(self):
        self.assertEqual(self.distribution_a.state, "matched")
        self.assertEqual(self.distribution_a.user_id, self.agent_a)
        self.assertEqual(
            self.env["cc.mail.distribution.membership"]
            .with_user(self.agent_a)
            .search([]),
            self.distribution_a,
        )
        with self.assertRaises(ValidationError):
            self.env["cc.mail.distribution.membership"].with_user(
                self.requester
            ).create(
                {
                    "campaign_id": self.campaign_a.id,
                    "distribution_group_id": self.group_a.id,
                    "membership_id": self.membership_b.id,
                }
            )
        billing_route = self.Route.with_user(self.requester).create(
            {
                "name": "Campaign A Billing",
                "campaign_id": self.campaign_a.id,
                "route_class": "billing",
                "direction": "both",
                "local_part": "a-billing",
                "domain": "staging.invalid",
                "source_ticket": "MAIL-BILLING-ROUTE",
                "requested_by_id": self.requester.id,
            }
        )
        billing_route.with_user(self.requester).action_submit()
        billing_route.with_user(self.approver).action_approve_for_staging()
        with self.assertRaises(AccessError):
            self.env["cc.mail.distribution.group"].with_user(
                self.requester
            ).create(
                {
                    "name": "Forged Matched Group",
                    "campaign_id": self.campaign_a.id,
                    "route_id": billing_route.id,
                    "external_group_key": "forged-matched-group",
                    "state": "matched",
                }
            )

    def test_inbound_alias_controls_scope_and_outbound_identity(self):
        payload = self._payload(
            10,
            supplied_campaign_id=self.campaign_b.id,
            body_html="<p>Hello</p><script>forbidden()</script>",
        )
        event = self._ingest(payload)
        thread = event.thread_id
        self.assertEqual(event.state, "processed")
        self.assertEqual(event.event_type, "cc.email.received.v1")
        self.assertEqual(thread.campaign_id, self.campaign_a)
        self.assertEqual(thread.route_id, self.route_a)
        self.assertEqual(thread.recipient, self.route_a.address)
        self.assertNotIn("forbidden", " ".join(thread.message_ids.mapped("body")))
        envelope = thread.with_user(self.agent_a).prepare_outbound("outbound-10")
        self.assertEqual(envelope["from"], self.route_a.address)
        self.assertEqual(envelope["reply_to"], self.route_a.address)
        self.assertFalse(envelope["external_send_enabled"])
        with self.assertRaises(ValidationError):
            thread.with_user(self.agent_a).prepare_outbound(
                "outbound-spoof", self.route_b.address
            )

    def test_cross_campaign_thread_token_is_quarantined(self):
        first = self._ingest(self._payload(20, route=self.route_a, token="shared-token"))
        original_messages = len(first.thread_id.message_ids)
        mismatch = self._ingest(
            self._payload(21, route=self.route_b, token="shared-token")
        )
        self.assertEqual(mismatch.state, "quarantined")
        self.assertEqual(mismatch.event_type, "cc.email.quarantined.v1")
        self.assertFalse(mismatch.thread_id)
        quarantine = self.env["cc.mail.quarantine"].search(
            [("event_id", "=", mismatch.id)]
        )
        self.assertEqual(quarantine.reason, "THREAD_CAMPAIGN_MISMATCH")
        self.assertEqual(quarantine.campaign_id, self.campaign_b)
        self.assertEqual(len(first.thread_id.message_ids), original_messages)

    def test_attachment_policy_tags_clean_and_quarantines_unsafe(self):
        event = self._ingest(
            self._payload(
                30,
                attachments=[
                    {
                        "filename": "safe.txt",
                        "mimetype": "text/plain",
                        "content_base64": base64.b64encode(b"safe").decode(),
                        "scan_status": "clean",
                        "scan_evidence_hash": "1" * 64,
                    },
                    {
                        "filename": "blocked.exe",
                        "mimetype": "application/octet-stream",
                        "content_base64": base64.b64encode(b"blocked").decode(),
                        "scan_status": "clean",
                        "scan_evidence_hash": "2" * 64,
                    },
                ],
            )
        )
        attachment = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "cc.mail.thread"),
                ("res_id", "=", event.thread_id.id),
                ("name", "=", "safe.txt"),
            ]
        )
        self.assertEqual(attachment.cc_campaign_id, self.campaign_a)
        self.assertEqual(attachment.cc_scan_state, "clean")
        self.assertEqual(len(attachment.cc_content_hash), 64)
        quarantine = self.env["cc.mail.quarantine"].search(
            [("route_id", "=", self.route_a.id), ("reason", "=", "ATTACHMENT_POLICY_REJECTED")]
        )
        self.assertTrue(quarantine)
        self.assertFalse(
            self.env["ir.attachment"].search(
                [("res_id", "=", event.thread_id.id), ("name", "=", "blocked.exe")]
            )
        )
        with self.assertRaises(AccessError):
            self.env["ir.attachment"].with_user(self.agent_a).create(
                {
                    "name": "forged-clean.txt",
                    "datas": base64.b64encode(b"forged"),
                    "mimetype": "text/plain",
                    "res_model": event.thread_id._name,
                    "res_id": event.thread_id.id,
                    "cc_scan_state": "clean",
                    "cc_scan_evidence_hash": "5" * 64,
                    "cc_content_hash": "6" * 64,
                }
            )

    def test_chatter_followers_activities_and_attachments_are_scoped(self):
        event_b = self._ingest(
            self._payload(
                40,
                route=self.route_b,
                attachments=[
                    {
                        "filename": "campaign-b.txt",
                        "mimetype": "text/plain",
                        "content_base64": base64.b64encode(b"campaign-b").decode(),
                        "scan_status": "clean",
                        "scan_evidence_hash": "3" * 64,
                    }
                ],
            )
        )
        thread_b = event_b.thread_id
        follower_b = self.env["mail.followers"].create(
            {
                "res_model": thread_b._name,
                "res_id": thread_b.id,
                "partner_id": self.agent_b.partner_id.id,
            }
        )
        activity_b = self.env["mail.activity"].create(
            {
                "res_model_id": self.env["ir.model"]._get_id(thread_b._name),
                "res_id": thread_b.id,
                "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
                "summary": "Campaign B follow-up",
                "user_id": self.agent_b.id,
                "date_deadline": fields.Date.today(),
            }
        )
        message_b = thread_b.message_ids.filtered(
            lambda message: message.message_type == "comment"
        )[-1]
        attachment_b = self.env["ir.attachment"].search(
            [("res_model", "=", thread_b._name), ("res_id", "=", thread_b.id)]
        )
        self.assertEqual(message_b.cc_campaign_id, self.campaign_b)
        self.assertEqual(follower_b.cc_campaign_id, self.campaign_b)
        self.assertEqual(activity_b.cc_campaign_id, self.campaign_b)
        self.assertEqual(attachment_b.cc_campaign_id, self.campaign_b)

        self.assertFalse(
            self.Thread.with_user(self.agent_a).search([("id", "=", thread_b.id)])
        )
        with self.assertRaises(AccessError):
            thread_b.with_user(self.agent_a).read(["subject"])
        self.assertFalse(
            self.env["mail.message"].with_user(self.agent_a).search(
                [("id", "=", message_b.id)]
            )
        )
        self.assertFalse(
            self.env["mail.followers"].with_user(self.agent_a).search(
                [("id", "=", follower_b.id)]
            )
        )
        self.assertFalse(
            self.env["mail.activity"].with_user(self.agent_a).search(
                [("id", "=", activity_b.id)]
            )
        )
        self.assertFalse(
            self.env["ir.attachment"].with_user(self.agent_a).search(
                [("id", "=", attachment_b.id)]
            )
        )
        with self.assertRaises(ValidationError):
            self.env["mail.followers"].create(
                {
                    "res_model": thread_b._name,
                    "res_id": thread_b.id,
                    "partner_id": self.agent_a.partner_id.id,
                }
            )

    def test_agent_query_and_mutation_surfaces_do_not_cross_scope(self):
        event_a = self._ingest(self._payload(50, route=self.route_a))
        event_b = self._ingest(self._payload(51, route=self.route_b))
        ThreadA = self.Thread.with_user(self.agent_a)
        self.assertEqual(ThreadA.search([]), event_a.thread_id)
        self.assertFalse(
            ThreadA.name_search(event_b.thread_id.subject, operator="=", limit=10)
        )
        grouped = ThreadA.read_group([], ["record_count:count(id)"], ["state"])
        self.assertEqual(sum(item["record_count"] for item in grouped), 1)
        with self.assertRaises(UserError):
            ThreadA.search([]).export_data(["subject"])
        with self.assertRaises(AccessError):
            event_b.thread_id.with_user(self.agent_a).copy()
        with self.assertRaises(AccessError):
            event_b.thread_id.with_user(self.agent_a).message_post(
                body="Attempted cross-campaign chatter"
            )
        with self.assertRaises(AccessError):
            event_a.thread_id.with_user(self.agent_a).write(
                {"campaign_id": self.campaign_b.id}
            )
        with self.assertRaises(AccessError):
            self.Route.with_user(self.agent_a).create(
                {
                    "name": "Forged B Route",
                    "campaign_id": self.campaign_b.id,
                    "route_class": "billing",
                    "direction": "both",
                    "local_part": "forged-b",
                    "domain": "staging.invalid",
                    "source_ticket": "MAIL-FORGED",
                }
            )

    def test_replay_unknown_alias_and_stale_timestamp_fail_closed(self):
        payload = self._payload(60)
        self._ingest(payload)
        with self.assertRaises(ValidationError):
            self._ingest(payload)
        with self.assertRaises(ValidationError):
            self._ingest(
                self._payload(61, recipient="unknown@staging.invalid")
            )
        with self.assertRaises(ValidationError):
            self._ingest(
                self._payload(
                    62,
                    occurred_at=fields.Datetime.now() - timedelta(hours=1),
                )
            )

    def test_ingestion_service_and_immutable_ledgers_are_enforced(self):
        with self.assertRaises(AccessError):
            self.Event.with_user(self.agent_a).ingest_staging_event(
                self._payload(70)
            )
        with self.assertRaises(AccessError):
            self.Event.with_user(self.requester).create(
                {
                    "event_id": "forged",
                    "idempotency_key": "forged",
                    "correlation_id": "forged",
                    "message_id": "forged",
                    "route_id": self.route_a.id,
                    "campaign_id": self.campaign_a.id,
                    "state": "processed",
                    "event_type": "cc.email.received.v1",
                    "payload_hash": "4" * 64,
                    "received_at": fields.Datetime.now(),
                }
            )
        event = self._ingest(self._payload(71))
        with self.assertRaises(AccessError):
            event.with_user(self.requester).write({"state": "quarantined"})
        with self.assertRaises(AccessError):
            event.with_user(self.requester).unlink()

    def test_raw_thread_tokens_are_never_stored(self):
        raw_token = "secret-thread-token-never-store"
        event = self._ingest(self._payload(80, token=raw_token))
        self.assertNotEqual(event.thread_id.thread_token_hash, raw_token)
        self.assertEqual(len(event.thread_id.thread_token_hash), 64)
        serialized = " ".join(
            [
                event.thread_id.thread_token_hash,
                event.payload_hash,
                event.message_id,
            ]
        )
        self.assertNotIn(raw_token, serialized)

    def test_legacy_campaign_chatter_is_mapped_to_canonical_scope(self):
        legacy_campaign = self.campaign_a.legacy_campaign_id
        message = legacy_campaign.with_context(
            mail_create_nosubscribe=True, mail_post_autofollow=False
        ).message_post(
            body="Synthetic legacy campaign chatter",
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )
        self.assertEqual(message.cc_campaign_id, self.campaign_a)
