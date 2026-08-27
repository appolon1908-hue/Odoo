from datetime import datetime, timedelta

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "test_syn_certification")
class TestSyntheticCrmMutations(TransactionCase):
    def setUp(self):
        super().setUp()
        self.mutations = self.env["codestra.crm.mutation"].with_context(
            _test_syn_certification=True
        )
        self.base_time = datetime(2026, 8, 12, 12, 0, 0)
        self.lead_ref = "00000000-0000-5000-8000-000000006198"

    def payload(self, event_id, status="ANSWERED", minutes=0, **extra):
        values = {
            "event_id": event_id,
            "idempotency_key": "vicidial-event:v1:%s" % event_id,
            "occurred_at": self.base_time + timedelta(minutes=minutes),
            "status": status,
            "lead_ref": self.lead_ref,
            "note": "Synthetic certification note",
        }
        values.update(extra)
        return values

    def test_mapping_is_disabled_and_complete(self):
        mapping = self.env.ref("codestra_odoo_certification.mapping_test_syn")
        self.assertFalse(mapping.active)
        self.assertFalse(mapping.production_eligible)
        self.assertEqual(mapping.desired_state, "inactive")
        self.assertFalse(mapping.company_id.active)
        self.assertFalse(mapping.crm_team_id.active)
        self.assertFalse(mapping.campaign_id.active)
        statuses = self.env["codestra.disposition"].with_context(active_test=False).search([
            ("campaign_id", "=", mapping.campaign_id.id)
        ]).mapped("vicidial_status_code")
        self.assertEqual(set(statuses), {
            "SALE", "CALLBK", "BUSY", "NA", "NI", "DNC", "WRONG",
            "DISCONNECTED", "ANSWERED", "TRANSFER", "APPOINTMENT",
        })

    def test_create_duplicate_conflict_update_and_stale(self):
        first = self.payload("evt-create")
        result = self.mutations.apply_test_syn(first)
        self.assertEqual(result["result"], "applied")
        lead = self.env["crm.lead"].browse(result["lead_id"])
        self.assertFalse(lead.phone)
        self.assertEqual(lead.team_id, self.env.ref("codestra_odoo_certification.team_test_syn"))
        self.assertEqual(self.mutations.apply_test_syn(first)["result"], "duplicate")
        conflict = dict(first, status="SALE")
        with self.assertRaisesRegex(ValidationError, "Conflicting retry"):
            self.mutations.apply_test_syn(conflict)
        updated = self.mutations.apply_test_syn(self.payload("evt-update", "TRANSFER", 2))
        self.assertEqual(updated["lead_id"], lead.id)
        self.assertEqual(lead.x_vicidial_status, "TRANSFER")
        stale = self.mutations.apply_test_syn(self.payload("evt-stale", "BUSY", 1))
        self.assertEqual(stale["result"], "stale")
        self.assertEqual(lead.x_vicidial_status, "TRANSFER")

    def test_callback_reschedule_dnc_and_all_stage_results(self):
        result = self.mutations.apply_test_syn(
            self.payload("evt-callback", "CALLBK", activity_date="2026-08-13")
        )
        lead = self.env["crm.lead"].browse(result["lead_id"])
        callback = lead.activity_ids.filtered(lambda activity: activity.summary == "TEST_SYN callback")
        self.assertEqual(len(callback), 1)
        self.mutations.apply_test_syn(
            self.payload("evt-callback-2", "CALLBK", 1, activity_date="2026-08-14")
        )
        callback = lead.activity_ids.filtered(lambda activity: activity.summary == "TEST_SYN callback")
        self.assertEqual(len(callback), 1)
        self.assertEqual(str(callback.date_deadline), "2026-08-14")
        self.mutations.apply_test_syn(self.payload("evt-dnc", "DNC", 2))
        self.assertTrue(lead.x_do_not_call)
        self.assertTrue(lead.do_not_call)
        self.assertFalse(lead.x_contact_consent)
        dnc_stage = lead.stage_id
        self.mutations.apply_test_syn(self.payload("evt-post-dnc", "ANSWERED", 3))
        self.assertTrue(lead.x_do_not_call, "DNC suppression must be permanent")
        self.assertEqual(lead.stage_id, dnc_stage, "DNC stage must not be reopened")

        for index, status in enumerate(
            ["SALE", "BUSY", "NA", "NI", "WRONG", "DISCONNECTED", "TRANSFER", "APPOINTMENT"], 4
        ):
            outcome = self.mutations.apply_test_syn(
                self.payload("evt-%s" % status.lower(), status, index, activity_date="2026-08-20")
            )
            self.assertEqual(outcome["result"], "applied")
            self.assertEqual(lead.x_vicidial_status, status)

    def test_capability_required_and_retry_is_bounded(self):
        with self.assertRaisesRegex(Exception, "capability"):
            self.env["codestra.crm.mutation"].apply_test_syn(self.payload("evt-denied"))
        result = self.mutations.apply_test_syn(
            self.payload("evt-busy-retry", "BUSY", retry_count=99)
        )
        lead = self.env["crm.lead"].browse(result["lead_id"])
        self.assertEqual(lead.x_vicidial_retry_count, 3)
