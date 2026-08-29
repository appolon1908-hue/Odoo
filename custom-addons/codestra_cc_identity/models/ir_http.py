from odoo import http, models
from odoo.exceptions import AccessDenied
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _authenticate(cls, endpoint):
        super()._authenticate(endpoint)
        if not request.env.uid or not request.env.user._cc_requires_session_scope():
            return
        session_identifier = request.session.sid
        if not session_identifier:
            request.session.logout(keep_db=True)
            raise http.SessionExpiredException("Contact-center session is unavailable")
        try:
            request.env["cc.identity.session.scope"]._assert_or_pin_authenticated_session(
                session_identifier
            )
        except AccessDenied as error:
            request.session.logout(keep_db=True)
            raise http.SessionExpiredException(str(error)) from error
