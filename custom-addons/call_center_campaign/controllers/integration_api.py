import base64
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib import parse as urlparse
from urllib import request as urlrequest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
from odoo import fields, http
from odoo.exceptions import ValidationError
from odoo.http import Response, request

MAX_BODY_BYTES = 65536
TOKEN_CLOCK_SKEW_SECONDS = 30
REQUEST_TTL_SECONDS = 300


class IntegrationRejected(ValueError):
    status = 401


class IntegrationConflict(IntegrationRejected):
    status = 409


class IntegrationNotFound(IntegrationRejected):
    status = 404


def _b64url(value):
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != value:
        raise ValueError("non-canonical base64url")
    return decoded


def _json_response(document, status=200):
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return Response(encoded, status=status, content_type="application/json")


def _canonical_hash(document):
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _scope_values(claims, singular, plural):
    value = claims.get(singular, claims.get(plural, []))
    if isinstance(value, str):
        return [value]
    return value if isinstance(value, list) else []


def _required_scopes(required_scope):
    if isinstance(required_scope, str):
        return {required_scope}
    return set(required_scope)


def _effective_service_key(claims):
    """Normalize an optional null Keycloak mapper claim to mandatory azp."""
    return claims.get("service_key") or claims.get("azp")


def _validated_jwks_url(value):
    parsed = urlparse.urlsplit(value or "")
    private_keycloak = (
        parsed.scheme == "http"
        and parsed.hostname == "keycloak"
        and parsed.port == 8080
    )
    if (
        (parsed.scheme != "https" and not private_keycloak)
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith("/protocol/openid-connect/certs")
    ):
        raise IntegrationRejected(
            "JWKS URL must use credential-free HTTPS or the private Keycloak service."
        )
    return value


def _verify_service_token(token, required_scope):
    parts = token.split(".")
    if len(parts) != 3:
        raise IntegrationRejected("invalid token")
    try:
        header = json.loads(_b64url(parts[0]))
        claims = json.loads(_b64url(parts[1]))
    except (ValueError, TypeError) as exc:
        raise IntegrationRejected("invalid token") from exc
    issuer = os.environ.get("CODESTRA_ODOO_KEYCLOAK_ISSUER", "")
    audience = os.environ.get("CODESTRA_ODOO_INTEGRATION_AUDIENCE", "codestra-odoo")
    jwks_url = os.environ.get("CODESTRA_ODOO_KEYCLOAK_JWKS_URL", "")
    allowed_services = {
        value.strip()
        for value in os.environ.get(
            "CODESTRA_ODOO_INTEGRATION_SERVICE_ALLOWLIST", ""
        ).split(",")
        if value.strip()
    }
    if (
        not issuer
        or not jwks_url
        or not allowed_services
        or header.get("alg") != "RS256"
        or not header.get("kid")
    ):
        raise IntegrationRejected("service identity is not configured")
    jwks_url = _validated_jwks_url(jwks_url)
    # The URL is scheme-, authority-, and path-bounded immediately above.
    with urlrequest.urlopen(jwks_url, timeout=5) as response:  # nosec B310
        jwks = json.loads(response.read(MAX_BODY_BYTES))
    jwk = next(
        (item for item in jwks.get("keys", []) if item.get("kid") == header["kid"]),
        None,
    )
    if not jwk or jwk.get("kty") != "RSA":
        raise IntegrationRejected("signing key rejected")
    public_key = rsa.RSAPublicNumbers(
        int.from_bytes(_b64url(jwk["e"]), "big"),
        int.from_bytes(_b64url(jwk["n"]), "big"),
    ).public_key()
    try:
        public_key.verify(
            _b64url(parts[2]),
            f"{parts[0]}.{parts[1]}".encode(),
            padding.PKCS1v15(),
            SHA256(),
        )
    except (InvalidSignature, ValueError) as exc:
        raise IntegrationRejected("token signature rejected") from exc
    now = int(time.time())
    audience_matches = claims.get("aud") == audience or (
        isinstance(claims.get("aud"), list) and audience in claims["aud"]
    )
    scopes = set(str(claims.get("scope", "")).split())
    required_scopes = _required_scopes(required_scope)
    endpoint_scopes = _scope_values(claims, "endpoint_scope", "endpoint_scopes")
    if (
        claims.get("iss") != issuer
        or not audience_matches
        or not claims.get("sub")
        or not claims.get("jti")
        or claims.get("azp") not in allowed_services
        # Keycloak may emit an explicitly-null optional mapper claim. Treat
        # only a non-empty service_key as an override; azp remains mandatory
        # and is still checked against the configured service allowlist.
        or _effective_service_key(claims) != claims.get("azp")
        or int(claims.get("exp", 0)) < now - TOKEN_CLOCK_SKEW_SECONDS
        or int(claims.get("nbf", 0)) > now + TOKEN_CLOCK_SKEW_SECONDS
        or int(claims.get("iat", now + 1)) > now + TOKEN_CLOCK_SKEW_SECONDS
        or not required_scopes.intersection(scopes)
        or (
            endpoint_scopes
            and not required_scopes.intersection(endpoint_scopes)
        )
    ):
        raise IntegrationRejected("service token claims rejected")
    return claims


def _validate_request_binding(headers, raw, claims, nonce_model):
    try:
        timestamp = int(headers.get("X-Codestra-Timestamp", ""))
    except ValueError as exc:
        raise IntegrationRejected("invalid timestamp") from exc
    if abs(int(time.time()) - timestamp) > REQUEST_TTL_SECONDS:
        raise IntegrationRejected("stale timestamp")
    nonce = headers.get("X-Codestra-Nonce", "")
    if not nonce or len(nonce) > 128:
        raise IntegrationRejected("invalid nonce")
    supplied_hash = headers.get("X-Codestra-Body-SHA256", "").removeprefix("sha256:")
    if supplied_hash != hashlib.sha256(raw).hexdigest():
        raise IntegrationRejected("request hash mismatch")
    traceparent = headers.get("traceparent", "")
    trace_parts = traceparent.split("-")
    if (
        len(trace_parts) != 4
        or trace_parts[0] != "00"
        or len(trace_parts[1]) != 32
        or len(trace_parts[2]) != 16
        or len(trace_parts[3]) != 2
    ):
        raise IntegrationRejected("invalid trace context")
    service_id = claims["azp"]
    if nonce_model.search_count(
        [("service_id", "=", service_id), ("nonce", "=", nonce)]
    ):
        raise IntegrationRejected("replayed request")
    nonce_model.create(
        {
            "service_id": service_id,
            "nonce": nonce,
            "expires_at": fields.Datetime.now()
            + timedelta(seconds=REQUEST_TTL_SECONDS),
        }
    )
    return supplied_hash


def _authenticate(raw, required_scope):
    headers = request.httprequest.headers
    authorization = headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise IntegrationRejected("bearer token required")
    claims = _verify_service_token(
        authorization.removeprefix("Bearer ").strip(), required_scope
    )
    supplied_hash = _validate_request_binding(
        headers,
        raw,
        claims,
        request.env["codestra.integration.callback.nonce"].sudo(),
    )
    return claims, supplied_hash


def _body(required_scope, required_fields=None):
    raw = request.httprequest.get_data(cache=True)
    if len(raw) > MAX_BODY_BYTES:
        raise IntegrationRejected("request too large")
    claims, body_hash = _authenticate(raw, required_scope)
    try:
        document = json.loads(raw or b"{}")
    except (TypeError, ValueError) as exc:
        raise IntegrationRejected("malformed JSON") from exc
    if not isinstance(document, dict):
        raise IntegrationRejected("JSON object required")
    if required_fields and not required_fields.issubset(document):
        raise IntegrationRejected("required fields missing")
    headers = request.httprequest.headers
    required_headers = {
        "Idempotency-Key",
        "X-Codestra-Request-ID",
        "X-Codestra-Correlation-ID",
        "X-Codestra-Causation-ID",
        "traceparent",
    }
    if any(not headers.get(name) for name in required_headers):
        raise IntegrationRejected("required integration headers missing")
    if document.get("idempotency_key") not in {
        None,
        headers["Idempotency-Key"],
    }:
        raise IntegrationConflict("idempotency binding conflict")
    if document.get("correlation_id") not in {
        None,
        headers["X-Codestra-Correlation-ID"],
    }:
        raise IntegrationConflict("correlation binding conflict")
    if document.get("causation_id") not in {
        None,
        headers["X-Codestra-Causation-ID"],
    }:
        raise IntegrationConflict("causation binding conflict")
    return claims, document, body_hash


def _assert_scope(claims, environment, business_unit, campaign=None):
    if claims.get("environment", "").upper() != environment:
        raise IntegrationRejected("environment scope rejected")
    units = _scope_values(claims, "business_unit_scope", "business_units")
    campaigns = _scope_values(claims, "campaign_scope", "campaigns")
    if business_unit not in units or (campaign and campaign not in campaigns):
        raise IntegrationRejected("business scope rejected")


def _assert_organization_scope(claims, organization):
    organizations = _scope_values(
        claims, "organization_scope", "organizations"
    )
    if organization not in organizations:
        raise IntegrationRejected("organization scope rejected")


def _outbox_document(record, lease_token=None):
    campaign = record.campaign_id
    document = {
        "outbox_public_id": record.event_uuid,
        "event_id": record.event_uuid,
        "event_type": record.event_type,
        "schema_version": record.schema_version,
        "record_environment": record.record_environment,
        "aggregate_type": record.aggregate_type,
        "aggregate_public_id": record.aggregate_uuid,
        "aggregate_version": record.design_request_revision,
        "business_unit_public_id": campaign.business_unit_id.code,
        "campaign_public_id": campaign.code,
        "correlation_id": record.correlation_id,
        "causation_id": record.causation_id or None,
        "policy_hash": record.policy_hash or None,
        "payload_hash": f"sha256:{record.payload_hash}",
        "payload": record.payload_json,
        "delivery_state": record.delivery_state,
        "lease_generation": record.lease_generation,
        "lease_expires_at": fields.Datetime.to_string(record.lease_expires_at),
    }
    if lease_token:
        document["lease_token"] = lease_token
    return document


def _find_outbox(outbox_id):
    record = (
        request.env["codestra.runtime.integration.outbox"]
        .sudo()
        .search([("event_uuid", "=", outbox_id)], limit=1)
    )
    if not record:
        raise IntegrationNotFound("outbox record not found")
    return record


def _lease_binding(record, body):
    try:
        record._verify_lease(
            body["consumer_id"],
            body["lease_token"],
            int(body["lease_generation"]),
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise IntegrationConflict("LEASE_GENERATION_MISMATCH") from exc


def _handle_errors(callback):
    try:
        return callback()
    except IntegrationRejected as exc:
        request.env.cr.rollback()
        classification = (
            "CONFLICT"
            if isinstance(exc, IntegrationConflict)
            else "NOT_FOUND"
            if isinstance(exc, IntegrationNotFound)
            else "REJECTED"
        )
        return _json_response(
            {
                "status": "REJECTED",
                "error": {
                    "code": str(exc),
                    "classification": classification,
                    "retryable": False,
                },
            },
            exc.status,
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        request.env.cr.rollback()
        return _json_response(
            {
                "status": "REJECTED",
                "error": {
                    "code": str(exc),
                    "classification": "VALIDATION",
                    "retryable": False,
                },
            },
            422,
        )


class CodestraIntegrationApiController(http.Controller):
    @http.route(
        "/api/v1/integration/capabilities",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def capabilities(self):
        def operation():
            _authenticate(b"", "service.attest")
            return _json_response(
                {
                    "schema_version": "1.0",
                    "service_key": "odoo",
                    "api_version": "v1",
                    "capabilities": [
                        "outbox.claim",
                        "outbox.read",
                        "outbox.renew",
                        "outbox.acknowledge",
                        "outbox.fail",
                        "outbox.release",
                        "results.create",
                        "results.read",
                        "results.reconcile",
                        "desired_state.read",
                        "traces.read",
                        "audit.read",
                        "telephony.projections.read",
                        "telephony.mappings.read",
                        "reconciliation.read",
                    ],
                }
            )

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/outbox/claims",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def claim_outbox(self):
        def operation():
            claims, body, _ = _body(
                "odoo.integration.outbox.claim",
                {"consumer_id", "batch_size", "lease_ttl_ms", "environment"},
            )
            environment = str(body["environment"]).upper()
            units = _scope_values(claims, "business_unit_scope", "business_units")
            if claims.get("environment", "").upper() != environment or not units:
                raise IntegrationRejected("claim scope rejected")
            lease_ttl_ms = int(body["lease_ttl_ms"])
            if lease_ttl_ms % 1000:
                raise IntegrationRejected("lease TTL must use whole seconds")
            records = (
                request.env["codestra.runtime.integration.outbox"]
                .sudo()
                ._claim_batch(
                    limit=int(body["batch_size"]),
                    consumer_id=body["consumer_id"],
                    lease_ttl_seconds=lease_ttl_ms // 1000,
                    record_environment=environment,
                    business_unit_codes=units,
                    event_type_allowlist=body.get("event_type_allowlist"),
                )
            )
            tokens = records.env.context.get("_codestra_lease_tokens", {})
            return _json_response(
                {
                    "claim_id": request.httprequest.headers.get(
                        "X-Codestra-Request-ID"
                    ),
                    "records": [
                        _outbox_document(record, tokens.get(record.id))
                        for record in records
                    ],
                },
                200,
            )

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/outbox/<string:outbox_id>",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def read_outbox(self, outbox_id):
        def operation():
            claims, _ = _authenticate(b"", "odoo.integration.outbox.read")
            record = _find_outbox(outbox_id)
            _assert_scope(
                claims,
                record.record_environment,
                record.business_unit_code,
                record.campaign_id.code,
            )
            return _json_response(_outbox_document(record))

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/outbox/<string:outbox_id>/lease/renew",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def renew_outbox(self, outbox_id):
        def operation():
            claims, body, _ = _body("odoo.integration.outbox.renew")
            record = _find_outbox(outbox_id)
            _assert_scope(
                claims,
                record.record_environment,
                record.business_unit_code,
                record.campaign_id.code,
            )
            _lease_binding(record, body)
            record._renew_lease(
                body["consumer_id"],
                body["lease_token"],
                int(body["lease_generation"]),
                int(body.get("requested_extension_ms", 30000)) // 1000,
            )
            return _json_response(_outbox_document(record))

        return _handle_errors(operation)

    def _finish_outbox(self, outbox_id, action):
        scopes = {
            "acknowledge": "odoo.integration.outbox.acknowledge",
            "fail": "odoo.integration.outbox.fail",
            "release": "odoo.integration.outbox.release",
        }
        claims, body, _ = _body(scopes[action])
        record = _find_outbox(outbox_id)
        _assert_scope(
            claims,
            record.record_environment,
            record.business_unit_code,
            record.campaign_id.code,
        )
        _lease_binding(record, body)
        if action == "acknowledge":
            record._worker_write(
                {
                    "delivery_state": "delivered",
                    "delivered_at": fields.Datetime.now(),
                    "integration_status": "PROCESSING",
                    "processing_started_at": False,
                    "lease_consumer_id": False,
                    "lease_token_hash": False,
                    "lease_expires_at": False,
                    "lease_heartbeat_at": False,
                }
            )
        elif action == "fail":
            record._finalize_delivery_failure(
                RuntimeError(str(body.get("error_classification", "safe failure")))
            )
        else:
            record._release_lease(
                body["consumer_id"],
                body["lease_token"],
                int(body["lease_generation"]),
            )
        return _json_response(_outbox_document(record))

    @http.route(
        "/api/v1/integration/outbox/<string:outbox_id>/acknowledgements",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def acknowledge_outbox(self, outbox_id):
        return _handle_errors(lambda: self._finish_outbox(outbox_id, "acknowledge"))

    @http.route(
        "/api/v1/integration/outbox/<string:outbox_id>/failures",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def fail_outbox(self, outbox_id):
        return _handle_errors(lambda: self._finish_outbox(outbox_id, "fail"))

    @http.route(
        "/api/v1/integration/outbox/<string:outbox_id>/release",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def release_outbox(self, outbox_id):
        return _handle_errors(lambda: self._finish_outbox(outbox_id, "release"))

    @http.route(
        "/api/v1/integration/results",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def create_result(self):
        def operation():
            claims, body, request_hash = _body(
                {"odoo.results.create", "odoo.integration.results.write"},
                {
                    "result_public_id",
                    "delivery_id",
                    "event_id",
                    "registration_id",
                    "acknowledgement_id",
                    "correlation_id",
                    "result_hash",
                    "originating_outbox_public_id",
                    "business_unit_public_id",
                    "campaign_public_id",
                },
            )
            outbox = _find_outbox(body["originating_outbox_public_id"])
            _assert_scope(
                claims,
                outbox.record_environment,
                body["business_unit_public_id"],
                body["campaign_public_id"],
            )
            if (
                outbox.event_uuid != body["event_id"]
                or outbox.correlation_id != body["correlation_id"]
                or outbox.business_unit_code != body["business_unit_public_id"]
                or outbox.campaign_id.code != body["campaign_public_id"]
            ):
                raise IntegrationConflict("immutable outbox binding conflict")
            inbox_model = request.env["codestra.integration.result.inbox"].sudo()
            prior = inbox_model.search(
                [
                    "|",
                    ("result_public_id", "=", body["result_public_id"]),
                    ("acknowledgement_id", "=", body["acknowledgement_id"]),
                ],
                limit=1,
            )
            immutable = (
                "delivery_id",
                "event_id",
                "registration_id",
                "acknowledgement_id",
                "correlation_id",
                "result_hash",
            )
            normalized_hash = str(body["result_hash"]).removeprefix("sha256:")
            if prior:
                for key in immutable:
                    expected = normalized_hash if key == "result_hash" else body[key]
                    if prior[key] != expected:
                        raise IntegrationConflict("IMMUTABLE_RESULT_BINDING_CONFLICT")
                inbox = prior
                status = 200
                idempotency_status = "DUPLICATE"
            else:
                acknowledged_at = body.get("acknowledged_at")
                if acknowledged_at:
                    acknowledged_at = (
                        datetime.fromisoformat(acknowledged_at.replace("Z", "+00:00"))
                        .astimezone(timezone.utc)
                        .replace(tzinfo=None)
                    )
                inbox = inbox_model._create_from_callback(
                    {
                        "name": body["result_public_id"],
                        "result_public_id": body["result_public_id"],
                        "schema_version": body.get("schema_version", "1.0"),
                        "delivery_id": body["delivery_id"],
                        "event_id": body["event_id"],
                        "registration_id": body["registration_id"],
                        "acknowledgement_id": body["acknowledgement_id"],
                        "correlation_id": body["correlation_id"],
                        "causation_id": body.get("causation_id"),
                        "workflow_id": body.get("workflow_id", "logical-workflow"),
                        "workflow_version": body.get("workflow_version", "1.0.0"),
                        "execution_id": body.get(
                            "execution_id", body["registration_id"]
                        ),
                        "execution_status": body.get("execution_status", "SUCCEEDED"),
                        "result_classification": body.get(
                            "result_classification", "COMPLETED"
                        ),
                        "result_hash": normalized_hash,
                        "organization_public_id": body.get(
                            "organization_public_id", "ORG-CODESTRA"
                        ),
                        "business_unit_id": outbox.campaign_id.business_unit_id.id,
                        "campaign_id": outbox.campaign_id.id,
                        "source_system": body.get(
                            "source_system", "codestra-middleware"
                        ),
                        "source_environment": outbox.record_environment.lower(),
                        "policy_hash": str(
                            body.get("policy_hash") or outbox.policy_hash or "0" * 64
                        ).removeprefix("sha256:"),
                        "originating_outbox_id": outbox.id,
                        "originating_model": outbox.aggregate_type,
                        "originating_res_id": outbox.campaign_id.id,
                        "received_at": fields.Datetime.now(),
                        "acknowledged_at": acknowledged_at or fields.Datetime.now(),
                        "processing_status": "RECEIVED",
                        "reconciliation_status": body.get(
                            "reconciliation_status", "RECONCILED"
                        ),
                        "payload_json_redacted": {
                            "summary": str(body.get("payload", {}).get("summary", ""))[
                                :512
                            ]
                        },
                        "request_hash": request_hash,
                        "created_by_service": claims["azp"],
                    }
                )
                inbox._mark_processed()
                outbox._worker_write({"integration_status": "COMPLETED"})
                status = 201
                idempotency_status = "NEW"
            return _json_response(
                {
                    "result_public_id": inbox.result_public_id,
                    "idempotency_status": idempotency_status,
                    "persisted": True,
                    "correlation_id": inbox.correlation_id,
                },
                status,
            )

        return _handle_errors(operation)

    @http.route(
        [
            "/api/v1/integration/results/<string:result_public_id>",
            "/api/v1/integration/results",
        ],
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def read_result(self, result_public_id=None, **query):
        def operation():
            claims, _ = _authenticate(
                b"", {"odoo.results.read", "odoo.integration.results.read"}
            )
            domain = (
                [("result_public_id", "=", result_public_id)]
                if result_public_id
                else [("delivery_id", "=", query.get("delivery_id"))]
            )
            inbox = (
                request.env["codestra.integration.result.inbox"]
                .sudo()
                .search(domain, limit=1)
            )
            if not inbox:
                raise IntegrationNotFound("result not found")
            _assert_scope(
                claims,
                inbox.source_environment.upper(),
                inbox.originating_outbox_id.business_unit_code,
                inbox.campaign_id.code,
            )
            return _json_response(
                {
                    "result_public_id": inbox.result_public_id,
                    "delivery_id": inbox.delivery_id,
                    "event_id": inbox.event_id,
                    "correlation_id": inbox.correlation_id,
                    "execution_status": inbox.execution_status,
                    "processing_status": inbox.processing_status,
                    "reconciliation_status": inbox.reconciliation_status,
                    "result_hash": f"sha256:{inbox.result_hash}",
                }
            )

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/results/<string:result_public_id>/reconcile",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def reconcile_result(self, result_public_id):
        def operation():
            claims, body, _ = _body("odoo.integration.results.reconcile")
            inbox = (
                request.env["codestra.integration.result.inbox"]
                .sudo()
                .search([("result_public_id", "=", result_public_id)], limit=1)
            )
            if not inbox:
                raise IntegrationNotFound("result not found")
            outbox = inbox.originating_outbox_id
            _assert_scope(
                claims,
                outbox.record_environment,
                outbox.business_unit_code,
                inbox.campaign_id.code,
            )
            expected = {
                "delivery_id": inbox.delivery_id,
                "event_id": inbox.event_id,
                "correlation_id": inbox.correlation_id,
                "result_hash": f"sha256:{inbox.result_hash}",
            }
            supplied = {key: body.get(key) for key in expected}
            drift = [
                key
                for key, value in expected.items()
                if supplied.get(key) not in {None, value}
            ]
            status = "IN_SYNC" if not drift else "VERSION_MISMATCH"
            return _json_response(
                {
                    "result_public_id": result_public_id,
                    "reconciliation_status": status,
                    "drift_fields": drift,
                    "desired": expected,
                    "observed": supplied,
                    "reconciled_at": fields.Datetime.to_string(fields.Datetime.now()),
                },
                200 if not drift else 409,
            )

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/traces/<string:correlation_id>",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def read_trace(self, correlation_id):
        def operation():
            claims, _ = _authenticate(
                b"", {"odoo.traces.read", "odoo.integration.traces.read"}
            )
            traces = (
                request.env["codestra.integration.trace"]
                .sudo()
                .search([("correlation_id", "=", correlation_id)])
            )
            if not traces:
                raise IntegrationNotFound("trace not found")
            first = traces[0]
            _assert_scope(
                claims,
                first.originating_outbox_id.record_environment,
                first.originating_outbox_id.business_unit_code,
                first.campaign_id.code,
            )
            return _json_response(
                {
                    "correlation_id": correlation_id,
                    "records": [
                        {
                            "event_id": item.event_id,
                            "delivery_id": item.delivery_id,
                            "registration_id": item.registration_id,
                            "acknowledgement_id": item.acknowledgement_id,
                            "current_status": item.current_status,
                            "reconciliation_status": item.reconciliation_status,
                            "end_to_end_latency_seconds": (
                                item.end_to_end_latency_seconds
                            ),
                        }
                        for item in traces
                    ],
                }
            )

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/traces",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def read_trace_by_record(self, **query):
        def operation():
            claims, _ = _authenticate(
                b"", {"odoo.traces.read", "odoo.integration.traces.read"}
            )
            model = query.get("model") or request.httprequest.args.get("model")
            record_public_id = (
                query.get("record_public_id")
                or request.httprequest.args.get("record_public_id")
            )
            res_id = query.get("res_id") or request.httprequest.args.get("res_id")
            if not model or (not record_public_id and not str(res_id).isdigit()):
                raise IntegrationRejected(
                    "model and record_public_id (or legacy numeric res_id) are required"
                )
            domain = [("originating_model", "=", model)]
            if record_public_id:
                domain.append(
                    ("originating_outbox_id.aggregate_uuid", "=", record_public_id)
                )
            else:
                domain.append(("originating_res_id", "=", int(res_id)))
            traces = (
                request.env["codestra.integration.trace"]
                .sudo()
                .search(domain)
            )
            if not traces:
                raise IntegrationNotFound("trace not found")
            first = traces[0]
            _assert_scope(
                claims,
                first.originating_outbox_id.record_environment,
                first.originating_outbox_id.business_unit_code,
                first.campaign_id.code,
            )
            return _json_response(
                {
                    "model": model,
                    "record_public_id": record_public_id,
                    "res_id": int(res_id) if res_id else None,
                    "correlation_ids": list(
                        dict.fromkeys(traces.mapped("correlation_id"))
                    ),
                    "trace_count": len(traces),
                }
            )

        return _handle_errors(operation)

    @http.route(
        "/api/v1/integration/audit/<int:audit_id>",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def read_audit(self, audit_id):
        def operation():
            claims, _ = _authenticate(b"", "odoo.integration.audit.read")
            audit = (
                request.env["call.center.audit.event"].sudo().browse(audit_id).exists()
            )
            if not audit:
                raise IntegrationNotFound("audit event not found")
            if not audit.business_unit_id:
                raise IntegrationRejected("unscoped audit event rejected")
            units = _scope_values(claims, "business_unit_scope", "business_units")
            if audit.business_unit_id.code not in units:
                raise IntegrationRejected("audit scope rejected")
            return _json_response(
                {
                    "audit_id": str(audit.id),
                    "occurred_at": fields.Datetime.to_string(audit.occurred_at),
                    "event_type": audit.event_type,
                    "model_name": audit.model_name,
                    "record_id": audit.record_id,
                    "business_unit_public_id": audit.business_unit_id.code,
                    "automation_reference": audit.automation_reference or None,
                    "immutable": True,
                }
            )

        return _handle_errors(operation)

    @http.route(
        [
            "/api/v1/integration/desired-state/<string:aggregate_type>/<string:public_id>",
            "/api/v1/integration/agents/<string:public_id>",
            "/api/v1/integration/leads/<string:public_id>",
            "/api/v1/integration/campaigns/<string:public_id>",
        ],
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def read_desired_state(self, public_id, aggregate_type=None):
        def operation():
            claims, _ = _authenticate(
                b"",
                {
                    "odoo.desired_state.read",
                    "odoo.integration.desired_state.read",
                },
            )
            route = request.httprequest.path
            kind = aggregate_type or (
                "agent"
                if "/agents/" in route
                else "lead"
                if "/leads/" in route
                else "campaign"
            )
            if kind == "campaign":
                record = (
                    request.env["call.center.campaign"]
                    .sudo()
                    .search(
                        [
                            "|",
                            ("code", "=", public_id),
                            ("integration_uuid", "=", public_id),
                        ],
                        limit=1,
                    )
                )
                campaign = record
                desired = (
                    {
                        "state": record.state,
                        "active": record.active,
                        "design_automation_enabled": record.design_automation_enabled,
                    }
                    if record
                    else {}
                )
            elif kind == "lead":
                record = (
                    request.env["crm.lead"]
                    .sudo()
                    .search(
                        [
                            "|",
                            ("integration_uuid", "=", public_id),
                            ("external_source_id", "=", public_id),
                        ],
                        limit=1,
                    )
                )
                campaign = record.call_center_campaign_id
                desired = (
                    {
                        "active": record.active,
                        "preferred_contact_method": record.preferred_contact_method,
                        "campaign_remediation_status": record.campaign_remediation_status,
                    }
                    if record
                    else {}
                )
            elif kind == "agent":
                employee = (
                    request.env["hr.employee"]
                    .sudo()
                    .search([("codestra_employee_number", "=", public_id)], limit=1)
                )
                record = employee
                campaign = (
                    request.env["call.center.campaign"]
                    .sudo()
                    .search([("agent_ids", "in", employee.user_id.id)], limit=1)
                    if employee
                    else request.env["call.center.campaign"]
                )
                desired = (
                    {
                        "active": employee.active,
                        "provisioning_state": employee.provisioning_state,
                    }
                    if employee
                    else {}
                )
            elif kind in {"telephony", "telephony_projection"}:
                record = (
                    request.env["codestra.telephony.desired.state"]
                    .sudo()
                    .search([("state_public_id", "=", public_id)], limit=1)
                )
                campaign = record.campaign_id
                desired = (
                    {
                        "enabled": record.desired_enabled,
                        "campaign_membership": (
                            record.desired_campaign_membership
                        ),
                        "callback_permission": (
                            record.desired_callback_permission
                        ),
                        "transfer_permission": (
                            record.desired_transfer_permission
                        ),
                        "external_call_permission": (
                            record.desired_external_call_permission
                        ),
                        "endpoint_context_key": (
                            record.desired_endpoint_context_key
                        ),
                    }
                    if record
                    else {}
                )
            else:
                raise IntegrationRejected("unsupported aggregate type")
            if not record or not campaign:
                raise IntegrationNotFound("desired state not found")
            _assert_scope(
                claims,
                claims.get("environment", "").upper(),
                campaign.business_unit_id.code,
                campaign.code,
            )
            if "reconciliation_status" in record._fields:
                authoritative_status = record.reconciliation_status
            elif "state" in record._fields:
                authoritative_status = record.state
            elif "active" in record._fields:
                authoritative_status = (
                    "ACTIVE" if record.active else "INACTIVE"
                )
            else:
                authoritative_status = "AVAILABLE"
            document = {
                "exists": True,
                "aggregate_type": kind,
                "aggregate_public_id": public_id,
                "environment": getattr(
                    record,
                    "record_environment",
                    claims.get("environment", "").upper(),
                ),
                "business_unit_public_id": campaign.business_unit_id.code,
                "campaign_public_id": campaign.code,
                "desired_state_version": getattr(
                    record, "desired_state_version", 0
                ),
                "actual_state_version": getattr(
                    record,
                    "actual_state_version",
                    getattr(record, "observed_state_version", 0),
                ),
                "allocation_reservation_public_id": getattr(
                    record, "allocation_reservation_public_id", False
                )
                or None,
                "authoritative_status": authoritative_status,
                "desired_state": desired,
            }
            document["desired_state_hash"] = f"sha256:{_canonical_hash(document)}"
            return _json_response(document)

        return _handle_errors(operation)


class CodestraServiceOperationsController(http.Controller):
    @http.route(
        "/health/live",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def health_live(self):
        return _json_response({"status": "UP", "service_key": "odoo"})

    @http.route(
        "/health/ready",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def health_ready(self):
        def operation():
            _authenticate(b"", "monitor.read")
            request.env.cr.execute("SELECT 1")
            if request.env.cr.fetchone() != (1,):
                raise IntegrationRejected("database readiness rejected")
            return _json_response({"status": "READY", "service_key": "odoo"})

        return _handle_errors(operation)

    @http.route(
        "/.well-known/codestra-service",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def service_attestation(self):
        def operation():
            _authenticate(b"", "service.attest")
            configuration_identity = {
                "environment": os.environ.get(
                    "CODESTRA_ODOO_ENVIRONMENT", "UNCONFIGURED"
                ),
                "release": os.environ.get("CODESTRA_ODOO_RELEASE_ID", "UNCONFIGURED"),
                "source_commit": os.environ.get(
                    "CODESTRA_ODOO_SOURCE_COMMIT", "UNCONFIGURED"
                ),
            }
            return _json_response(
                {
                    "schema_version": "1.0",
                    "service_key": "odoo",
                    "environment": configuration_identity["environment"],
                    "version": "19.0.5.0.0",
                    "configuration_checksum": (
                        f"sha256:{_canonical_hash(configuration_identity)}"
                    ),
                    "source_commit": configuration_identity["source_commit"],
                    "release_id": configuration_identity["release"],
                    "capabilities_endpoint": "/api/v1/integration/capabilities",
                    "issued_at": fields.Datetime.to_string(fields.Datetime.now()),
                }
            )

        return _handle_errors(operation)

    @http.route(
        "/metrics",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def metrics(self):
        try:
            _authenticate(b"", "metrics.read")
            outbox = request.env["codestra.runtime.integration.outbox"].sudo()
            inbox = request.env["codestra.integration.result.inbox"].sudo()
            lines = [
                "# HELP codestra_odoo_outbox_pending Pending integration outbox records.",
                "# TYPE codestra_odoo_outbox_pending gauge",
                (
                    "codestra_odoo_outbox_pending "
                    f"{outbox.search_count([('delivery_state', '=', 'pending')])}"
                ),
                "# HELP codestra_odoo_result_inbox_total Durable integration results.",
                "# TYPE codestra_odoo_result_inbox_total gauge",
                f"codestra_odoo_result_inbox_total {inbox.search_count([])}",
                "",
            ]
            return Response(
                "\n".join(lines),
                status=200,
                content_type="text/plain; version=0.0.4",
            )
        except IntegrationRejected as exc:
            request.env.cr.rollback()
            return _json_response(
                {"status": "REJECTED", "detail": str(exc)}, exc.status
            )
