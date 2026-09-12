from __future__ import annotations

from odoo.addons.call_center_campaign.controllers.integration_api import (
    IntegrationConflict,
    IntegrationNotFound,
    IntegrationRejected,
    _body,
    _handle_errors,
    _json_response,
)
from odoo import http
from odoo.http import request


SERVICE_GROUP = "codestra_observability_integration.group_codestra_observability_service"
KPI_WRITE_SCOPE = "odoo.observability.kpis.write"
INCIDENT_WRITE_SCOPE = "odoo.observability.incidents.write"
READ_SCOPE = "odoo.observability.read"


class CodestraKyyowObservabilityApi(http.Controller):
    def _service_user(self):
        params = request.env["ir.config_parameter"].sudo()
        configured = (
            params.get_param("codestra.integration.observability_service_user_id")
            or params.get_param("codestra.integration.service_user_id")
            or "0"
        )
        try:
            user_id = int(configured)
        except (TypeError, ValueError) as exc:
            raise IntegrationRejected("observability service identity rejected") from exc
        user = request.env["res.users"].sudo().browse(user_id).exists()
        group = request.env.ref(SERVICE_GROUP)
        if not user or not user.active or group not in user.group_ids:
            raise IntegrationRejected("observability service identity rejected")
        request.update_env(user=user.id)
        return user

    def _tenant(self, claims, body):
        tenant_id = body.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise IntegrationRejected("tenant_id is required")
        params = request.env["ir.config_parameter"].sudo()
        allowed = {
            value.strip()
            for value in (params.get_param("codestra.observability.tenant_ids") or "").split(",")
            if value.strip()
        }
        if not allowed or tenant_id not in allowed:
            raise IntegrationRejected("observability tenant scope rejected")
        claim_tenant = claims.get("tenant_id")
        if isinstance(claim_tenant, str) and claim_tenant and claim_tenant != tenant_id:
            raise IntegrationRejected("observability token tenant scope rejected")
        claim_tenants = claims.get("tenant_ids")
        if isinstance(claim_tenants, list) and claim_tenants and tenant_id not in claim_tenants:
            raise IntegrationRejected("observability token tenant scope rejected")
        return tenant_id

    @staticmethod
    def _required_body_fields():
        return {"tenant_id", "event_id", "projection_hash"}

    @http.route(
        "/api/v1/integration/observability/kpis",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def create_kpi(self):
        def operation():
            claims, body, _ = _body(
                KPI_WRITE_SCOPE,
                self._required_body_fields(),
            )
            self._service_user()
            tenant_id = self._tenant(claims, body)
            if body["tenant_id"] != tenant_id:
                raise IntegrationConflict("tenant binding conflict")
            record, duplicate = request.env[
                "kyyow.observability.kpi.snapshot"
            ]._from_payload(body)
            document = {
                "status": "APPLIED",
                "operation": "observability.kpis.create",
                "event_id": record.event_id,
                "tenant_id": record.tenant_id,
                "correlation_id": record.correlation_id,
                "receipt_id": f"kyyow-kpi-{record.id}",
                "duplicate": duplicate,
            }
            return _json_response(document, 200 if duplicate else 201)

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/observability/incidents",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def upsert_incident(self):
        def operation():
            claims, body, _ = _body(
                INCIDENT_WRITE_SCOPE,
                self._required_body_fields(),
            )
            self._service_user()
            tenant_id = self._tenant(claims, body)
            if body["tenant_id"] != tenant_id:
                raise IntegrationConflict("tenant binding conflict")
            record, duplicate = request.env[
                "kyyow.observability.incident"
            ]._from_payload(body)
            document = {
                "status": "APPLIED",
                "operation": "observability.incidents.upsert",
                "event_id": body["event_id"],
                "tenant_id": tenant_id,
                "incident_id": record.incident_id,
                "state": record.state,
                "resource_version": record.resource_version,
                "correlation_id": record.correlation_id,
                "receipt_id": f"kyyow-incident-{record.id}",
                "duplicate": duplicate,
            }
            return _json_response(document, 200 if duplicate else 201)

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/observability/kpis",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def read_kpi(self):
        def operation():
            claims, body, _ = _body(READ_SCOPE)
            self._service_user()
            tenant_id = self._tenant(claims, body)
            event_id = body.get("event_id")
            domain = [("tenant_id", "=", tenant_id)]
            if event_id:
                domain.append(("event_id", "=", event_id))
            record = request.env[
                "kyyow.observability.kpi.snapshot"
            ].search(domain, order="observed_at desc, id desc", limit=1)
            if not record:
                raise IntegrationNotFound("KPI snapshot not found")
            return _json_response(
                {
                    "status": "FOUND",
                    "operation": "observability.kpis.read",
                    "tenant_id": tenant_id,
                    "data": record.document(),
                }
            )

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/observability/incidents",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def read_incident(self):
        def operation():
            claims, body, _ = _body(READ_SCOPE)
            self._service_user()
            tenant_id = self._tenant(claims, body)
            incident_id = body.get("incident_id")
            domain = [("tenant_id", "=", tenant_id)]
            if incident_id:
                domain.append(("incident_id", "=", incident_id))
            record = request.env[
                "kyyow.observability.incident"
            ].search(domain, order="updated_at desc, id desc", limit=1)
            if not record:
                raise IntegrationNotFound("incident not found")
            return _json_response(
                {
                    "status": "FOUND",
                    "operation": "observability.incidents.read",
                    "tenant_id": tenant_id,
                    "data": record.document(),
                }
            )

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/observability/sync-status",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def sync_status(self):
        def operation():
            claims, body, _ = _body(READ_SCOPE)
            self._service_user()
            tenant_id = self._tenant(claims, body)
            kpis = request.env["kyyow.observability.kpi.snapshot"].search_count(
                [("tenant_id", "=", tenant_id)]
            )
            incidents = request.env["kyyow.observability.incident"].search_count(
                [("tenant_id", "=", tenant_id)]
            )
            latest_kpi = request.env[
                "kyyow.observability.kpi.snapshot"
            ].search(
                [("tenant_id", "=", tenant_id)],
                order="created_at desc, id desc",
                limit=1,
            )
            latest_incident = request.env[
                "kyyow.observability.incident"
            ].search(
                [("tenant_id", "=", tenant_id)],
                order="updated_at desc, id desc",
                limit=1,
            )
            return _json_response(
                {
                    "status": "READY",
                    "operation": "observability.sync.read",
                    "tenant_id": tenant_id,
                    "kpi_snapshot_count": kpis,
                    "incident_count": incidents,
                    "latest_kpi_created_at": (
                        latest_kpi.created_at.isoformat() if latest_kpi else None
                    ),
                    "latest_incident_updated_at": (
                        latest_incident.updated_at.isoformat()
                        if latest_incident
                        else None
                    ),
                }
            )

        return _handle_errors(operation)
