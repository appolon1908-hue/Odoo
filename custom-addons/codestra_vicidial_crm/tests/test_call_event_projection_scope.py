import uuid

from odoo.tests.common import TransactionCase


class TestCallEventProjectionScope(TransactionCase):
    def test_phone_match_is_limited_to_requested_business_unit(self):
        first = self.env["call.center.business.unit"].create(
            {
                "name": "Projection Scope First",
                "code": "SCOPE_A_" + uuid.uuid4().hex[:8],
            }
        )
        second = self.env["call.center.business.unit"].create(
            {
                "name": "Projection Scope Second",
                "code": "SCOPE_B_" + uuid.uuid4().hex[:8],
            }
        )
        number = "+18095559876"
        authorized = self.env["res.partner"].create(
            {
                "name": "Authorized Projection Match",
                "phone": number,
                "business_unit_id": first.id,
            }
        )
        self.env["res.partner"].create(
            {
                "name": "Other Unit Projection Match",
                "phone": number,
                "business_unit_id": second.id,
            }
        )

        result = self.env["codestra.vicidial.call"].match_customer(
            number,
            business_unit_id=first.id,
        )

        self.assertEqual(result["match"], "exact")
        self.assertEqual(result["matches"], [
            {
                "model": "partner",
                "id": authorized.id,
                "name": authorized.display_name,
            }
        ])

    def test_campaign_filter_rejects_other_campaign_lead_and_contact(self):
        unit = self.env.ref("call_center_core.business_unit_digital")
        number = "+18095559875"
        partner = self.env["res.partner"].create({
            "name": "Other Campaign Contact", "phone": number,
            "business_unit_id": unit.id,
        })
        self.env["crm.lead"].create({
            "name": "Other Campaign Lead", "phone": number,
            "business_unit_id": unit.id, "vicidial_campaign_id": "SYN-B",
            "partner_id": partner.id,
        })
        Call = self.env["codestra.vicidial.call"]
        denied = Call.match_customer(number, "SYN-A", business_unit_id=unit.id)
        self.assertEqual(denied["match"], "none")
        self.assertEqual(denied["matches"], [])
        owned = self.env["crm.lead"].create({
            "name": "Owned Campaign Lead", "phone": number,
            "business_unit_id": unit.id, "vicidial_campaign_id": "SYN-A",
        })
        allowed = Call.match_customer(number, "SYN-A", business_unit_id=unit.id)
        self.assertEqual(allowed["match"], "exact")
        self.assertEqual([row["id"] for row in allowed["matches"]], owned.ids)

    def test_canonical_campaign_cannot_be_overridden_by_stale_alias(self):
        unit = self.env.ref("call_center_core.business_unit_digital")
        campaign = self.env["call.center.campaign"].create({
            "name": "Canonical Rematch B", "code": "COD-REMATCH-B",
            "business_unit_id": unit.id, "design_automation_enabled": False,
            "vicidial_campaign_id": "SYN-B",
        })
        number = "+18095559874"
        self.env["crm.lead"].create({
            "name": "Stale Alias Lead", "phone": number,
            "business_unit_id": unit.id, "call_center_campaign_id": campaign.id,
            "vicidial_campaign_id": "SYN-A", "x_vicidial_campaign_id": "SYN-A",
        })
        result = self.env["codestra.vicidial.call"].match_customer(
            number, "SYN-A", business_unit_id=unit.id,
        )
        self.assertEqual(result["matches"], [])
