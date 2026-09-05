from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAgentOnboardingVicidialBinding(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.unit = cls.env["call.center.business.unit"].create(
            {
                "name": "Binding Test Unit",
                "code": "BND",
                "company_id": cls.company.id,
            }
        )
        # Legacy creation already adopts one canonical wrapper.
        cls.canonical_unit = cls.env["cc.business.unit"].with_context(
            active_test=False
        ).search([("legacy_business_unit_id", "=", cls.unit.id)])
        cls.canonical_unit.ensure_one()
        cls.supervisor = cls.env["res.users"].create(
            {
                "name": "Binding Supervisor",
                "login": "binding.supervisor@example.invalid",
                "company_id": cls.company.id,
                "company_ids": [(6, 0, cls.company.ids)],
            }
        )
        cls.department = cls.env["call.center.department"].create(
            {
                "name": "Binding Operations",
                "code": "BND-OPS",
                "business_unit_id": cls.unit.id,
            }
        )
        cls.team = cls.env["call.center.team"].create(
            {
                "name": "Binding Team",
                "code": "BND-T1",
                "business_unit_id": cls.unit.id,
                "department_id": cls.department.id,
                "supervisor_ids": [(6, 0, cls.supervisor.ids)],
            }
        )
        cls.legacy_campaign = cls.env["call.center.campaign"].create(
            {
                "name": "Binding Campaign",
                "code": "BND-OUT",
                "business_unit_id": cls.unit.id,
                "state": "approved",
                "design_automation_enabled": False,
                "active": False,
                "direction": "outbound",
                "team_ids": [(6, 0, cls.team.ids)],
                "supervisor_ids": [(6, 0, cls.supervisor.ids)],
                "start_date": fields.Date.today(),
                "timezone": "UTC",
                "telephony_enabled": True,
                "vicidial_required": True,
                "vicidial_campaign_id": "BND0001",
                "vicidial_user_group": "BND_AGENT",
                "reconciliation_status": "synced_disabled",
            }
        )
        cls.campaign = cls.env["cc.campaign"].with_context(
            active_test=False
        ).search([("legacy_campaign_id", "=", cls.legacy_campaign.id)])
        cls.campaign.ensure_one()
        assert cls.campaign.cc_business_unit_id == cls.canonical_unit
        assert cls.campaign.lifecycle_state == "approved"
        cls.role_template = cls.env["codestra.role.template"].create(
            {
                "name": "Binding Agent",
                "code": "BND_AGENT",
                "company_id": cls.company.id,
                "business_unit_id": cls.unit.id,
                "vicidial_user_group": "BND_AGENT",
            }
        )
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Bounded Agent",
                "company_id": cls.company.id,
                "work_email": "bounded.agent@example.invalid",
            }
        )

    def _onboarding(self):
        return self.env["codestra.agent.onboarding"].create(
            {
                "employee_id": self.employee.id,
                "manager_id": self.supervisor.id,
                "target_start_date": fields.Date.today(),
                "campaign_id": self.campaign.id,
                "campaign_role": "agent",
                "department_id": self.department.id,
                "operational_team_id": self.team.id,
                "supervisor_id": self.supervisor.id,
                "role_template_id": self.role_template.id,
                "needs_vicidial": True,
                "activation_email": "bounded.agent@example.invalid",
                "identity_verified": True,
                "employment_documents_complete": True,
                "approved_checks_complete": True,
                "equipment_ready": True,
                "training_complete": True,
                "compliance_approved": True,
            }
        )

    def test_event_context_contains_native_campaign_and_display_name(self):
        onboarding = self._onboarding()
        onboarding._assert_assignment_ready()
        context = onboarding._event_context()
        self.assertEqual(context["employee_display_name"], "Bounded Agent")
        self.assertEqual(context["vicidial_campaign_id"], "BND0001")
        self.assertEqual(context["vicidial_user_group"], "BND_AGENT")
        self.assertEqual(context["vicidial_inbound_groups"], [])

    def test_unreconciled_vicidial_campaign_fails_closed(self):
        onboarding = self._onboarding()
        self.legacy_campaign.reconciliation_status = "pending"
        with self.assertRaises(ValidationError):
            onboarding._assert_assignment_ready()

    def test_role_template_group_must_match_campaign(self):
        onboarding = self._onboarding()
        self.role_template.vicidial_user_group = "OTHER_GROUP"
        # Privilege changes create a new immutable version; the original row
        # keeps its old group and is archived, rather than being overwritten.
        self.assertFalse(self.role_template.active)
        with self.assertRaises(ValidationError):
            onboarding._assert_assignment_ready()
        replacement = self.env["codestra.role.template"].search([
            ("code", "=", self.role_template.code),
            ("business_unit_id", "=", self.unit.id),
            ("version", "=", self.role_template.version + 1),
        ])
        replacement.ensure_one()
        self.assertEqual(replacement.vicidial_user_group, "OTHER_GROUP")
        onboarding.role_template_id = replacement
        with self.assertRaises(ValidationError):
            onboarding._assert_assignment_ready()
