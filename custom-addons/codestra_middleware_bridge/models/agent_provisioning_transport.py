"""Approved Middleware transport for the canonical agent-provisioning saga."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import UUID

from odoo import SUPERUSER_ID, api, models
from odoo.exceptions import UserError, ValidationError

AGENT_PROVISIONING_PATH = "/platform/v1/agent-provisioning/requests"
MAX_RESPONSE_BYTES = 262_144


class MiddlewareProvisioningRejected(UserError):
    """Middleware rejected the command before accepting a saga."""


class MiddlewareProvisioningOutcomeUnknown(UserError):
    """The request may have been accepted but its HTTP outcome is unknown."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise MiddlewareProvisioningOutcomeUnknown("Middleware redirects are rejected.")


def _endpoint_url(value):
    parsed = urllib.parse.urlsplit((value or "").strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != AGENT_PROVISIONING_PATH
    ):
        raise ValidationError(
            "Middleware agent provisioning URL must be the credential-free "
            "HTTPS /platform/v1/agent-provisioning/requests endpoint."
        )
    return parsed.geturl()


def _token_url(value):
    parsed = urllib.parse.urlsplit((value or "").strip())
    private_http = parsed.scheme == "http" and parsed.hostname == "keycloak"
    if (
        (parsed.scheme != "https" and not private_http)
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValidationError(
            "Middleware provisioning token URL must use HTTPS or the isolated "
            "Keycloak service alias."
        )
    return parsed.geturl().rstrip("/")


def _protected_value(path_value, label):
    path = Path(path_value or "")
    try:
        mode = path.stat().st_mode
        if (
            not path.is_absolute()
            or path.is_symlink()
            or not path.is_file()
            or mode & 0o077
        ):
            raise OSError
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise ValidationError("%s reference is unavailable or unsafe." % label) from error
    if not value:
        raise ValidationError("%s reference is empty." % label)
    return value


class CodestraMiddlewareAgentProvisioningTransport(models.AbstractModel):
    _name = "codestra.middleware.agent.provisioning.transport"
    _description = "Approved Middleware Agent Provisioning Transport"

    @api.model
    def _configuration(self):
        params = self.env["ir.config_parameter"].with_user(SUPERUSER_ID)
        return {
            "endpoint": _endpoint_url(
                os.getenv("CODESTRA_MIDDLEWARE_AGENT_PROVISIONING_URL")
                or params.get_param("codestra.middleware.agent_provisioning_url")
            ),
            "token_url": _token_url(
                os.getenv("CODESTRA_MIDDLEWARE_AGENT_PROVISIONING_TOKEN_URL")
                or os.getenv("CODESTRA_PROVISIONING_TOKEN_URL")
            ),
            "client_id": (
                os.getenv("CODESTRA_MIDDLEWARE_AGENT_PROVISIONING_CLIENT_ID")
                or os.getenv("CODESTRA_PROVISIONING_CLIENT_ID", "")
            ).strip(),
            "client_secret_file": (
                os.getenv("CODESTRA_MIDDLEWARE_AGENT_PROVISIONING_CLIENT_SECRET_FILE")
                or os.getenv("CODESTRA_PROVISIONING_CLIENT_SECRET_FILE", "")
            ).strip(),
            "ca_file": (
                os.getenv("CODESTRA_MIDDLEWARE_AGENT_PROVISIONING_CA_FILE")
                or os.getenv("CODESTRA_PROVISIONING_CA_FILE", "")
            ).strip(),
            "policy_revision": (
                os.getenv("CODESTRA_MIDDLEWARE_AGENT_PROVISIONING_POLICY_REVISION")
                or params.get_param(
                    "codestra.middleware.agent_provisioning_policy_revision", "1"
                )
            ).strip(),
            "scope": (
                os.getenv(
                    "CODESTRA_MIDDLEWARE_AGENT_PROVISIONING_SCOPE",
                    "identity.request",
                )
                .strip()
            ),
            "audience": (
                os.getenv(
                    "CODESTRA_MIDDLEWARE_AGENT_PROVISIONING_AUDIENCE",
                    "middleware-api",
                )
                .strip()
            ),
        }

    @api.model
    def _open_json(self, outbound, context):
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                _NoRedirect(),
                urllib.request.HTTPSHandler(context=context),
            )
            with opener.open(outbound, timeout=15) as response:  # nosec B310
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise MiddlewareProvisioningRejected(
                        "Middleware provisioning response exceeds the size limit."
                    )
                status = response.status
        except MiddlewareProvisioningOutcomeUnknown:
            raise
        except urllib.error.HTTPError as error:
            if 400 <= error.code < 500 and error.code not in {408, 429}:
                raise MiddlewareProvisioningRejected(
                    "Middleware rejected the agent provisioning command."
                ) from error
            raise MiddlewareProvisioningOutcomeUnknown(
                "Middleware provisioning outcome is unknown; reconcile the request."
            ) from error
        except (OSError, urllib.error.URLError) as error:
            raise MiddlewareProvisioningOutcomeUnknown(
                "Middleware provisioning outcome is unknown; reconcile the request."
            ) from error
        if status not in (200, 201, 202):
            raise MiddlewareProvisioningOutcomeUnknown(
                "Middleware provisioning outcome is unknown; reconcile the request."
            )
        try:
            document = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise MiddlewareProvisioningOutcomeUnknown(
                "Middleware returned an invalid provisioning response."
            ) from error
        if not isinstance(document, dict):
            raise MiddlewareProvisioningOutcomeUnknown(
                "Middleware returned an invalid provisioning response."
            )
        return document

    @api.model
    def _access_token(self, configured, context):
        if not configured["client_id"]:
            raise ValidationError("Middleware provisioning client identity is not configured.")
        secret = _protected_value(
            configured["client_secret_file"], "Middleware provisioning client credential"
        )
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": configured["client_id"],
                "client_secret": secret,
                "audience": configured["audience"],
                "scope": configured["scope"],
            }
        ).encode()
        outbound = urllib.request.Request(
            configured["token_url"],
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        document = self._open_json(outbound, context)
        token = document.get("access_token")
        if not isinstance(token, str) or not token:
            raise MiddlewareProvisioningOutcomeUnknown(
                "Middleware provisioning token response is invalid."
            )
        return token

    @api.model
    def _transport(self, configured):
        ca_file = configured["ca_file"]
        if not ca_file:
            raise ValidationError("Middleware provisioning CA reference is not configured.")
        ca_path = Path(ca_file)
        if (
            not ca_path.is_absolute()
            or ca_path.is_symlink()
            or not ca_path.is_file()
            or ca_path.stat().st_mode & 0o022
        ):
            raise ValidationError("Middleware provisioning CA reference is unsafe.")
        context = ssl.create_default_context(cafile=str(ca_path))
        return context, self._access_token(configured, context)

    @staticmethod
    def _validate_response(response, *, request_id, correlation_id):
        if not isinstance(response, dict):
            raise MiddlewareProvisioningOutcomeUnknown(
                "Middleware returned an invalid provisioning response."
            )
        required = {
            "middleware_request_id",
            "request_id",
            "tenant_id",
            "employee_id",
            "state",
            "correlation_id",
            "version",
            "steps",
        }
        try:
            UUID(str(response["middleware_request_id"]))
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise MiddlewareProvisioningOutcomeUnknown(
                "Middleware returned an invalid provisioning response."
            ) from error
        if (
            not required <= set(response)
            or not isinstance(response["request_id"], str)
            or not response["request_id"]
            or (request_id is not None and response["request_id"] != request_id)
            or response["correlation_id"] != correlation_id
            or not isinstance(response["tenant_id"], str)
            or not isinstance(response["employee_id"], str)
            or isinstance(response["version"], bool)
            or not isinstance(response["version"], int)
            or response["version"] < 1
            or not isinstance(response["steps"], list)
        ):
            raise MiddlewareProvisioningOutcomeUnknown(
                "Middleware returned an invalid provisioning response."
            )
        return response

    @api.model
    def _create_request(self, payload, *, idempotency_key, correlation_id):
        if not isinstance(payload, dict) or not payload.get("request_id"):
            raise ValidationError("Middleware provisioning payload is invalid.")
        if not isinstance(idempotency_key, str) or len(idempotency_key) < 16:
            raise ValidationError("Middleware provisioning idempotency key is invalid.")
        if not isinstance(correlation_id, str) or not correlation_id:
            raise ValidationError("Middleware provisioning correlation ID is invalid.")
        configured = self._configuration()
        context, token = self._transport(configured)
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        outbound = urllib.request.Request(
            configured["endpoint"],
            data=raw,
            method="POST",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Idempotency-Key": idempotency_key,
                "X-Correlation-ID": correlation_id,
                "X-Policy-Revision": configured["policy_revision"],
                "X-Codestra-Request-ID": payload["request_id"],
            },
        )
        response = self._open_json(outbound, context)
        return self._validate_response(
            response,
            request_id=payload["request_id"],
            correlation_id=correlation_id,
        )

    @api.model
    def _reconcile_request(
        self,
        middleware_request_id,
        *,
        correlation_id,
        reason,
        expected_request_id=None,
    ):
        try:
            request_uuid = UUID(str(middleware_request_id))
        except (TypeError, ValueError) as error:
            raise ValidationError("Middleware request ID is invalid.") from error
        if not isinstance(correlation_id, str) or not correlation_id:
            raise ValidationError("Middleware provisioning correlation ID is invalid.")
        if not isinstance(reason, str) or not reason.strip():
            raise ValidationError("Middleware reconciliation reason is required.")
        if expected_request_id is not None and (
            not isinstance(expected_request_id, str) or not expected_request_id
        ):
            raise ValidationError("Middleware request binding is invalid.")
        configured = self._configuration()
        context, token = self._transport(configured)
        endpoint = (
            configured["endpoint"].rsplit(AGENT_PROVISIONING_PATH, 1)[0]
            + AGENT_PROVISIONING_PATH
            + "/"
            + str(request_uuid)
            + "/reconcile"
        )
        raw = json.dumps(
            {"reason": reason[:1000]}, sort_keys=True, separators=(",", ":")
        ).encode()
        outbound = urllib.request.Request(
            endpoint,
            data=raw,
            method="POST",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Correlation-ID": correlation_id,
                "X-Policy-Revision": configured["policy_revision"],
            },
        )
        response = self._open_json(outbound, context)
        return self._validate_response(
            response,
            request_id=expected_request_id,
            correlation_id=correlation_id,
        )
