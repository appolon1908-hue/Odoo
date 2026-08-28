from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCampaignFoundation(TransactionCase):
    def setUp(self):
        super().setUp()
        self.unit = self.env.ref("call_center_core.business_unit_transport")
        self.department = self.env["call.center.department"].search(
            [("business_unit_id", "=", self.unit.id)], limit=1
        )
        if not self.department:
            self.department = self.env["call.center.department"].create(
                {
                    "name": "Foundation Department",
                    "code": "FOUNDATION-DEPT",
                    "business_unit_id": self.unit.id,
                }
            )
        self.team = self.env["call.center.team"].create(
            {
                "name": "Foundation Team",
                "code": "FOUNDATION-TEAM",
                "business_unit_id": self.unit.id,
                "department_id": self.department.id,
            }
        )
        self.campaign = self.env["call.center.campaign"].create(
            {
                "name": "Foundation Campaign",
                "code": "FOUNDATION-CAMPAIGN",
                "business_unit_id": self.unit.id,
            }
        )

    def test_queue_is_inactive_and_live_state_is_external(self):
        queue = self.env["call.center.queue"].create(
            {
                "name": "Foundation Queue",
                "code": "FOUNDATION-QUEUE",
                "company_id": self.unit.company_id.id,
                "business_unit_id": self.unit.id,
                "campaign_id": self.campaign.id,
                "team_id": self.team.id,
                "vicidial_queue_reference": "TEST_INBOUND",
            }
        )
        self.assertFalse(queue.active)
        self.assertEqual(queue.reconciliation_state, "not_observed")
        self.assertEqual(queue.live_membership_authority, "VICIdial/Asterisk")

    def test_queue_cross_business_unit_is_denied(self):
        other = self.env.ref("call_center_core.business_unit_digital")
        other_campaign = self.env["call.center.campaign"].create(
            {
                "name": "Other Campaign",
                "code": "FOUNDATION-OTHER",
                "business_unit_id": other.id,
            }
        )
        with self.assertRaises(ValidationError):
            self.env["call.center.queue"].create(
                {
                    "name": "Invalid Queue",
                    "code": "INVALID-QUEUE",
                    "company_id": self.unit.company_id.id,
                    "business_unit_id": self.unit.id,
                    "campaign_id": other_campaign.id,
                    "team_id": self.team.id,
                }
            )

    def test_queue_limits_and_self_overflow_are_denied(self):
        with self.assertRaises(Exception):
            self.env["call.center.queue"].create(
                {
                    "name": "Bad Capacity",
                    "code": "BAD-CAPACITY",
                    "company_id": self.unit.company_id.id,
                    "business_unit_id": self.unit.id,
                    "campaign_id": self.campaign.id,
                    "team_id": self.team.id,
                    "maximum_capacity": 0,
                }
            )
        queue = self.env["call.center.queue"].create(
            {
                "name": "No Loop",
                "code": "NO-LOOP",
                "company_id": self.unit.company_id.id,
                "business_unit_id": self.unit.id,
                "campaign_id": self.campaign.id,
                "team_id": self.team.id,
            }
        )
        with self.assertRaises(ValidationError):
            queue.overflow_queue_id = queue

    def test_queue_change_creates_immutable_audit(self):
        queue = self.env["call.center.queue"].create(
            {
                "name": "Audited",
                "code": "AUDITED-QUEUE",
                "company_id": self.unit.company_id.id,
                "business_unit_id": self.unit.id,
                "campaign_id": self.campaign.id,
                "team_id": self.team.id,
            }
        )
        queue.fallback_destination = "logical-only"
        event = self.env["call.center.audit.event"].search(
            [("event_type", "=", "queue.changed"), ("record_id", "=", queue.id)],
            limit=1,
        )
        self.assertTrue(event)
        with self.assertRaises(Exception):
            event.unlink()

    def test_branch_scopes_team_and_campaign(self):
        branch = self.env["call.center.branch"].create(
            {
                "name": "Scoped Branch",
                "code": "FOUNDATION-BRANCH",
                "country_id": self.env.ref("base.us").id,
                "business_unit_ids": [(6, 0, self.unit.ids)],
            }
        )
        self.team.branch_id = branch
        self.campaign.branch_id = branch
        self.assertEqual(self.team.branch_id, self.campaign.branch_id)
        other = self.env.ref("call_center_core.business_unit_digital")
        invalid_branch = self.env["call.center.branch"].create(
            {
                "name": "Other Branch",
                "code": "FOUNDATION-OTHER-BRANCH",
                "country_id": self.env.ref("base.us").id,
                "business_unit_ids": [(6, 0, other.ids)],
            }
        )
        with self.assertRaises(ValidationError):
            self.campaign.branch_id = invalid_branch

    def test_all_codestra_lifecycle_stages_have_canonical_mapping(self):
        stage_ids = [
            "stage_validating",
            "stage_ready_ai",
            "stage_ai_progress",
            "stage_ai_qualified",
            "stage_human_required",
            "stage_callback",
            "stage_closer",
            "stage_fulfillment",
            "stage_retention",
            "stage_upsell",
            "stage_do_not_contact",
        ]
        stages = self.env["crm.stage"].browse(
            [self.env.ref(f"call_center_campaign.{xmlid}").id for xmlid in stage_ids]
        )
        self.assertTrue(all(stages.mapped("canonical_journey_status_id")))

    def test_disposition_mapping_and_constraints(self):
        stage = self.env.ref("call_center_campaign.stage_callback")
        disposition = self.env["codestra.disposition"].create(
            {
                "code": "CALLBACK",
                "name": "Callback",
                "category": "progress",
                "business_unit_id": self.unit.id,
                "campaign_id": self.campaign.id,
                "vicidial_status_code": "CBHOLD",
                "canonical_status_id": self.env.ref(
                    "call_center_core.status_disposition_contact"
                ).id,
                "callback_required": True,
                "maximum_retries": 2,
                "stage_change_policy": "required",
                "allowed_next_stage_ids": [(6, 0, stage.ids)],
            }
        )
        self.assertTrue(disposition.callback_required)
        with self.assertRaises(Exception):
            disposition.copy()

    def test_callback_disposition_requires_retry(self):
        with self.assertRaises(ValidationError):
            self.env["codestra.disposition"].create(
                {
                    "code": "BAD-CB",
                    "name": "Bad Callback",
                    "category": "progress",
                    "business_unit_id": self.unit.id,
                    "campaign_id": self.campaign.id,
                    "vicidial_status_code": "BADCB",
                    "canonical_status_id": self.env.ref(
                        "call_center_core.status_disposition_contact"
                    ).id,
                    "callback_required": True,
                    "maximum_retries": 0,
                }
            )

    def test_campaign_and_queue_skill_requirements(self):
        category = self.env["call.center.skill.category"].create(
            {"name": "Product", "code": "FOUNDATION-PRODUCT"}
        )
        skill = self.env["call.center.skill"].create(
            {
                "name": "Widget",
                "code": "FOUNDATION-WIDGET",
                "category_id": category.id,
            }
        )
        requirement = self.env["call.center.skill.requirement"].create(
            {
                "campaign_id": self.campaign.id,
                "skill_id": skill.id,
                "minimum_proficiency": 2,
                "preferred_proficiency": 4,
            }
        )
        self.assertEqual(requirement.audit_business_unit_id, self.unit)
        with self.assertRaises(Exception):
            self.env["call.center.skill.requirement"].create(
                {
                    "campaign_id": self.campaign.id,
                    "skill_id": skill.id,
                    "minimum_proficiency": 5,
                    "preferred_proficiency": 4,
                }
            )

    def test_country_policy_and_phone_format_scope(self):
        us = self.env.ref("base.us")
        canada = self.env.ref("base.ca")
        policy = self.env["call.center.calling.hours.policy"].create(
            {"name": "US Hours", "code": "FOUNDATION-US-HOURS", "timezone": "UTC"}
        )
        phone_format = self.env["call.center.phone.format"].create(
            {
                "name": "US",
                "country_id": us.id,
                "country_calling_code": "1",
                "national_lengths": "10",
            }
        )
        country_policy = self.env["call.center.campaign.country.policy"].create(
            {
                "campaign_id": self.campaign.id,
                "country_id": us.id,
                "policy": "allowed",
                "calling_hours_policy_id": policy.id,
                "phone_format_id": phone_format.id,
            }
        )
        self.assertEqual(country_policy.audit_business_unit_id, self.unit)
        with self.assertRaises(ValidationError):
            country_policy.country_id = canada

    def test_campaign_country_policy_is_unique(self):
        us = self.env.ref("base.us")
        policy = self.env["call.center.calling.hours.policy"].create(
            {"name": "Unique Hours", "code": "FOUNDATION-UNIQUE-HOURS", "timezone": "UTC"}
        )
        phone_format = self.env["call.center.phone.format"].create(
            {
                "name": "Unique US",
                "country_id": us.id,
                "country_calling_code": "1",
                "national_lengths": "10",
            }
        )
        values = {
            "campaign_id": self.campaign.id,
            "country_id": us.id,
            "calling_hours_policy_id": policy.id,
            "phone_format_id": phone_format.id,
        }
        self.env["call.center.campaign.country.policy"].create(values)
        with self.assertRaises(Exception):
            self.env["call.center.campaign.country.policy"].create(values)
