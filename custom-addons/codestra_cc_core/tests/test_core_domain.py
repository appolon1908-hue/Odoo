from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCodestraCcCoreDomain(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Unit = cls.env["cc.business.unit"].with_context(active_test=False)
        cls.Campaign = cls.env["cc.campaign"].with_context(active_test=False)
        cls.Channel = cls.env["cc.campaign.channel"].with_context(active_test=False)
        cls.Policy = cls.env["cc.campaign.policy"].with_context(active_test=False)
        cls.Unit._adopt_legacy_records()
        cls.unit = cls.Unit.search([("code", "=", "COD")], limit=1)
        cls.campaign = cls.Campaign.search([("code", "=", "COD-WEB-OUT")], limit=1)

    def test_dependencies_and_canonical_models_are_available(self):
        expected = {
            "call_center_core",
            "codestra_interaction_workflow",
            "codestra_vicidial_crm",
        }
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
        self.assertTrue(self.unit)
        self.assertTrue(self.campaign)

    def test_adoption_is_complete_one_to_one_and_idempotent(self):
        first = self.Unit._adopt_legacy_records()
        second = self.Unit._adopt_legacy_records()
        legacy_units = self.env["call.center.business.unit"].with_context(
            active_test=False
        ).search_count([])
        legacy_campaigns = self.env["call.center.campaign"].with_context(
            active_test=False
        ).search_count([])
        legacy_mappings = self.env["call.center.campaign.mapping"].with_context(
            active_test=False
        ).search_count([])
        self.assertEqual(first, second)
        self.assertEqual(first["business_units"], legacy_units)
        self.assertEqual(first["campaigns"], legacy_campaigns)
        self.assertEqual(first["channels"], legacy_mappings)
        self.assertEqual(
            len(set(self.Unit.search([]).mapped("legacy_business_unit_id").ids)),
            legacy_units,
        )
        self.assertEqual(
            len(set(self.Campaign.search([]).mapped("legacy_campaign_id").ids)),
            legacy_campaigns,
        )

    def test_new_legacy_records_are_adopted_without_copying_business_fields(self):
        legacy_unit = self.env["call.center.business.unit"].create(
            {"name": "Auto Adoption Unit", "code": "AUT"}
        )
        canonical_unit = self.Unit.search(
            [("legacy_business_unit_id", "=", legacy_unit.id)], limit=1
        )
        self.assertTrue(canonical_unit)
        self.assertEqual(canonical_unit.name, legacy_unit.name)
        legacy_campaign = self.env["call.center.campaign"].create(
            {
                "name": "Auto Adoption Campaign",
                "code": "AUT-ADOPT-OUT",
                "business_unit_id": legacy_unit.id,
                "active": False,
            }
        )
        canonical_campaign = self.Campaign.search(
            [("legacy_campaign_id", "=", legacy_campaign.id)], limit=1
        )
        self.assertTrue(canonical_campaign)
        self.assertEqual(canonical_campaign.cc_business_unit_id, canonical_unit)
        self.assertEqual(canonical_campaign.code, legacy_campaign.code)

    def test_workspace_reuses_legacy_owner_and_stays_disabled(self):
        self.assertEqual(
            self.campaign.cc_business_unit_id.legacy_business_unit_id,
            self.campaign.legacy_campaign_id.business_unit_id,
        )
        self.assertFalse(self.campaign.live_enabled)
        self.assertFalse(self.campaign.production_eligible)
        self.assertNotEqual(self.campaign.lifecycle_state, "active")
        with self.assertRaises(ValidationError):
            self.campaign.write({"live_enabled": True})
        with self.assertRaises(ValidationError):
            self.campaign.transition_to("active")

    def test_workspace_owner_and_identity_are_immutable(self):
        other_unit = self.Unit.search([("id", "!=", self.unit.id)], limit=1)
        with self.assertRaises(AccessError):
            self.campaign.write({"cc_business_unit_id": other_unit.id})
        with self.assertRaises(AccessError):
            self.campaign.write({"workspace_uuid": "replacement"})

    def test_callback_compatibility_channels_are_not_login_targets(self):
        callback_channels = self.Channel.search(
            [("technical_callback_compatibility", "=", True)]
        )
        self.assertTrue(callback_channels)
        self.assertFalse(any(callback_channels.mapped("agent_login_allowed")))
        self.assertFalse(any(callback_channels.mapped("active")))
        channel = callback_channels[0]
        with self.assertRaises(ValidationError):
            channel.write({"agent_login_allowed": True})

    def test_policy_hash_is_deterministic_and_approved_versions_are_immutable(self):
        policy = self.Policy.create(
            {
                "campaign_id": self.campaign.id,
                "name": "Callback Policy",
                "policy_type": "callback",
                "version": 1,
                "settings_json": {"same_campaign_only": True, "publish": False},
            }
        )
        expected_hash = policy.policy_hash
        policy.settings_json = {"publish": False, "same_campaign_only": True}
        self.assertEqual(policy.policy_hash, expected_hash)
        with self.assertRaises(AccessError):
            policy.write({"state": "approved"})
        policy.with_context(cc_security_approval=True).write({"state": "approved"})
        with self.assertRaises(AccessError):
            policy.write({"settings_json": {"publish": True}})

    def test_policy_effective_period_must_increase(self):
        with self.assertRaises(ValidationError):
            self.Policy.create(
                {
                    "campaign_id": self.campaign.id,
                    "name": "Invalid Recording Policy",
                    "policy_type": "recording",
                    "version": 1,
                    "effective_from": "2026-08-29 00:00:00",
                    "effective_to": "2026-08-28 00:00:00",
                    "settings_json": {"playback": False},
                }
            )
