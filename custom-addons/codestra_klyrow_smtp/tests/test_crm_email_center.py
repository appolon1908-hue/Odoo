from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCrmEmailCenter(TransactionCase):
    def test_crm_menu_and_action_reuse_campaign_mail_threads(self):
        action = self.env.ref("codestra_klyrow_smtp.action_crm_email_center")
        menu = self.env.ref("codestra_klyrow_smtp.menu_crm_email_center")
        self.assertEqual(action.res_model, "cc.mail.thread")
        self.assertEqual(menu.action, action)
        self.assertEqual(menu.parent_id, self.env.ref("crm.crm_menu_root"))

    def test_snapshot_is_fail_closed_and_does_not_enable_compose(self):
        snapshot = self.env["cc.mail.thread"].crm_email_center_snapshot(limit=200)
        self.assertLessEqual(len(snapshot["items"]), 20)
        self.assertFalse(snapshot["delivery_ready"])
        self.assertFalse(snapshot["compose_enabled"])
        self.assertEqual(
            {profile["name"] for profile in snapshot["profiles"]},
            {"Klyrow Production", "Beyvra Production"},
        )
        self.assertTrue(all(not profile["ready"] for profile in snapshot["profiles"]))

    def test_unscoped_internal_user_cannot_load_email_center(self):
        internal = self.env.ref("base.group_user")
        user = self.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "CRM Email Center Unscoped",
                "login": "crm-email-center-unscoped@example.invalid",
                "group_ids": [(6, 0, internal.ids)],
            }
        )
        with self.assertRaises(AccessError):
            self.env["cc.mail.thread"].with_user(user).crm_email_center_snapshot()
