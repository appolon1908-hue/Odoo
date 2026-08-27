from odoo.tests.common import HttpCase, TransactionCase, tagged


class TestCodestraLoginViews(TransactionCase):
    def test_login_views_inherit_odoo_web_templates(self):
        layout = self.env.ref(
            "codestra_login_branding.codestra_login_layout"
        )
        login_form = self.env.ref(
            "codestra_login_branding.codestra_login_form"
        )

        self.assertEqual(layout.inherit_id, self.env.ref("web.login_layout"))
        self.assertEqual(login_form.inherit_id, self.env.ref("web.login"))
        self.assertIn("codestra-login-shell", str(layout.arch_db))
        self.assertIn("Continue securely", str(login_form.arch_db))


@tagged("post_install", "-at_install")
class TestCodestraLoginHttp(HttpCase):
    def test_login_page_renders_codestra_branding(self):
        response = self.url_open("/web/login")
        response.raise_for_status()

        self.assertIn("Codestra CRM", response.text)
        self.assertIn("Continue securely", response.text)
        self.assertIn("codestra-login-shell", response.text)
        self.assertNotIn("Powered by <span>Odoo</span>", response.text)
        self.assertNotIn("/web/database/manager", response.text)
