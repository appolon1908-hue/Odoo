from lxml import etree

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

        layout_arch = etree.fromstring(layout.arch_db.encode())
        xpath_expressions = layout_arch.xpath("//xpath/@expr")
        self.assertIn("t[@t-call]", xpath_expressions)
        self.assertNotIn("//t[@t-set='body_classname']", xpath_expressions)


@tagged("post_install", "-at_install")
class TestCodestraLoginWebsiteCompatibility(TransactionCase):
    def test_website_layout_cannot_remove_codestra_authentication_shell(self):
        website_layout = self.env.ref(
            "website.login_layout",
            raise_if_not_found=False,
        )
        if not website_layout:
            self.skipTest("The optional website module is not installed")

        combined_arch = self.env.ref("web.login_layout").get_combined_arch()
        self.assertIn("codestra-login-shell", combined_arch)
        self.assertIn("codestra-auth-body", combined_arch)
        self.assertNotIn("oe_website_login_container", combined_arch)


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
