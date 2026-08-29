from odoo.tests.common import TransactionCase


class TestGroupHierarchy(TransactionCase):
    def test_roles(self):
        ref = self.env.ref
        agent = ref("codestra_base.group_codestra_agent")
        closer = ref("codestra_base.group_codestra_closer")
        supervisor = ref("codestra_base.group_codestra_supervisor")
        manager = ref("codestra_base.group_codestra_manager")
        self.assertIn(agent, closer.implied_ids)
        self.assertIn(agent, supervisor.implied_ids)
        self.assertIn(supervisor, manager.implied_ids)
        self.assertIn(closer, manager.implied_ids)
        self.assertNotIn(agent, ref("codestra_base.group_codestra_qa_reviewer").implied_ids)

    def test_privileged_roles_are_separate(self):
        integration_admin = self.env.ref("codestra_base.group_codestra_integration_admin")
        compliance_officer = self.env.ref("codestra_base.group_codestra_compliance_officer")
        manager = self.env.ref("codestra_base.group_codestra_manager")

        self.assertNotEqual(integration_admin, compliance_officer)
        self.assertNotIn(compliance_officer, integration_admin.implied_ids)
        self.assertNotIn(integration_admin, compliance_officer.implied_ids)
        self.assertNotIn(integration_admin, manager.implied_ids)
        self.assertNotIn(compliance_officer, manager.implied_ids)
