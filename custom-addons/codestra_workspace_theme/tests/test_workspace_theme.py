from lxml import html

from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraWorkspaceAssets(HttpCase):
    def _stylesheets(self, response):
        response.raise_for_status()
        document = html.fromstring(response.content)
        hrefs = document.xpath("//link[@rel='stylesheet']/@href")
        self.assertTrue(hrefs, "Odoo did not declare its stylesheet bundles")
        styles = []
        for href in hrefs:
            asset = self.url_open(href)
            asset.raise_for_status()
            self.assertIn("text/css", asset.headers.get("Content-Type", ""))
            self.assertNotIn("style compilation failed", asset.text.lower())
            styles.append(asset.text)
        return "\n".join(styles)

    def test_authenticated_workspace_loads_night_assets(self):
        # This account belongs to the disposable Odoo test database only.
        self.authenticate("admin", "admin")
        response = self.url_open("/odoo")
        self.assertIn("o_web_client", response.text)
        css = self._stylesheets(response)
        self.assertIn("--cs-night-canvas", css)
        self.assertIn("body.o_web_client .o_main_navbar", css)
        self.assertIn(".o-mail-ChatWindow", css)

    def test_public_login_does_not_load_workspace_assets(self):
        self.authenticate(None, None)
        response = self.url_open("/web/login")
        document = html.fromstring(response.content)
        self.assertTrue(document.xpath("//input[@name='csrf_token']"))
        self.assertTrue(document.xpath("//input[@name='password']"))
        self.assertNotIn("--cs-night-canvas", self._stylesheets(response))
