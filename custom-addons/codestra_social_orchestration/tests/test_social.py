from odoo.tests.common import TransactionCase


class TestSocialOrchestration(TransactionCase):
    def test_models_and_integration_role_are_present(self):
        self.assertTrue(self.env.ref("codestra_social_orchestration.group_social_integration_service"))
        self.assertEqual(self.env["codestra.social.post"]._name, "codestra.social.post")
        self.assertEqual(self.env["codestra.social.publication"]._name, "codestra.social.publication")

    def test_service_role_has_no_delete_access(self):
        group = self.env.ref("codestra_social_orchestration.group_social_integration_service")
        group_id = group.id
        for model_name in ("codestra.social.campaign", "codestra.social.post", "codestra.social.publication", "codestra.social.failure"):
            model_id = self.env[model_name]._name
            rows = self.env["ir.model.access"].search([
                ("group_id", "=", group_id), ("model_id.model", "=", model_id)
            ])
            self.assertTrue(rows)
            self.assertFalse(any(rows.mapped("perm_unlink")))
        self.assertNotIn(self.env.ref("base.group_system"), group.implied_ids)
