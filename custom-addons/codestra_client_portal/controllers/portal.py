from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class CodestraClientPortal(CustomerPortal):
    @staticmethod
    def _client_partner():
        return request.env.user.partner_id.commercial_partner_id

    @http.route(["/my/codestra"], type="http", auth="user", website=True)
    def codestra_dashboard(self, **kwargs):
        client = self._client_partner()
        contracts = request.env["codestra.client.contract"].search(
            [("client_id", "=", client.id)], order="name, version desc"
        )
        usage = request.env["codestra.billing.usage"].search(
            [
                ("contract_id.client_id", "=", client.id),
                ("state", "in", ["approved", "invoiced"]),
            ],
            order="occurred_at desc",
            limit=100,
        )
        return request.render(
            "codestra_client_portal.portal_dashboard",
            {
                "page_name": "codestra_dashboard",
                "client": client,
                "contracts": contracts,
                "usage": usage,
            },
        )

    @http.route(
        ["/my/codestra/contracts/<int:contract_id>"],
        type="http",
        auth="user",
        website=True,
    )
    def codestra_contract(self, contract_id, **kwargs):
        client = self._client_partner()
        contract = request.env["codestra.client.contract"].search(
            [("id", "=", contract_id), ("client_id", "=", client.id)], limit=1
        )
        if not contract:
            return request.not_found()
        usage = request.env["codestra.billing.usage"].search(
            [
                ("contract_id", "=", contract.id),
                ("state", "in", ["approved", "invoiced"]),
            ],
            order="occurred_at desc",
        )
        return request.render(
            "codestra_client_portal.portal_contract",
            {
                "page_name": "codestra_contract",
                "client": client,
                "contract": contract,
                "usage": usage,
            },
        )
