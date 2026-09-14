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
        audit = self.env["codestra.integration.audit"]._append(
            False,
            "test",
            "success",
            {
                "model_name": "res.users",
                "record_res_id": manager.id,
                "after": {},
            },
            actor_role="system",
            correlation_id="audit-security-delete-test",
            subject_model="res.users",
            subject_id=manager.id,
        )
        with self.assertRaises(AccessError):
            audit.with_user(manager).unlink()
