from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCodestraTrainingAcademy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "Training Agent"})
        cls.course = cls.env["codestra.training.course"].create(
            {"name": "Compliance Basics", "code": "COMP-101", "passing_score": 80}
        )

    def test_training_evaluation_and_expiration(self):
        enrollment = self.env["codestra.training.enrollment"].create(
            {"course_id": self.course.id, "employee_id": self.employee.id, "score": 90}
        )
        enrollment.action_start()
        enrollment.action_evaluate()
        self.assertEqual(enrollment.state, "passed")
        self.assertEqual(enrollment.attempts, 1)
        self.assertTrue(enrollment.completed_at)
        self.assertTrue(enrollment.expires_at)
