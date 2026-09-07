from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request


class ProvisioningMonitoringController(http.Controller):
    @http.route(
        "/codestra/provisioning/v1/monitoring/agents",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def monitoring_agents(self, campaign=None, limit=200):
        """Expose a secret-free, record-rule-scoped agent status projection."""
        try:
            result = request.env["codestra.provisioning.request"].monitoring_snapshot(
                campaign_code=campaign,
                limit=limit,
            )
        except (AccessError, ValueError, TypeError):
            return request.make_json_response({"error": "access_denied"}, status=403)
        return request.make_json_response(result, status=200)
