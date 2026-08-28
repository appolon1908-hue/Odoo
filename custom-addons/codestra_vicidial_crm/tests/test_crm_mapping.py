from odoo.tests.common import TransactionCase


class TestCrmMapping(TransactionCase):
    def test_call_links_to_crm_lead(self):
        lead = self.env["crm.lead"].create({"name": "Staging Lead"})
        call = self.env["codestra.vicidial.call"].create(
            {
                "name": "Staging Call",
                "uniqueid": "crm-map-test",
                "crm_lead_id": lead.id,
                "duration_seconds": 0,
                "billable_seconds": 0,
            }
        )
        self.assertEqual(call.crm_lead_id, lead)
