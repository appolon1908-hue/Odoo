from odoo.tests.common import TransactionCase, new_test_user


class TestPermissions(TransactionCase):
    def test_agent_cannot_see_another_agents_call(self):
        context = {"no_reset_password": True}
        agent_user = new_test_user(
            self.env,
            login="codestra_agent_test",
            groups="codestra_vicidial_crm.group_agent",
            context=context,
        )
        other_user = new_test_user(
            self.env,
            login="codestra_other_test",
            groups="codestra_vicidial_crm.group_agent",
            context=context,
        )
        agent = self.env["codestra.vicidial.agent"].create(
            {
                "name": "Agent",
                "odoo_user_id": agent_user.id,
            }
        )
        other = self.env["codestra.vicidial.agent"].create(
            {
                "name": "Other",
                "odoo_user_id": other_user.id,
            }
        )
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
