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
