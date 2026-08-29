import json
from datetime import datetime, timezone

from odoo import fields, http
from odoo.addons.call_center_campaign.controllers.integration_api import (
    CodestraIntegrationApiController,
    IntegrationConflict,
    IntegrationNotFound,
    IntegrationRejected,
    _assert_organization_scope,
    _assert_scope,
    _authenticate,
    _body,
    _find_outbox,
    _handle_errors,
    _json_response,
)
from odoo.http import request


def _hash_value(value, field_name):
    normalized = str(value or "").removeprefix("sha256:")
    if len(normalized) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in normalized
    ):
        raise IntegrationRejected(f"{field_name} must be a SHA-256 value")
    return normalized.lower()


def _datetime_value(value):
    if not value:
        return fields.Datetime.now()
    try:
        return (
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
    except ValueError as exc:
        raise IntegrationRejected("invalid result timestamp") from exc


def _scope(record):
    return (
        record.environment
        if "environment" in record._fields
        else record.record_environment,
        record.business_unit_id.code,
        record.campaign_id.code,
    )


def _projection_document(projection):
    return {
        "projection_public_id": projection.state_public_id,
        "environment": projection.record_environment,
        "agent_public_id": projection.agent_public_id,
        "business_unit_public_id": projection.business_unit_public_id,
        "campaign_public_id": projection.campaign_public_id,
        "allocation_reservation_public_id": (
            projection.allocation_reservation_public_id or None
        ),
        "phone_public_id": projection.phone_public_id or None,
        "endpoint_public_id": projection.endpoint_public_id or None,
        "extension": projection.extension or None,
        "desired_enabled": projection.desired_enabled,
        "desired_campaign_membership": projection.desired_campaign_membership,
        "desired_callback_permission": projection.desired_callback_permission,
        "desired_transfer_permission": projection.desired_transfer_permission,
        "desired_external_call_permission": (
            projection.desired_external_call_permission
        ),
        "desired_endpoint_context_key": (
            projection.desired_endpoint_context_key or None
        ),
        "desired_state_version": projection.desired_state_version,
        "desired_state_hash": f"sha256:{projection.desired_state_hash}",
        "observed_state": projection.observed_state,
        "observed_state_version": projection.observed_state_version,
        "observed_state_hash": (
            f"sha256:{projection.observed_state_hash}"
            if projection.observed_state_hash
            else None
        ),
        "observed_vicidial_user_exists": (
            projection.observed_vicidial_user_exists
        ),
        "observed_vicidial_user_active": (
            projection.observed_vicidial_user_active
        ),
        "observed_vicidial_phone_exists": (
            projection.observed_vicidial_phone_exists
        ),
        "observed_vicidial_phone_active": (
            projection.observed_vicidial_phone_active
        ),
        "observed_asterisk_endpoint_exists": (
            projection.observed_asterisk_endpoint_exists
        ),
        "observed_asterisk_endpoint_enabled": (
            projection.observed_asterisk_endpoint_enabled
        ),
        "observed_asterisk_contact_count": (
            projection.observed_asterisk_contact_count
        ),
        "observed_registration_status": projection.observed_registration_status,
        "observed_campaign_membership": (
            projection.observed_campaign_membership
        ),
        "observed_at": fields.Datetime.to_string(projection.observed_at),
        "reconciliation_status": projection.reconciliation_status,
        "last_result_public_id": (
            projection.last_result_id.result_public_id
            if projection.last_result_id
            else None
        ),
    }


def _mapping_document(mapping):
    return {
        "mapping_public_id": mapping.mapping_public_id,
        "environment": mapping.environment,
        "agent_public_id": mapping.agent_public_id,
        "business_unit_public_id": mapping.business_unit_public_id,
        "campaign_public_id": mapping.campaign_public_id,
        "allocation_reservation_public_id": (
            mapping.allocation_reservation_public_id or None
        ),
        "target_system": mapping.target_system,
        "target_resource_type": mapping.target_resource_type,
        "target_public_id": mapping.target_public_id,
        "target_native_id": mapping.target_native_id or None,
        "extension": mapping.extension or None,
        "phone_public_id": mapping.phone_public_id or None,
        "endpoint_public_id": mapping.endpoint_public_id or None,
        "desired_state_version": mapping.desired_state_version,
        "observed_state_version": mapping.observed_state_version,
        "desired_state_hash": (
            f"sha256:{mapping.desired_state_hash}"
            if mapping.desired_state_hash
            else None
        ),
        "observed_state_hash": (
            f"sha256:{mapping.observed_state_hash}"
            if mapping.observed_state_hash
            else None
        ),
        "mapping_status": mapping.mapping_status,
        "last_readback_at": fields.Datetime.to_string(mapping.last_readback_at),
        "last_reconciled_at": fields.Datetime.to_string(mapping.last_reconciled_at),
    }


class CodestraTelephonyIntegrationApiController(CodestraIntegrationApiController):
    @http.route()
    def create_result(self):
        raw = request.httprequest.get_data(cache=True)
        try:
            document = json.loads(raw or b"{}")
        except (TypeError, ValueError):
            return super().create_result()
        if document.get("result_domain") != "TELEPHONY":
            return super().create_result()

        def operation():
            required = {
                "schema_version",
                "result_public_id",
                "originating_outbox_public_id",
                "event_id",
                "command_id",
                "delivery_id",
                "registration_id",
                "acknowledgement_id",
                "operation_public_id",
                "correlation_id",
                "causation_id",
                "environment",
                "organization_public_id",
                "business_unit_public_id",
                "campaign_public_id",
                "target_system",
                "target_resource_type",
                "target_public_id",
                "requested_state_version",
                "applied_state_version",
                "observed_state_version",
                "application_status",
                "readback_status",
                "application_hash",
                "readback_hash",
                "result_hash",
                "policy_hash",
                "result_domain",
            }
            claims, body, request_hash = _body(
                {"odoo.results.create", "odoo.integration.results.write"},
                required,
            )
            environment = str(body["environment"]).upper()
            outbox = _find_outbox(body["originating_outbox_public_id"])
            _assert_scope(
                claims,
                environment,
                body["business_unit_public_id"],
                body["campaign_public_id"],
            )
            _assert_organization_scope(
                claims, body["organization_public_id"]
            )
            if body["schema_version"] != "1.0":
                raise IntegrationRejected("unsupported result schema version")
            if body["application_status"] not in {
                "APPLIED",
                "READBACK_PENDING",
                "READBACK_VERIFIED",
                "READBACK_MISMATCH",
                "RECONCILIATION_REQUIRED",
                "FAILED",
            }:
                raise IntegrationRejected("invalid application status")
            if body["readback_status"] not in {
                "READBACK_PENDING",
                "READBACK_VERIFIED",
                "READBACK_MISMATCH",
                "RECONCILIATION_REQUIRED",
                "FAILED",
            }:
                raise IntegrationRejected("invalid readback status")
            outbox_command_id = (outbox.payload_json or {}).get("command_id")
            policy_hash = _hash_value(body["policy_hash"], "policy_hash")
            if (
                outbox.record_environment != environment
                or outbox.event_uuid != body["event_id"]
                or outbox.correlation_id != body["correlation_id"]
                or outbox.business_unit_code != body["business_unit_public_id"]
                or outbox.campaign_id.code != body["campaign_public_id"]
                or outbox_command_id != body["command_id"]
                or (outbox.policy_hash and outbox.policy_hash != policy_hash)
            ):
                raise IntegrationConflict("IMMUTABLE_RESULT_BINDING_CONFLICT")

            result_hash = _hash_value(body["result_hash"], "result_hash")
            application_hash = _hash_value(
                body["application_hash"], "application_hash"
            )
            readback_hash = _hash_value(body["readback_hash"], "readback_hash")
            inbox_model = request.env["codestra.integration.result.inbox"].sudo()
            duplicate_domain = [
                "|",
                "|",
                ("result_public_id", "=", body["result_public_id"]),
                ("delivery_id", "=", body["delivery_id"]),
                ("acknowledgement_id", "=", body["acknowledgement_id"]),
            ]
            prior = inbox_model.search(duplicate_domain, limit=1)
            immutable = {
                "result_public_id": body["result_public_id"],
                "delivery_id": body["delivery_id"],
                "event_id": body["event_id"],
                "registration_id": body["registration_id"],
                "acknowledgement_id": body["acknowledgement_id"],
                "correlation_id": body["correlation_id"],
                "operation_public_id": body["operation_public_id"],
                "command_public_id": body["command_id"],
                "target_system": body["target_system"],
                "target_resource_type": body["target_resource_type"],
                "target_public_id": body["target_public_id"],
                "result_hash": result_hash,
                "application_hash": application_hash,
                "readback_hash": readback_hash,
            }
            if prior:
                if any(prior[key] != value for key, value in immutable.items()):
                    raise IntegrationConflict("IMMUTABLE_RESULT_BINDING_CONFLICT")
                return _json_response(
                    {
                        "schema_version": "1.0",
                        "result_public_id": prior.result_public_id,
                        "status": "ACCEPTED",
                        "application_status": prior.application_status,
                        "readback_status": prior.readback_status,
                        "idempotency_status": "DUPLICATE",
                        "trace_updated": True,
                        "reconciliation_status": prior.reconciliation_status,
                        "persisted_at": fields.Datetime.to_string(prior.received_at),
                    }
                )

            mapping = (
                request.env["codestra.telephony.target.mapping"]
                .sudo()
                .search(
                    [
                        ("environment", "=", environment),
                        ("campaign_public_id", "=", body["campaign_public_id"]),
                        ("target_system", "=", body["target_system"]),
                        ("target_resource_type", "=", body["target_resource_type"]),
                        ("target_public_id", "=", body["target_public_id"]),
                    ],
                    limit=1,
                )
            )
            if not mapping:
                raise IntegrationConflict("TELEPHONY_TARGET_MAPPING_NOT_FOUND")
            projection = (
                request.env["codestra.telephony.desired.state"]
                .sudo()
                .search(
                    [
                        ("record_environment", "=", environment),
                        ("employee_id", "=", mapping.employee_id.id),
                        ("campaign_id", "=", mapping.campaign_id.id),
                    ],
                    limit=1,
                )
            )
            if not projection:
                raise IntegrationConflict("TELEPHONY_PROJECTION_NOT_FOUND")
            requested_version = int(body["requested_state_version"])
            applied_version = int(body["applied_state_version"])
            observed_version = int(body["observed_state_version"])
            if min(requested_version, applied_version, observed_version) < 0:
                raise IntegrationRejected("state versions cannot be negative")
            if (
                body["application_status"] == "APPLIED"
                and applied_version != requested_version
            ):
                raise IntegrationConflict("APPLIED_STATE_VERSION_MISMATCH")
            if requested_version > projection.desired_state_version:
                raise IntegrationConflict("FUTURE_DESIRED_STATE_VERSION")

            payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
            safe_summary = str(
                payload.get("safe_summary") or payload.get("summary") or ""
            )[:512]
            inbox = inbox_model._create_from_callback(
                {
                    "name": body["result_public_id"],
                    "result_public_id": body["result_public_id"],
                    "schema_version": body["schema_version"],
                    "delivery_id": body["delivery_id"],
                    "event_id": body["event_id"],
                    "registration_id": body["registration_id"],
                    "acknowledgement_id": body["acknowledgement_id"],
                    "correlation_id": body["correlation_id"],
                    "causation_id": body["causation_id"],
                    "workflow_id": body.get("workflow_key", "telephony-readback"),
                    "workflow_version": body.get("workflow_version", "1.0.0"),
                    "execution_id": body.get(
                        "execution_id", body["registration_id"]
                    ),
                    "execution_status": body.get("execution_status", "SUCCEEDED"),
                    "result_classification": body.get(
                        "result_classification", "TELEPHONY_READBACK"
                    ),
                    "result_hash": result_hash,
                    "organization_public_id": body["organization_public_id"],
                    "business_unit_id": mapping.business_unit_id.id,
                    "campaign_id": mapping.campaign_id.id,
                    "source_system": "codestra-middleware",
                    "source_environment": environment.lower(),
                    "policy_hash": policy_hash,
                    "originating_outbox_id": outbox.id,
                    "originating_model": outbox.aggregate_type,
                    "originating_res_id": outbox.aggregate_record_id
                    or mapping.campaign_id.id,
                    "received_at": fields.Datetime.now(),
                    "acknowledged_at": _datetime_value(body.get("applied_at")),
                    "processing_status": "RECEIVED",
                    "reconciliation_status": "RECONCILED",
                    "payload_json_redacted": {"safe_summary": safe_summary},
                    "request_hash": request_hash,
                    "created_by_service": claims["azp"],
                    "result_domain": "TELEPHONY",
                    "command_public_id": body["command_id"],
                    "operation_public_id": body["operation_public_id"],
                    "target_system": body["target_system"],
                    "target_resource_type": body["target_resource_type"],
                    "target_public_id": body["target_public_id"],
                    "command_type": body.get("command_type", "telephony.apply"),
                    "operation_type": body.get("operation_type", "READBACK"),
                    "requested_state_version": requested_version,
                }
            )
            run = request.env[
                "codestra.integration.reconciliation.run"
            ].sudo().get_or_create_scan(
                {
                    "environment": environment,
                    "scope_type": "CAMPAIGN",
                    "organization_public_id": body["organization_public_id"],
                    "business_unit_id": mapping.business_unit_id.id,
                    "campaign_id": mapping.campaign_id.id,
                    "target_system": body["target_system"],
                    "trigger_type": "ON_DEMAND",
                    "triggered_by": claims["azp"],
                    "configuration_version": body["schema_version"],
                    "policy_hash": policy_hash,
                    "scan_idempotency_key": (
                        f"result:{body['acknowledgement_id']}"
                    ),
                }
            )
            observed_state = payload.get("observed_state") or (
                "ENABLED" if payload.get("enabled") else "DISABLED"
            )
            mapping_status = payload.get("mapping_status") or mapping.mapping_status
            observed_values = payload.get("observed_values")
            inbox._apply_telephony_readback(
                projection=projection,
                mapping=mapping,
                reconciliation_run=run,
                observed_state=observed_state,
                observed_state_version=observed_version,
                observed_state_hash=readback_hash,
                mapping_status=mapping_status,
                application_hash=application_hash,
                safe_summary=safe_summary,
                observed_values=observed_values,
            )
            inbox._mark_processed()
            outbox._worker_write({"integration_status": "COMPLETED"})
            status = 200 if inbox.application_status == "STALE" else 201
            return _json_response(
                {
                    "schema_version": "1.0",
                    "result_public_id": inbox.result_public_id,
                    "status": "ACCEPTED",
                    "application_status": inbox.application_status,
                    "readback_status": inbox.readback_status,
                    "idempotency_status": "NEW",
                    "trace_updated": True,
                    "reconciliation_status": projection.reconciliation_status,
                    "persisted_at": fields.Datetime.to_string(inbox.received_at),
                },
                status,
            )

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/telephony/projections/<string:projection_public_id>",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def read_telephony_projection(self, projection_public_id):
        def operation():
            claims, _ = _authenticate(
                b"", "odoo.telephony.projections.read"
            )
            projection = (
                request.env["codestra.telephony.desired.state"]
                .sudo()
                .search([("state_public_id", "=", projection_public_id)], limit=1)
            )
            if not projection:
                raise IntegrationNotFound("telephony projection not found")
            _assert_scope(claims, *_scope(projection))
            return _json_response(_projection_document(projection))

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/telephony/projections",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def search_telephony_projections(self, **query):
        def operation():
            claims, _ = _authenticate(
                b"", "odoo.telephony.projections.read"
            )
            args = request.httprequest.args
            agent_id = query.get("agent_public_id") or args.get("agent_public_id")
            campaign_id = query.get("campaign_public_id") or args.get(
                "campaign_public_id"
            )
            if not agent_id or not campaign_id:
                raise IntegrationRejected(
                    "agent_public_id and campaign_public_id are required"
                )
            records = (
                request.env["codestra.telephony.desired.state"]
                .sudo()
                .search(
                    [
                        ("agent_public_id", "=", agent_id),
                        ("campaign_public_id", "=", campaign_id),
                    ],
                    limit=100,
                )
            )
            for record in records:
                _assert_scope(claims, *_scope(record))
            return _json_response(
                {"records": [_projection_document(record) for record in records]}
            )

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/telephony/mappings/<string:mapping_public_id>",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def read_telephony_mapping(self, mapping_public_id):
        def operation():
            claims, _ = _authenticate(b"", "odoo.telephony.mappings.read")
            mapping = (
                request.env["codestra.telephony.target.mapping"]
                .sudo()
                .search([("mapping_public_id", "=", mapping_public_id)], limit=1)
            )
            if not mapping:
                raise IntegrationNotFound("telephony mapping not found")
            _assert_scope(claims, *_scope(mapping))
            return _json_response(_mapping_document(mapping))

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/telephony/mappings",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def search_telephony_mappings(self, **query):
        def operation():
            claims, _ = _authenticate(b"", "odoo.telephony.mappings.read")
            args = request.httprequest.args
            target_system = query.get("target_system") or args.get("target_system")
            target_public_id = query.get("target_public_id") or args.get(
                "target_public_id"
            )
            if not target_system or not target_public_id:
                raise IntegrationRejected(
                    "target_system and target_public_id are required"
                )
            records = (
                request.env["codestra.telephony.target.mapping"]
                .sudo()
                .search(
                    [
                        ("target_system", "=", target_system),
                        ("target_public_id", "=", target_public_id),
                    ],
                    limit=100,
                )
            )
            for record in records:
                _assert_scope(claims, *_scope(record))
            return _json_response(
                {"records": [_mapping_document(record) for record in records]}
            )

        return _handle_errors(operation)

    def _read_reconciliation(self, model_name, public_field, public_id):
        claims, _ = _authenticate(b"", "odoo.reconciliation.read")
        record = (
            request.env[model_name]
            .sudo()
            .search([(public_field, "=", public_id)], limit=1)
        )
        if not record:
            raise IntegrationNotFound("reconciliation record not found")
        run = record if model_name.endswith(".run") else record.reconciliation_run_id
        if not run.business_unit_id or not run.campaign_id:
            raise IntegrationRejected("unscoped reconciliation record rejected")
        _assert_scope(
            claims,
            run.environment,
            run.business_unit_id.code,
            run.campaign_id.code,
        )
        if model_name.endswith(".run"):
            document = {
                "run_public_id": record.run_public_id,
                "environment": record.environment,
                "scope_type": record.scope_type,
                "target_system": record.target_system,
                "status": record.status,
                "records_scanned": record.records_scanned,
                "records_in_sync": record.records_in_sync,
                "drift_count": record.drift_count,
                "repairable_count": record.repairable_count,
                "manual_review_count": record.manual_review_count,
                "failed_count": record.failed_count,
                "evidence_checksum": (
                    f"sha256:{record.evidence_checksum}"
                    if record.evidence_checksum
                    else None
                ),
            }
        else:
            document = {
                "drift_public_id": record.drift_public_id,
                "run_public_id": run.run_public_id,
                "aggregate_model": record.aggregate_model,
                "aggregate_public_id": record.aggregate_public_id,
                "source_system": record.source_system,
                "target_system": record.target_system,
                "target_resource_type": record.target_resource_type,
                "target_public_id": record.target_public_id,
                "drift_type": record.drift_type,
                "severity": record.severity,
                "expected_state_version": record.expected_state_version,
                "observed_state_version": record.observed_state_version,
                "expected_state_hash": (
                    f"sha256:{record.expected_state_hash}"
                    if record.expected_state_hash
                    else None
                ),
                "observed_state_hash": (
                    f"sha256:{record.observed_state_hash}"
                    if record.observed_state_hash
                    else None
                ),
                "repair_eligibility": record.repair_eligibility,
                "repair_status": record.repair_status,
            }
        return _json_response(document)

    @http.route(
        "/api/v1/integration/reconciliation/runs/<string:run_public_id>",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def read_reconciliation_run(self, run_public_id):
        return _handle_errors(
            lambda: self._read_reconciliation(
                "codestra.integration.reconciliation.run",
                "run_public_id",
                run_public_id,
            )
        )

    @http.route(
        "/api/v1/integration/reconciliation/drifts/<string:drift_public_id>",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def read_reconciliation_drift(self, drift_public_id):
        return _handle_errors(
            lambda: self._read_reconciliation(
                "codestra.integration.reconciliation.drift",
                "drift_public_id",
                drift_public_id,
            )
        )
