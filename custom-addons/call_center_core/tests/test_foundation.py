from datetime import datetime
from zoneinfo import ZoneInfo

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFoundationCore(TransactionCase):
    def setUp(self):
        super().setUp()
        self.unit = self.env.ref("call_center_core.business_unit_transport")
        self.country = self.env.ref("base.us")

    def test_branch_company_and_business_unit_scope(self):
        branch = self.env["call.center.branch"].create(
            {
                "name": "Test Office",
                "code": "TEST-OFFICE",
                "company_id": self.unit.company_id.id,
                "country_id": self.country.id,
                "business_unit_ids": [(6, 0, self.unit.ids)],
            }
        )
        self.assertIn(self.unit, branch.business_unit_ids)
        other_company = self.env["res.company"].create({"name": "Other"})
        other_unit = self.env["call.center.business.unit"].create(
            {"name": "Other Unit", "code": "OTHER-UNIT", "company_id": other_company.id}
        )
        with self.assertRaises(ValidationError):
            branch.business_unit_ids = [(4, other_unit.id)]

    def test_branch_code_is_unique_per_company(self):
        values = {
            "name": "One",
            "code": "DUP-BRANCH",
            "country_id": self.country.id,
        }
        self.env["call.center.branch"].create(values)
        with self.assertRaises(Exception):
            self.env["call.center.branch"].create({**values, "name": "Two"})

    def test_canonical_layers_are_seeded(self):
        layers = set(self.env["call.center.canonical.status"].search([]).mapped("layer"))
        self.assertEqual(
            layers,
            {"journey", "disposition", "callback", "appointment", "agent", "consent"},
        )

    def test_transition_policy_and_immutable_audit(self):
        previous = self.env.ref("call_center_core.status_journey_new")
        new = self.env.ref("call_center_core.status_journey_validation")
        audit = self.env["call.center.status.transition.audit"].create(
            {
                "model_name": "crm.lead",
                "record_id": 999,
                "previous_status_id": previous.id,
                "new_status_id": new.id,
                "audit_business_unit_id": self.unit.id,
            }
        )
        with self.assertRaises(AccessError):
            audit.write({"audit_reason": "tamper"})
        with self.assertRaises(AccessError):
            audit.unlink()

    def test_unapproved_and_cross_layer_transitions_fail(self):
        journey = self.env.ref("call_center_core.status_journey_new")
        agent = self.env.ref("call_center_core.status_agent_available")
        with self.assertRaises(ValidationError):
            self.env["call.center.status.transition"].create(
                {"from_status_id": journey.id, "to_status_id": agent.id}
            )
        terminal = self.env.ref("call_center_core.status_journey_converted")
        with self.assertRaises(ValidationError):
            self.env["call.center.status.transition.audit"].create(
                {
                    "model_name": "crm.lead",
                    "record_id": 999,
                    "previous_status_id": journey.id,
                    "new_status_id": terminal.id,
                }
            )

    def test_calling_hours_multiple_periods_timezone_and_holiday(self):
        policy = self.env["call.center.calling.hours.policy"].create(
            {
                "name": "Eastern Split Day",
                "code": "TEST-EASTERN",
                "timezone": "America/New_York",
                "period_ids": [
                    (0, 0, {"weekday": "0", "hour_from": 8, "hour_to": 12}),
                    (0, 0, {"weekday": "0", "hour_from": 13, "hour_to": 17}),
                ],
            }
        )
        monday = datetime(2026, 7, 27, 14, 0, tzinfo=ZoneInfo("UTC"))
        self.assertTrue(policy.evaluate(moment=monday)["allowed"])
        lunch = datetime(2026, 7, 27, 16, 30, tzinfo=ZoneInfo("UTC"))
        self.assertFalse(policy.evaluate(moment=lunch)["allowed"])
        policy.exception_ids = [
            (
                0,
                0,
                {
                    "name": "Closure",
                    "date_from": "2026-07-27",
                    "date_to": "2026-07-27",
                    "exception_type": "holiday",
                    "reason": "Synthetic holiday",
                },
            )
        ]
        self.assertEqual(policy.evaluate(moment=monday)["reason"], "holiday")

    def test_overnight_period(self):
        policy = self.env["call.center.calling.hours.policy"].create(
            {
                "name": "Night",
                "code": "TEST-NIGHT",
                "timezone": "UTC",
                "period_ids": [
                    (
                        0,
                        0,
                        {
                            "weekday": "0",
                            "hour_from": 22,
                            "hour_to": 4,
                            "overnight": True,
                        },
                    )
                ],
            }
        )
        monday_night = datetime(2026, 7, 27, 23, 0, tzinfo=ZoneInfo("UTC"))
        self.assertTrue(policy.evaluate(moment=monday_night)["allowed"])
        tuesday_early = datetime(2026, 7, 28, 2, 0, tzinfo=ZoneInfo("UTC"))
        self.assertTrue(policy.evaluate(moment=tuesday_early)["allowed"])

    def test_calling_decision_is_immutable(self):
        policy = self.env["call.center.calling.hours.policy"].create(
            {"name": "Closed", "code": "TEST-CLOSED", "timezone": "UTC"}
        )
        result = policy.evaluate(
            moment=datetime(2026, 7, 27, 12, 0, tzinfo=ZoneInfo("UTC"))
        )
        audit = self.env["call.center.calling.hours.decision"].browse(result["audit_id"])
        with self.assertRaises(AccessError):
            audit.unlink()

    def test_phone_normalization_is_format_only(self):
        phone_format = self.env["call.center.phone.format"].create(
            {
                "name": "US Test",
                "country_id": self.country.id,
                "country_calling_code": "1",
                "national_lengths": "10",
                "permitted_prefixes": "2,3,4,5,6,7,8,9",
                "mobile_prefixes": "917",
            }
        )
        result = phone_format.normalize("(917) 555-0100")
        self.assertTrue(result["valid"])
        self.assertEqual(result["e164"], "+19175550100")
        self.assertEqual(result["number_type"], "mobile")
        self.assertEqual(
            phone_format.normalize("123")["reason"], "invalid_national_length"
        )

    def test_managed_skill_constraints(self):
        category = self.env["call.center.skill.category"].create(
            {"name": "Language", "code": "TEST-LANG"}
        )
        skill = self.env["call.center.skill"].create(
            {
                "name": "English",
                "code": "TEST-EN",
                "category_id": category.id,
                "skill_type": "language",
            }
        )
        assignment = self.env["call.center.agent.skill"].create(
            {
                "user_id": self.env.user.id,
                "skill_id": skill.id,
                "proficiency": 4,
                "language_level": "c1",
            }
        )
        self.assertEqual(assignment.proficiency, 4)
        with self.assertRaises(Exception):
            self.env["call.center.agent.skill"].create(
                {"user_id": self.env.user.id, "skill_id": skill.id}
            )
        with self.assertRaises(ValidationError):
            assignment.write({"certified": True})

    def test_existing_audit_event_remains_immutable(self):
        event = self.env["call.center.audit.event"].create(
            {
                "event_type": "foundation.test",
                "model_name": "call.center.branch",
                "record_id": 1,
                "business_unit_id": self.unit.id,
                "source_system": "odoo-test",
            }
        )
        with self.assertRaises(AccessError):
            event.write({"reason": "tamper"})
