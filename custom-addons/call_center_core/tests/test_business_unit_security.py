from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBusinessUnitSecurity(TransactionCase):
    def setUp(self):
        super().setUp()
        self.unit_a = self.env["call.center.business.unit"].create(
            {"name": "A", "code": "TEST-A"}
        )
        self.unit_b = self.env["call.center.business.unit"].create(
            {"name": "B", "code": "TEST-B"}
        )
        group = self.env.ref("call_center_core.group_call_center_agent")
        self.user = self.env["res.users"].create(
            {
                "name": "Scoped Agent",
                "login": "scoped-agent@example.invalid",
                "group_ids": [(6, 0, group.ids)],
                "call_center_business_unit_ids": [(6, 0, self.unit_a.ids)],
                "call_center_default_business_unit_id": self.unit_a.id,
            }
        )

    def test_new_user_defaults_to_non_operational_role(self):
        user = self.env["res.users"].create(
            {
                "name": "Non-Operational User",
                "login": "non-operational@example.invalid",
            }
        )
        self.assertEqual(user.call_center_primary_role, "non_operational")
        self.assertFalse(
            user.has_group("call_center_core.group_call_center_agent")
        )

    def test_required_identity_role_values_are_declared(self):
        selection = dict(
            self.env["res.users"]._fields[
                "call_center_primary_role"
            ].get_description(self.env)["selection"]
        )
        self.assertTrue(
            {
                "non_operational",
                "global_administrator",
                "agent",
                "closer",
                "supervisor",
                "qa_analyst",
                "campaign_manager",
                "compliance_reviewer",
                "auditor",
                "integration_service",
            }.issubset(selection)
        )

    def test_default_unit_must_be_authorized(self):
        with self.assertRaises(ValidationError):
            self.user.call_center_default_business_unit_id = self.unit_b

    def test_lead_cross_unit_is_hidden(self):
        values = {"name": "Unit B Lead", "business_unit_id": self.unit_b.id}
        if "call_center_campaign_id" in self.env["crm.lead"]._fields:
            values["call_center_campaign_id"] = self.env[
                "call.center.campaign"
            ].create(
                {
                    "name": "Unit B Test Campaign",
                    "code": "TEST-B-SECURITY",
                    "business_unit_id": self.unit_b.id,
                }
            ).id
        lead = self.env["crm.lead"].create(
            values
        )
        visible = self.env["crm.lead"].with_user(self.user).search(
            [("id", "=", lead.id)]
        )
        self.assertFalse(visible)

    def test_unscoped_lead_defaults_to_shared_services(self):
        lead = self.env["crm.lead"].create({"name": "Legacy-safe default"})
        self.assertEqual(
            lead.business_unit_id,
            self.env.ref("call_center_core.business_unit_shared"),
        )

    def test_authoritative_feature_flags_default_false(self):
        flags = self.env["call.center.feature.flag"].search([])
        self.assertEqual(len(flags), 16)
        self.assertFalse(any(flags.mapped("enabled")))

    def test_production_flag_requires_activation_reference(self):
        flag = self.env.ref("call_center_core.flag_production_traffic")
        with self.assertRaises(ValidationError):
            flag.enabled = True
