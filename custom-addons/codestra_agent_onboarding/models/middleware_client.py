"""Odoo facade for the approved Middleware agent-provisioning transport."""

from __future__ import annotations

from odoo import SUPERUSER_ID, api, models
from odoo.exceptions import ValidationError

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
    def create_request(self, payload, *, idempotency_key, correlation_id):
        if not isinstance(payload, dict) or not payload.get("request_id"):
            raise ValidationError("Middleware provisioning payload is invalid.")
        if not isinstance(idempotency_key, str) or len(idempotency_key) < 16:
            raise ValidationError("Middleware provisioning idempotency key is invalid.")
        if not isinstance(correlation_id, str) or not correlation_id:
            raise ValidationError("Middleware provisioning correlation ID is invalid.")
        return self.env[
            "codestra.middleware.agent.provisioning.transport"
        ].with_user(SUPERUSER_ID).create_request(
            payload,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @api.model
    def reconcile_request(
        self,
        middleware_request_id,
        *,
        correlation_id,
        reason,
        expected_request_id=None,
    ):
        return self.env[
            "codestra.middleware.agent.provisioning.transport"
        ].with_user(SUPERUSER_ID).reconcile_request(
            middleware_request_id,
            correlation_id=correlation_id,
            reason=reason,
            expected_request_id=expected_request_id,
        )
