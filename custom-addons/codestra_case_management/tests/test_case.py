from lxml import etree

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

    def test_search_view_uses_odoo_19_group_schema(self):
        view = self.env.ref(
            "codestra_case_management.view_codestra_case_search"
        )
        arch = etree.fromstring(view.get_combined_arch().encode())
        groups = arch.xpath("/search/group")

        self.assertEqual(len(groups), 1)
        self.assertFalse(groups[0].attrib)
        self.assertEqual(
            set(groups[0].xpath("filter/@name")),
            {"group_state", "group_category", "group_campaign", "group_owner"},
        )
