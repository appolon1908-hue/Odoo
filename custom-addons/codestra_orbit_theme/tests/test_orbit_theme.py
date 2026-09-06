from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from odoo.tests.common import HttpCase, TransactionCase, tagged


class TestOrbitSecurity(TransactionCase):
    def test_addon_creates_no_business_models_or_acl_bypass(self):
        module = self.env["ir.module.module"].search([("name", "=", "codestra_orbit_theme")])
        authorization_data = self.env["ir.model.data"].search([
            ("module", "=", "codestra_orbit_theme"),
            ("model", "in", ["ir.model.access", "ir.rule"]),
        ])
        self.assertTrue(module)
        self.assertFalse(authorization_data, "theme/SSO addon must not create ACL or record-rule bypasses")
        self.assertFalse(
            self.env["ir.model"].search([("model", "like", "codestra.orbit.%")]),
            "theme/SSO addon must not create business models",
        )

    def test_keycloak_secret_field_is_system_admin_only(self):
        field = self.env["res.config.settings"]._fields["codestra_keycloak_client_secret"]
        self.assertEqual(field.groups, "base.group_system")

    def test_templates_are_global_and_do_not_read_company_records(self):
        for xmlid in ("login", "logout_message", "website_header", "portal_layout"):
            view = self.env.ref(f"codestra_orbit_theme.{xmlid}")
            self.assertFalse(view.company_id if "company_id" in view._fields else False)
            self.assertNotIn("sudo", str(view.arch_db))


@tagged("post_install", "-at_install")
class TestOrbitHttp(HttpCase):
    def test_login_is_responsive_and_preserves_csrf(self):
        response = self.url_open("/web/login")
        response.raise_for_status()
        self.assertIn("Continue with Codestra", response.text)
        self.assertIn('name="csrf_token"', response.text)
        css = self.url_open("/codestra_orbit_theme/static/src/css/frontend.css")
        css.raise_for_status()
        self.assertIn("@media (max-width: 575.98px)", css.text)
        self.assertIn(":focus-visible", css.text)

    def test_sso_login_uses_code_flow_and_server_side_state(self):
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param("codestra_orbit_theme.keycloak_issuer", "https://id.example/realms/codestra")
        parameters.set_param("codestra_orbit_theme.keycloak_client_id", "odoo")
        parameters.set_param("codestra_orbit_theme.keycloak_client_secret", "test-only-secret")
        response = self.url_open("/codestra/sso/login", allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        query = parse_qs(urlparse(response.headers["Location"]).query)
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], ["openid profile email"])
        self.assertNotIn("token", response.headers["Location"])

    def test_callback_rejects_missing_or_unbound_state_before_token_exchange(self):
        with patch("requests.post") as token_request:
            response = self.url_open(
                "/codestra/sso/callback?code=untrusted&state=untrusted",
                allow_redirects=False,
            )
        self.assertIn(response.status_code, (400, 403))
        token_request.assert_not_called()
