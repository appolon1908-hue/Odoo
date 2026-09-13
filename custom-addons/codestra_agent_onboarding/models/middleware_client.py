"""Odoo facade for the approved Middleware agent-provisioning transport."""

from __future__ import annotations

from odoo import SUPERUSER_ID, api, models
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.codestra_middleware_bridge.models.agent_provisioning_transport import (
    MiddlewareProvisioningOutcomeUnknown,
    MiddlewareProvisioningRejected,
)

AGENT_PROVISIONING_PATH = "/platform/v1/agent-provisioning/requests"
AgentProvisioningRejected = MiddlewareProvisioningRejected
AgentProvisioningOutcomeUnknown = MiddlewareProvisioningOutcomeUnknown


class CodestraAgentProvisioningMiddlewareClient(models.AbstractModel):
    """Keep onboarding dependent on the bridge boundary, not on HTTP details."""

    _name = "codestra.agent.provisioning.middleware.client"
    _description = "Canonical Middleware Agent Provisioning Client"

    @api.model
    def _authorize_workflow(self, onboarding, correlation_id):
        onboarding.ensure_one()
        onboarding._require_global_administrator()
        request = onboarding.provisioning_request_id
        if (onboarding.state != "provisioning" or not request
                or request.correlation_id != correlation_id
                or request.state not in {"provisioning", "partially_provisioned", "verification", "awaiting_user_activation", "failed"}
                or not onboarding.campaign_membership_id
                or onboarding.campaign_membership_id.state != "pending_sync"):
            raise AccessError("An approved onboarding workflow is required.")

    @api.model
    def _create_request(self, onboarding, payload, *, idempotency_key, correlation_id):
        self._authorize_workflow(onboarding, correlation_id)
        if not isinstance(payload, dict) or payload.get("request_id") != onboarding.integration_uuid:
            raise AccessError("Provisioning request identity mismatch.")
        if not isinstance(payload, dict) or not payload.get("request_id"):
            raise ValidationError("Middleware provisioning payload is invalid.")
        if not isinstance(idempotency_key, str) or len(idempotency_key) < 16:
            raise ValidationError("Middleware provisioning idempotency key is invalid.")
        if not isinstance(correlation_id, str) or not correlation_id:
            raise ValidationError("Middleware provisioning correlation ID is invalid.")
        return self.env[
            "codestra.middleware.agent.provisioning.transport"
        ].with_user(SUPERUSER_ID)._create_request(
            payload,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @api.model
    def _reconcile_request(
        self,
        onboarding,
        middleware_request_id,
        *,
        correlation_id,
        reason,
        expected_request_id=None,
    ):
        self._authorize_workflow(onboarding, correlation_id)
        if (middleware_request_id != onboarding.middleware_request_id
                or expected_request_id != onboarding.integration_uuid):
            raise AccessError("Provisioning request identity mismatch.")
        return self.env[
            "codestra.middleware.agent.provisioning.transport"
        ].with_user(SUPERUSER_ID)._reconcile_request(
            middleware_request_id,
            correlation_id=correlation_id,
            reason=reason,
            expected_request_id=expected_request_id,
        )
