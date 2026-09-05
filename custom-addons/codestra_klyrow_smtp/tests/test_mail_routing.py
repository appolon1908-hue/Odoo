from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models.constants import (
    BEYVRA_DOMAIN,
    CANONICAL_TRACKING_HOST,
    CURRENT_SIGNED_INBOUND_DOMAINS,
    EXCLUDED_DOMAINS,
    LIVE_DELIVERY_PARAMETER,
    MANAGED_DOMAINS,
    SHARED_KLYROW_DOMAINS,
)


@tagged("post_install", "-at_install")
class TestKlyrowSmtpRouting(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.shared = cls.env.ref(
            "codestra_klyrow_smtp.mail_server_klyrow_production"
        )
        cls.beyvra = cls.env.ref(
            "codestra_klyrow_smtp.mail_server_beyvra_production"
        )

    def test_01_exact_fail_closed_server_inventory(self):
        self.assertEqual(
            set(self.shared._parse_from_filter(self.shared.from_filter)),
            set(SHARED_KLYROW_DOMAINS),
        )
        self.assertEqual(
            self.beyvra._parse_from_filter(self.beyvra.from_filter),
            [BEYVRA_DOMAIN],
        )
        for server in self.shared | self.beyvra:
            self.assertEqual(server.smtp_host, "mail.klyrow.com")
            self.assertEqual(server.smtp_port, 25)
            self.assertEqual(server.smtp_encryption, "starttls_strict")
            self.assertEqual(server.smtp_authentication, "login")
            self.assertFalse(server.active)
            self.assertFalse(server.smtp_pass)
            self.assertEqual(server.codestra_tracking_host, CANONICAL_TRACKING_HOST)
        self.assertEqual(self.shared.codestra_credential_state, "hold")
        self.assertEqual(self.beyvra.codestra_credential_state, "missing")

    def test_02_all_managed_brands_are_routed_without_booked4seasons(self):
        brands = self.env["codestra.mail.brand"].search(
            [("domain", "in", sorted(MANAGED_DOMAINS))]
        )
        self.assertEqual(set(brands.mapped("domain")), set(MANAGED_DOMAINS))
        self.assertTrue(all(brands.mapped("active")))
        for brand in brands:
            self.assertTrue(brand.outbound_server_id.codestra_managed)
            self.assertEqual(brand.klyrow_inbound_target, "signed_adapter")
            self.assertEqual(
                brand.klyrow_tracking_host,
                CANONICAL_TRACKING_HOST,
            )
            expected_observed = (
                "signed_adapter"
                if brand.domain in CURRENT_SIGNED_INBOUND_DOMAINS
                else "gmail_forward"
            )
            self.assertEqual(brand.klyrow_inbound_observed, expected_observed)

        excluded = (
            self.env["codestra.mail.brand"]
            .with_context(active_test=False)
            .search([("domain", "in", sorted(EXCLUDED_DOMAINS))])
        )
        self.assertTrue(excluded)
        self.assertFalse(any(excluded.mapped("active")))
        teams = (
            self.env["codestra.mail.team"]
            .with_context(active_test=False)
            .search([("brand_id", "in", excluded.ids)])
        )
        self.assertFalse(any(teams.mapped("active")))
        senders = (
            self.env["codestra.mail.sender.allowlist"]
            .with_context(active_test=False)
            .search([("team_id", "in", teams.ids)])
        )
        self.assertFalse(any(senders.mapped("active")))

        active_managed_teams = self.env["codestra.mail.team"].search(
            [
                ("brand_id.domain", "in", sorted(MANAGED_DOMAINS)),
                ("queue_type_id.code", "in", ["SUPPORT", "BILLING"]),
            ]
        )
        self.assertEqual(len(active_managed_teams), 28)
        self.assertFalse(
            self.env["codestra.mail.team"].search_count(
                [
                    ("brand_id.domain", "in", sorted(MANAGED_DOMAINS)),
                    ("queue_type_id.code", "=", "ADMINISTRATION"),
                ]
            )
        )

    def test_03_managed_sender_never_falls_back(self):
        self.env["ir.mail_server"].create(
            {
                "name": "Synthetic fallback",
                "smtp_host": "smtp.invalid",
                "smtp_port": 25,
                "smtp_encryption": "none",
                "smtp_authentication": "login",
                "active": True,
                "sequence": 1,
            }
        )
        with self.assertRaises(UserError):
            self.env["ir.mail_server"]._find_mail_server("support@codestra.co")

    def test_04_prepared_outbound_is_exact_but_closed(self):
        team = self.env.ref("codestra_mail_inbox.team_codestra_support")
        conversation = self.env["codestra.mail.conversation"].create(
            {
                "name": "Synthetic routing",
                "team_id": team.id,
                "sender": "fixture@synthetic.invalid",
                "source_message_id": "<klyrow-routing@synthetic.invalid>",
                "correlation_id": "klyrow-routing",
            }
        )
        result = conversation.prepare_outbound("klyrow-routing-outbound")
        self.assertEqual(result["mail_server_id"], self.shared.id)
        self.assertEqual(result["sender"], "support@codestra.co")
        self.assertEqual(result["provider"], "klyrow")
        self.assertEqual(result["tracking_host"], CANONICAL_TRACKING_HOST)
        self.assertFalse(result["external_delivery_enabled"])

    def test_05_all_activation_gates_are_required(self):
        self.env["ir.config_parameter"].sudo().set_param(
            LIVE_DELIVERY_PARAMETER,
            "true",
        )
        self.shared.write(
            {
                "active": True,
                "smtp_pass": "synthetic-not-a-real-secret",
                "codestra_credential_state": "active",
                "codestra_secret_loaded_at": fields.Datetime.now(),
            }
        )
        with patch.dict(
            "os.environ",
            {
                "ENABLE_EXTERNAL_DELIVERY": "false",
                "EMAIL_DELIVERY": "false",
                "LIVE_EMAIL_DELIVERY": "false",
            },
            clear=False,
        ):
            self.shared.invalidate_recordset(
                [
                    "codestra_secret_loaded",
                    "codestra_delivery_ready",
                    "codestra_readiness_message",
                ]
            )
            self.assertFalse(self.shared.codestra_delivery_ready)
            with self.assertRaises(UserError):
                self.shared._ensure_codestra_delivery_ready()

    def test_06_excluded_alias_cannot_create_a_conversation(self):
        team = (
            self.env["codestra.mail.team"]
            .with_context(active_test=False)
            .search([("brand_id.domain", "in", sorted(EXCLUDED_DOMAINS))], limit=1)
        )
        self.assertTrue(team)
        with self.assertRaises(ValidationError):
            self.env["codestra.mail.conversation"].message_new(
                {
                    "subject": "Rejected",
                    "email_from": "fixture@synthetic.invalid",
                    "to": team.alias_id.alias_full_name,
                },
                custom_values={"team_id": team.id},
            )

    def test_07_direct_alias_ingestion_is_rejected_for_managed_domains(self):
        team = self.env.ref("codestra_mail_inbox.team_codestra_support")
        with self.assertRaises(AccessError):
            self.env["codestra.mail.conversation"].message_new(
                {
                    "subject": "Unsigned inbound",
                    "email_from": "fixture@synthetic.invalid",
                    "to": team.alias_id.alias_full_name,
                },
                custom_values={"team_id": team.id},
            )

    def test_08_signed_adapter_accepts_a_drifted_domain(self):
        recipient = "support@breero.shop"
        conversation = self.env["codestra.mail.inbound.event"].ingest_event(
            {
                "event_id": "klyrow-drifted-event",
                "idempotency_key": "klyrow-drifted-idempotency",
                "correlation_id": "klyrow-drifted-correlation",
                "timestamp": fields.Datetime.now(),
                "message_id": "<klyrow-drifted@synthetic.invalid>",
                "recipient": recipient,
                "sender": "fixture@synthetic.invalid",
                "subject": "Signed drifted route",
                "body_text": "Synthetic",
                "raw_size": 100,
                "authenticated_identity": "codestra-middleware",
                "signature_valid": True,
            }
        )
        self.assertEqual(conversation.recipient, recipient)
        self.assertEqual(conversation.brand_id.domain, "breero.shop")

    def test_09_provisioning_is_idempotent(self):
        before = self.env["codestra.mail.brand"].with_context(
            active_test=False
        ).search_count([])
        self.env["codestra.mail.brand"]._provision_klyrow_routing()
        self.env["codestra.mail.brand"]._provision_klyrow_routing()
        after = self.env["codestra.mail.brand"].with_context(
            active_test=False
        ).search_count([])
        self.assertEqual(before, after)
