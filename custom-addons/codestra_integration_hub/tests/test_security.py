from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestSecurity(TransactionCase):
    def _user(self, login, group_xmlid):
        return self.env["res.users"].create({"name": login, "login": login,
            "group_ids": [(6, 0, [self.env.ref(group_xmlid).id])]})

    def test_agent_and_supervisor_denied_manager_read_only(self):
        event = self.env["codestra.integration.event"].register_event("x", "odoo", "middleware", {})
        for group in ("codestra_base.group_codestra_agent", "codestra_base.group_codestra_closer", "codestra_base.group_codestra_supervisor"):
            user = self._user(group.rsplit("_", 1)[-1], group)
            with self.assertRaises(AccessError):
                event.with_user(user).check_access("read")
            for model_name in ("codestra.integration.endpoint", "codestra.integration.idempotency"):
                with self.assertRaises(AccessError):
                    self.env[model_name].with_user(user).check_access("read")
        manager = self._user("hub-manager", "codestra_base.group_codestra_manager")
        event.with_user(manager).check_access("read")
        with self.assertRaises(AccessError):
            event.with_user(manager).write({"destination": "changed"})
        for model_name in ("codestra.integration.endpoint", "codestra.integration.idempotency"):
            with self.assertRaises(AccessError):
                self.env[model_name].with_user(manager).check_access("read")

    def test_integration_admin_has_intended_endpoint_access(self):
        admin = self._user(
            "hub-integration-admin", "codestra_base.group_codestra_integration_admin"
        )
        endpoint = self.env["codestra.integration.endpoint"].with_user(admin).create({
            "name": "Admin logical endpoint",
            "code": "admin-logical-endpoint",
            "direction": "outbound",
        })
        self.assertFalse(endpoint.enabled)
        self.assertTrue(endpoint.test_only)
