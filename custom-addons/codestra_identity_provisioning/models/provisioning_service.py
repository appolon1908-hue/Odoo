import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from odoo import api, models
from odoo.exceptions import UserError


def _https_url(value, label):
    parsed = urllib.parse.urlsplit(value or "")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise UserError("%s must be a credential-free HTTPS URL." % label)
    return value.rstrip("/")


def _token_url(value):
    parsed = urllib.parse.urlsplit(value or "")
    private_http = parsed.scheme == "http" and parsed.hostname == "keycloak"
    if (
        (parsed.scheme != "https" and not private_http)
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise UserError(
            "Provisioning token URL must use HTTPS or the isolated Keycloak "
            "service alias."
        )
    return value.rstrip("/")


def _protected_value(path_value, label):
    path = Path(path_value or "")
    try:
        mode = path.stat().st_mode
        if path.is_symlink() or not path.is_file() or mode & 0o027:
            raise OSError
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise UserError("%s reference is unavailable or unsafe." % label) from error
    if not value:
        raise UserError("%s reference is empty." % label)
    return value


class PrivateProvisioningService(models.AbstractModel):
    _name = "codestra.private.provisioning.service"
    _description = "Private Provisioning Service Contract Client"

    @api.model
    def _configuration(self):
        return {
            "base_url": _https_url(
                os.getenv("CODESTRA_PROVISIONING_URL"),
                "Provisioning service URL",
            ),
            "token_url": _token_url(
                os.getenv("CODESTRA_PROVISIONING_TOKEN_URL")
            ),
            "client_id": os.getenv("CODESTRA_PROVISIONING_CLIENT_ID", "").strip(),
            "client_secret_file": os.getenv(
                "CODESTRA_PROVISIONING_CLIENT_SECRET_FILE", ""
            ),
            "ca_file": os.getenv("CODESTRA_PROVISIONING_CA_FILE", "").strip(),
        }

    @api.model
    def _open_json(self, request, context):
        try:
            # Callers supply only URLs accepted by _https_url or _token_url.
            with urllib.request.urlopen(  # nosec B310
                request, context=context, timeout=15
            ) as response:
                if response.status not in (200, 201, 202):
                    raise UserError(
                        "Private provisioning service rejected the request."
                    )
                document = json.loads(response.read(262144))
        except (
            OSError,
            ValueError,
            urllib.error.HTTPError,
            urllib.error.URLError,
        ) as error:
            raise UserError(
                "Private provisioning service is unavailable; inspect protected logs."
            ) from error
        if not isinstance(document, dict):
            raise UserError("Private provisioning service returned an invalid response.")
        return document

    @api.model
    def _access_token(self, configured, context):
        client_id = configured["client_id"]
        if not client_id:
            raise UserError("Provisioning service client identity is not configured.")
        secret = _protected_value(
            configured["client_secret_file"],
            "Provisioning client credential",
        )
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
        }).encode()
        request = urllib.request.Request(
            configured["token_url"],
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        document = self._open_json(request, context)
        token = document.get("access_token")
        if not isinstance(token, str) or not token:
            raise UserError("Provisioning service token response is invalid.")
        return token

    @api.model
    def request(self, method, path, payload):
        if method not in ("GET", "POST"):
            raise UserError("Unsupported provisioning service method.")
        if not isinstance(path, str) or not path.startswith("/") or ".." in path:
            raise UserError("Invalid provisioning service path.")
        configured = self._configuration()
        ca_file = configured["ca_file"]
        if not ca_file:
            raise UserError("Provisioning service CA reference is not configured.")
        context = ssl.create_default_context(cafile=ca_file)
        token = self._access_token(configured, context)
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode()
        request = urllib.request.Request(
            configured["base_url"] + path,
            data=raw,
            method=method,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        return self._open_json(request, context)
