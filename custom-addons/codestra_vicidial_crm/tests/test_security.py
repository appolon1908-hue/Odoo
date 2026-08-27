from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


class TestSecurity(TransactionCase):
    def test_non_superuser_cannot_delete_audit(self):
        manager = new_test_user(
            self.env,
            login="codestra_manager_test",
            groups="codestra_vicidial_crm.group_manager",
            context={"no_reset_password": True},
        )
        audit = (
            self.env["codestra.integration.audit"]
            .sudo()
            .create(
                {
                    "action": "test",
                    "success": True,
                }
            )
        )
        with self.assertRaises(AccessError):
            audit.with_user(manager).unlink()
