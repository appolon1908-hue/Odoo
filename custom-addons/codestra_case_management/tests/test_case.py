from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCodestraCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Case = cls.env["codestra.case"]

    def test_case_sequence_and_resolution_transition(self):
        case = self.Case.create({"summary": "Customer complaint"})
        self.assertTrue(case.name.startswith("CC-"))
        self.assertEqual(case.company_id, self.env.company)
        self.assertEqual(case.state, "new")

        case.action_start()
        self.assertEqual(case.state, "in_progress")
        with self.assertRaises(ValidationError):
            case.action_resolve()

        case.resolution = "Customer concern addressed."
        case.action_resolve()
        self.assertEqual(case.state, "resolved")
        case.action_close()
        self.assertEqual(case.state, "closed")
        self.assertTrue(case.closed_at)

    def test_escalation_requires_reason(self):
        case = self.Case.create({"summary": "Escalation review"})
        case.action_start()
        with self.assertRaises(ValidationError):
            case.action_escalate()
        case.escalation_reason = "Executive review required."
        case.action_escalate()
        self.assertEqual(case.state, "escalated")
