from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


class TestPermissions(TransactionCase):
    def _create_agent_users(self, suffix):
        context = {"no_reset_password": True}
        agent_user = new_test_user(
            self.env,
            login=f"codestra_agent_{suffix}",
            groups="codestra_vicidial_crm.group_agent",
            context=context,
        )
        other_user = new_test_user(
            self.env,
            login=f"codestra_other_{suffix}",
            groups="codestra_vicidial_crm.group_agent",
            context=context,
        )
        agent = self.env["codestra.vicidial.agent"].create(
            {
                "name": f"Agent {suffix}",
                "odoo_user_id": agent_user.id,
            }
        )
        other = self.env["codestra.vicidial.agent"].create(
            {
                "name": f"Other {suffix}",
                "odoo_user_id": other_user.id,
            }
        )
        return agent_user, other_user, agent, other

    def test_agent_cannot_see_another_agents_call(self):
        agent_user, _other_user, agent, other = self._create_agent_users("calls")
        own_call = self.env["codestra.vicidial.call"].create(
            {
                "name": "Own",
                "agent_id": agent.id,
                "duration_seconds": 0,
                "billable_seconds": 0,
            }
        )
        self.env["codestra.vicidial.call"].create(
            {
                "name": "Other",
                "agent_id": other.id,
                "duration_seconds": 0,
                "billable_seconds": 0,
            }
        )
        visible = self.env["codestra.vicidial.call"].with_user(agent_user).search([])
        self.assertEqual(visible, own_call)

    def test_agent_profile_is_read_only_and_scoped(self):
        agent_user, _other_user, agent, other = self._create_agent_users("profile")
        agent_model = self.env["codestra.vicidial.agent"].with_user(agent_user)

        self.assertEqual(agent_model.search([]), agent)

        with self.assertRaises(AccessError):
            agent.with_user(agent_user).write({"status": "ready"})

        with self.assertRaises(AccessError):
            other.with_user(agent_user).write({"odoo_user_id": agent_user.id})
