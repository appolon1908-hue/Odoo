import hashlib
import hmac
import json

from odoo import http
from odoo.http import request
from werkzeug.exceptions import BadRequest, Conflict, Forbidden, NotFound

from .service_auth import signature, validate_call_mapping, validate_request

ALLOWED_FIELDS = {
    "contract_version",
    "recording_uid",
    "vicidial_recording_id",
    "vicidial_call_id",
    "asterisk_uniqueid",
    "started_at",
    "duration_seconds",
    "format",
    "codec",
    "channels",
    "sample_rate_hz",
    "file_size_bytes",
    "sha256",
    "object_version_id",
    "storage_status",
    "retention_class",
    "retention_until",
    "legal_hold",
    "upload_attempts",
    "last_error",
    "verified_at",
    "environment",
    "campaign_key",
    "agent_key",
}
REQUIRED_FIELDS = {
    "contract_version",
    "recording_uid",
    "vicidial_recording_id",
    "vicidial_call_id",
    "asterisk_uniqueid",
    "started_at",
    "duration_seconds",
    "format",
    "codec",
    "channels",
    "sample_rate_hz",
    "file_size_bytes",
    "sha256",
    "object_version_id",
    "storage_status",
    "retention_class",
    "retention_until",
    "legal_hold",
    "environment",
    "campaign_key",
    "agent_key",
}
STATUS_FIELDS = {
    "storage_status",
    "verification_status",
    "odoo_link_status",
    "retention_status",
    "legal_hold",
    "retention_until",
    "middleware_acknowledgement_status",
    "middleware_acknowledgement_time",
    "transcription_status",
    "qa_status",
    "upload_attempts",
    "last_error",
    "verified_at",
}


class RecordingAPI(http.Controller):
    signature = staticmethod(signature)

    def _authenticate(self):
        headers = request.httprequest.headers
        params = request.env["ir.config_parameter"].sudo()
        secret = params.get_param("codestra.recording_middleware_service_secret", "")
        allowed_environment = params.get_param(
            "codestra.recording_environment", "staging"
        )
        try:
            authenticated = validate_request(
                headers,
                request.httprequest.get_data(),
                request.httprequest.method,
                request.httprequest.path,
                secret,
                "codestra-middleware",
                "codestra-odoo-recording-api",
                allowed_environment,
            )
        except ValueError as exc:
            raise Forbidden(
                "Recording middleware service authentication failed."
            ) from exc
        nonce_model = request.env["codestra.vicidial.recording.api.nonce"].sudo()
        if nonce_model.search_count(
            [
                ("environment", "=", authenticated["environment"]),
                ("service_identity", "=", authenticated["identity"]),
                ("nonce", "=", authenticated["nonce"]),
            ]
        ):
            raise Forbidden("Recording middleware service authentication failed.")
        nonce_model.create(
            {
                "environment": authenticated["environment"],
                "service_identity": authenticated["identity"],
                "nonce": authenticated["nonce"],
                "request_timestamp": authenticated["timestamp"],
            }
        )
        return authenticated["environment"], authenticated["idempotency_key"]

    @staticmethod
    def _body():
        if (request.httprequest.content_length or 0) > 262144:
            raise BadRequest("Request too large.")
        try:
            body = json.loads(request.httprequest.get_data())
        except (TypeError, ValueError) as exc:
            raise BadRequest("JSON object required.") from exc
        if not isinstance(body, dict):
            raise BadRequest("JSON object required.")
        return body

    @staticmethod
    def _ack(recording):
        return {
            "contract_version": recording.contract_version,
            "recording_uid": recording.recording_uid,
            "odoo_record_id": recording.id,
            "call_link_status": "linked" if recording.call_id else "unresolved",
            "lead_link_status": "linked" if recording.lead_id else "not_present",
            "campaign_link_status": "linked" if recording.campaign_id else "unresolved",
            "agent_link_status": "linked" if recording.agent_id else "unresolved",
            "storage_status": recording.storage_status,
            "retention_class": recording.retention_class,
            "retention_until": recording.retention_until.isoformat()
            if recording.retention_until
            else None,
            "legal_hold": recording.legal_hold,
            "updated_at": recording.updated_at.isoformat()
            if recording.updated_at
            else None,
        }

    @http.route(
        "/codestra/api/v1/recordings/upsert",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def upsert(self):
        environment, key = self._authenticate()
        payload = self._body()
        unknown = set(payload) - ALLOWED_FIELDS
        missing = REQUIRED_FIELDS - set(payload)
        if (
            unknown
            or missing
            or payload.get("environment") != environment
            or payload.get("contract_version") != "1.0"
        ):
            raise BadRequest("Recording request schema or environment is invalid.")
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        idempotency = request.env["codestra.vicidial.recording.api.idempotency"].sudo()
        prior = idempotency.search(
            [("environment", "=", environment), ("idempotency_key", "=", key)],
            limit=1,
        )
        if prior:
            if not hmac.compare_digest(prior.request_hash, digest):
                raise Conflict("Idempotency key payload conflict.")
            return request.make_json_response(prior.acknowledgement())
        call = (
            request.env["codestra.vicidial.call"]
            .sudo()
            .search([("uniqueid", "=", payload["vicidial_call_id"])], limit=1)
        )
        if not call or not call.campaign_id or not call.agent_id:
            raise Conflict("Existing call, campaign and agent links are required.")
        try:
            validate_call_mapping(
                payload["campaign_key"],
                payload["agent_key"],
                call.campaign_id.campaign_id,
                call.agent_id.vicidial_user,
            )
        except ValueError as exc:
            raise Conflict(
                "Call mapping does not match authoritative Odoo links."
            ) from exc
        values = {
            field: payload[field]
            for field in ALLOWED_FIELDS
            if field in payload and field not in {"campaign_key", "agent_key"}
        }
        values.update(
            {
                "call_id": call.id,
                "campaign_id": call.campaign_id.id,
                "agent_id": call.agent_id.id,
                "lead_id": (call.crm_lead_id or call.lead_id).id or False,
            }
        )
        model = request.env["codestra.vicidial.recording"].sudo()
        recording = model.search(
            [("recording_uid", "=", payload["recording_uid"])], limit=1
        )
        if recording:
            if (
                recording.call_id != call
                or recording.campaign_id != call.campaign_id
                or recording.agent_id != call.agent_id
            ):
                raise Conflict(
                    "Recording UID is already bound to a different call mapping."
                )
            recording.with_context(retention_reason="middleware metadata upsert").write(
                values
            )
        else:
            recording = model.create(values)
        acknowledgement = self._ack(recording)
        idempotency.create(
            {
                "environment": environment,
                "idempotency_key": key,
                "request_hash": digest,
                "recording_uid": recording.recording_uid,
                "acknowledgement_json": json.dumps(
                    acknowledgement, sort_keys=True, default=str
                ),
            }
        )
        request.env["codestra.integration.audit"].sudo().create(
            {
                "action": "recording_metadata_upsert",
                "model_name": recording._name,
                "record_res_id": recording.id,
                "success": True,
                "after_json": json.dumps(
                    {
                        "recording_uid": recording.recording_uid,
                        "storage_status": recording.storage_status,
                    },
                    sort_keys=True,
                ),
            }
        )
        return request.make_json_response(acknowledgement)

    @http.route(
        "/codestra/api/v1/recordings/<string:recording_uid>",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def get_recording(self, recording_uid):
        self._authenticate()
        recording = (
            request.env["codestra.vicidial.recording"]
            .sudo()
            .search([("recording_uid", "=", recording_uid)], limit=1)
        )
        if not recording:
            raise NotFound("Recording not found.")
        return request.make_json_response(self._ack(recording))

    @http.route(
        "/codestra/api/v1/recordings/<string:recording_uid>/status",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def update_status(self, recording_uid):
        environment, _key = self._authenticate()
        payload = self._body()
        if (
            not payload
            or set(payload) - (STATUS_FIELDS | {"contract_version", "environment"})
            or payload.get("contract_version") != "1.0"
            or payload.get("environment") != environment
        ):
            raise BadRequest("Recording status schema is invalid.")
        recording = (
            request.env["codestra.vicidial.recording"]
            .sudo()
            .search([("recording_uid", "=", recording_uid)], limit=1)
        )
        if not recording:
            raise NotFound("Recording not found.")
        values = {field: payload[field] for field in STATUS_FIELDS if field in payload}
        acknowledgement_status = values.pop("middleware_acknowledgement_status", None)
        acknowledgement_time = values.pop("middleware_acknowledgement_time", None)
        recording.with_context(
            retention_reason="middleware status acknowledgement"
        ).write(values)
        if acknowledgement_status:
            audit = (
                request.env["codestra.vicidial.recording.retention.audit"]
                .sudo()
                .search(
                    [
                        ("recording_id", "=", recording.id),
                        ("middleware_acknowledgement_status", "=", "pending"),
                    ],
                    order="event_time desc",
                    limit=1,
                )
            )
            if audit:
                # Status acknowledgement is the sole controlled completion of append-only evidence.
                audit.with_context(allow_middleware_acknowledgement=True).write(
                    {
                        "middleware_acknowledgement_status": acknowledgement_status,
                        "middleware_acknowledgement_time": acknowledgement_time,
                    }
                )
        request.env["codestra.integration.audit"].sudo().create(
            {
                "action": "recording_status_update",
                "model_name": recording._name,
                "record_res_id": recording.id,
                "success": True,
                "after_json": json.dumps(
                    {
                        key: value
                        for key, value in payload.items()
                        if key not in {"last_error"}
                    },
                    sort_keys=True,
                ),
            }
        )
        return request.make_json_response(self._ack(recording))
