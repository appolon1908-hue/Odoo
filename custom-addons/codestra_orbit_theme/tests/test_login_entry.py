from lxml import html

from odoo.tests.common import HttpCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestCodestraLoginEntry(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = new_test_user(
            cls.env, login="workspace_portal_fixture", groups="base.group_portal"
        )
        cls.website = cls.env.ref("website.default_website")

    def test_branding_dependency_renders_one_login_heading(self):
        response = self.url_open("/web/login")
        response.raise_for_status()
        page = html.fromstring(response.content)
        self.assertEqual(len(page.xpath("//div[@class='codestra-login-shell']")), 1)
        self.assertEqual(len(page.xpath("//div[contains(@class, 'codestra-login-card')]//*[self::h1 or self::h2]")), 1)
        self.assertEqual(len(page.xpath("//form[contains(@class, 'oe_login_form')]//input[@name='csrf_token']")), 1)
        self.assertFalse(page.xpath("//header[@id='top'] | //footer[@id='bottom']"))
        self.assertNotIn("Your Logo", response.text)
        self.assertNotIn("info@yourcompany.example.com", response.text)

    def test_codestra_sso_has_one_code_flow_button_and_keeps_local_login(self):
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param("codestra_orbit_theme.keycloak_issuer", "https://id.example/realms/codestra")
        parameters.set_param("codestra_orbit_theme.keycloak_client_id", "odoo-web")
        self.env.ref("codestra_orbit_theme.provider_codestra_keycloak").enabled = True
        response = self.url_open("/web/login?redirect=/odoo")
        response.raise_for_status()
        page = html.fromstring(response.content)
        buttons = page.xpath("//a[contains(@class, 'cs-orbit-sso')]")
        self.assertEqual(len(buttons), 1)
        self.assertTrue(buttons[0].get("href").startswith("/codestra/sso/login?"))
        self.assertFalse(page.xpath("//a[contains(@class, 'o_auth_oauth_login')]"))
        self.assertEqual(len(page.xpath("//form[contains(@class, 'oe_login_form')]//input[@name='password']")), 1)

    def test_public_workspace_entry_uses_branded_login(self):
        response = self.url_open("/codestra/workspace", allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "/web/login?redirect=%2Fodoo")

    def test_configured_website_homepage_enters_workspace(self):
        self.website.homepage_url = "/codestra/workspace"
        response = self.url_open("/", allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "/web/login?redirect=%2Fodoo")

    def test_unconfigured_website_homepage_is_preserved(self):
        self.website.homepage_url = False
        response = self.url_open("/", allow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Location", response.headers)

    def test_internal_user_enters_odoo(self):
        self.authenticate("admin", "admin")
        response = self.url_open("/codestra/workspace", allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "/odoo")

    def test_portal_user_enters_portal(self):
        self.authenticate(self.portal_user.login, self.portal_user.login)
        response = self.url_open("/codestra/workspace", allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "/my")
