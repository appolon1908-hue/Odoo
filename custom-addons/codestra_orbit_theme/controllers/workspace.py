from odoo import http
from odoo.http import request


class CodestraWorkspaceEntry(http.Controller):
    """Optional website homepage target; existing Odoo access rules still apply."""

    @http.route(
        "/codestra/workspace", type="http", auth="public",
        methods=["GET"], website=True, sitemap=False,
    )
    def workspace(self, **_params):
        user = request.env.user
        if user._is_public():
            destination = "/web/login?redirect=%2Fodoo"
        elif user._is_internal():
            destination = "/odoo"
        else:
            destination = "/my"
        return request.redirect(destination, code=303)
