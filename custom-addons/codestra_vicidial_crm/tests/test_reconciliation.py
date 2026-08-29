from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, new_test_user
from psycopg2 import IntegrityError


class TestCoreReconciliation(TransactionCase):
    def test_legacy_groups_bridge_without_membership_loss(self):
        agent_user = new_test_user(
            self.env,
            login="codestra_bridge_agent",
            groups="codestra_vicidial_crm.group_agent",
            context={"no_reset_password": True},
        )
        self.assertTrue(agent_user.has_group("codestra_vicidial_crm.group_agent"))
        self.assertTrue(agent_user.has_group("codestra_base.group_codestra_agent"))
        self.assertIn(
            self.env.ref("codestra_base.group_codestra_integration_admin"),
            self.env.ref("codestra_vicidial_crm.group_integration_admin").implied_ids,
        )

    def test_call_constraints_and_relationships(self):
        lead = self.env["crm.lead"].create({"name": "Phase 3B synthetic lead"})
        values = {
            "name": "Phase 3B synthetic call",
            "uniqueid": "phase3b-unique-call",
            "crm_lead_id": lead.id,
            "duration_seconds": 0,
            "billable_seconds": 0,
        }
        call = self.env["codestra.vicidial.call"].create(values)
        self.assertEqual(call.crm_lead_id, lead)
        call.write({"status": "verified"})
        with self.assertRaises(IntegrityError):
            self.env["codestra.vicidial.call"].create(values)
        with self.assertRaises(IntegrityError):
            self.env["codestra.vicidial.call"].create(
                {
                    "name": "Invalid duration",
                    "duration_seconds": -1,
                    "billable_seconds": 0,
                }
            )

    def test_callback_and_disposition_validation(self):
        lead = self.env["crm.lead"].create({"name": "Callback synthetic lead"})
        campaign = self.env["codestra.vicidial.campaign"].create(
            {
                "name": "Callback campaign",
                "campaign_id": "CALLBACK_SYN",
                "mode": "test",
            }
        )
        call = self.env["codestra.vicidial.call"].create(
            {
                "name": "Callback source",
                "crm_lead_id": lead.id,
                "tenant_id": "COD",
                "campaign_id": campaign.id,
                "duration_seconds": 0,
                "billable_seconds": 0,
            }
        )
        callback = self.env["codestra.callback"].create(
            {
                "name": "Future callback",
                "lead_id": lead.id,
                "owner_id": self.env.user.id,
                "call_id": call.id,
                "tenant_id": "COD",
                "vicidial_campaign_id": campaign.id,
                "phone": "+18095550100",
                "scheduled_at": fields.Datetime.now() + timedelta(days=1),
                "timezone": "UTC",
                "reason": "Synthetic test",
            }
        )
        self.assertEqual(callback.status, "scheduled")
        self.assertEqual(callback.vicidial_campaign_id, campaign)
        with self.assertRaises(ValidationError):
            self.env["codestra.callback"].create(
                {
                    "name": "Past callback",
                    "lead_id": lead.id,
                    "owner_id": self.env.user.id,
                    "call_id": call.id,
                    "tenant_id": "COD",
                    "vicidial_campaign_id": campaign.id,
                    "phone": "+18095550100",
                    "scheduled_at": fields.Datetime.now() - timedelta(days=1),
                    "timezone": "UTC",
                    "reason": "Synthetic test",
                }
            )
        self.assertTrue(self.env["codestra.vicidial.disposition"].search([("code", "=", "NEW")]))
        self.assertEqual(self.env["crm.lead"].normalize_codestra_phone("+1 (809) 555-0100"), "+18095550100")

    def test_existing_xml_ids_and_flags(self):
        for xmlid in (
            "codestra_vicidial_crm.group_agent",
            "codestra_vicidial_crm.menu_codestra_root",
            "codestra_vicidial_crm.model_codestra_vicidial_call",
            "codestra_vicidial_crm.model_codestra_vicidial_sync_event",
        ):
            self.assertTrue(self.env.ref(xmlid))
        params = self.env["ir.config_parameter"].sudo()
        for name in (
            "live_writes_enabled",
            "vicidial_read_enabled",
            "vicidial_write_enabled",
            "odoo_sync_enabled",
            "n8n_delivery_enabled",
            "agent_api_read_enabled",
            "agent_api_write_enabled",
            "call_control_enabled",
            "transfer_control_enabled",
            "recording_access_enabled",
            "ai_advisory_enabled",
            "ai_external_delivery_enabled",
        ):
            self.assertNotEqual(params.get_param(f"codestra.{name}", "false"), "true")
