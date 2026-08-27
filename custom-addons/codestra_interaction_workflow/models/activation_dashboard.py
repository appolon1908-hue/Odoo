from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError


class CodestraIntegrationDashboard(models.AbstractModel):
    _name = "codestra.integration.dashboard"
    _description = "Codestra Integration Dashboard Read Model"

    @api.model
    def _require_access(self):
        if not (
            self.env.user.has_group("call_center_core.group_call_center_user")
            or self.env.user.has_group("call_center_core.group_call_center_manager")
        ):
            raise AccessError("Integration dashboard access is not permitted.")

    @api.model
    def get_dashboard_snapshot(self, window_minutes=60):
        self._require_access()
        now = fields.Datetime.now()
        start = now - timedelta(minutes=int(window_minutes))
        outbox = self.env["codestra.runtime.integration.outbox"]
        result = self.env["codestra.integration.result.inbox"]
        trace = self.env["codestra.integration.trace"]
        return {
            "generated_at": fields.Datetime.to_string(now),
            "window_minutes": int(window_minutes),
            "cards": {
                "pending_outbox": outbox.search_count([( "delivery_state", "in", ["pending", "failed"]) ]),
                "oldest_pending_age_seconds": self._oldest_pending_age(outbox, now),
                "failed_executions": result.search_count([( "execution_status", "=", "FAILED"), ("received_at", ">=", start)]),
                "dead_letters": outbox.search_count([( "delivery_state", "=", "dead_letter") ]),
                "missing_results": trace.search_count([( "current_status", "=", "ACKNOWLEDGED"), ("result_inbox_id", "=", False)]),
                "reconciliation_drift": trace.search_count([( "reconciliation_status", "!=", "RECONCILED") ]),
            },
        }

    @staticmethod
    def _oldest_pending_age(outbox, now):
        record = outbox.search([( "delivery_state", "in", ["pending", "failed"]) ], order="created_at asc", limit=1)
        return int((now - record.created_at).total_seconds()) if record else 0

    @api.model
    def request_delivery_retry(self, delivery_id, reason):
        self._require_access()
        return self.env["codestra.integration.retry.request"].create({
            "delivery_id": delivery_id,
            "correlation_id": delivery_id,
            "reason": reason,
            "requested_by": self.env.user.id,
        }).id

    @api.model
    def request_workflow_activation(self, workflow_key, workflow_version, environment, reason):
        self._require_access()
        return self.env["codestra.integration.activation.request"].create({
            "workflow_key": workflow_key,
            "workflow_version": workflow_version,
            "environment": environment,
            "reason": reason,
            "requested_by": self.env.user.id,
        }).id
