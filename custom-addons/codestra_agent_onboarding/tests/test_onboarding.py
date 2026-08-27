from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCodestraAgentOnboarding(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "Onboarding Agent"})

    def test_approval_requires_all_readiness_gates(self):
        onboarding = self.env["codestra.agent.onboarding"].create(
            {"employee_id": self.employee.id}
        )
        onboarding.action_submit()
        with self.assertRaises(ValidationError):
            onboarding.action_approve()
        onboarding.write(
            {
                "identity_verified": True,
                "employment_documents_complete": True,
                "approved_checks_complete": True,
                "equipment_ready": True,
                "training_complete": True,
                "compliance_approved": True,
            }
        )
        self.assertEqual(onboarding.completion_percent, 100.0)
        onboarding.action_approve()
        self.assertEqual(onboarding.state, "approved")
