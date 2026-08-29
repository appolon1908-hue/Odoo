import werkzeug.exceptions
import werkzeug.utils

from odoo import http
from odoo.http import request


class ContactCenterLandingController(http.Controller):
    @http.route(
        "/contact-center/agent",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
        sitemap=False,
    )
    def agent_landing(self, **_params):
        membership = request.env.user._cc_resolve_operational_membership()
        if membership.role not in {"agent", "senior_agent"}:
            raise werkzeug.exceptions.Forbidden()
        return werkzeug.utils.redirect("/odoo", 303)

    @http.route(
        "/contact-center/supervisor",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
        sitemap=False,
    )
    def supervisor_landing(self, **_params):
        membership = request.env.user._cc_resolve_operational_membership()
        if membership.role != "supervisor":
            raise werkzeug.exceptions.Forbidden()
        return werkzeug.utils.redirect("/odoo", 303)
