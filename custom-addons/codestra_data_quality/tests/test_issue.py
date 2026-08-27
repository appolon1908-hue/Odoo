from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCodestraDataQualityIssue(TransactionCase):
    def test_duplicate_review_requires_candidate_and_resolution(self):
        with self.assertRaises(ValidationError):
            self.env["codestra.data.quality.issue"].create(
                {
                    "res_model": "res.partner",
                    "res_id": 10,
                    "issue_type": "duplicate",
                }
            )
        issue = self.env["codestra.data.quality.issue"].create(
            {
                "res_model": "res.partner",
                "res_id": 10,
                "duplicate_res_id": 11,
                "issue_type": "duplicate",
            }
        )
        issue.action_start_review()
        with self.assertRaises(ValidationError):
            issue.action_resolve()
        issue.resolution = "Records reviewed; retain both until manager merge approval."
        issue.action_resolve()
        self.assertEqual(issue.state, "resolved")
