from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCodestraContactCenterShift(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["hr.employee"].create({"name": "Schedule Agent"})
        cls.start = fields.Datetime.now()
        cls.end = fields.Datetime.add(cls.start, hours=8)

    def test_shift_metrics_from_verified_attendance(self):
        attendance = self.env["hr.attendance"].create(
            {
                "employee_id": self.employee.id,
                "check_in": self.start,
                "check_out": fields.Datetime.add(self.start, hours=7, minutes=30),
            }
        )
        shift = self.env["codestra.cc.shift"].create(
            {
                "employee_id": self.employee.id,
                "start_at": self.start,
                "end_at": self.end,
                "break_minutes": 30,
                "attendance_id": attendance.id,
            }
        )
        self.assertTrue(shift.name.startswith("SHIFT-"))
        self.assertAlmostEqual(shift.planned_hours, 7.5, places=2)
        self.assertAlmostEqual(shift.actual_hours, 7.5, places=2)
        self.assertAlmostEqual(shift.adherence_percent, 100.0, places=2)
        shift.action_publish()
        shift.action_complete()
        self.assertEqual(shift.state, "completed")

    def test_invalid_interval_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["codestra.cc.shift"].create(
                {
                    "employee_id": self.employee.id,
                    "start_at": self.end,
                    "end_at": self.start,
                }
            )
