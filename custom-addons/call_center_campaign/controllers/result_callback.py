import json

from odoo import http
from odoo.http import Response


class CodestraLegacyIntegrationResultController(http.Controller):
    """Keep the retired callback path fail-closed during client migration."""

    @http.route(
        "/codestra/integration/v1/results",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def retired_result_callback(self):
        document = {
            "status": "REJECTED",
            "error": {
                "code": "LEGACY_INTEGRATION_ROUTE_RETIRED",
                "classification": "CONFIGURATION",
                "retryable": False,
                "safe_message": (
                    "Resolve and use the logical endpoint key odoo.results.create."
                ),
            },
        }
        return Response(
            json.dumps(document, sort_keys=True, separators=(",", ":")),
            status=410,
            content_type="application/json",
        )
