import base64
import hashlib
import json
import logging
import secrets
import time
from urllib.parse import urlencode

import requests

from odoo import SUPERUSER_ID, http
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.addons.auth_oauth.controllers.main import OAuthLogin
from odoo.addons.web.controllers.session import Session

_logger = logging.getLogger(__name__)
_STATE_TTL_SECONDS = 600


def _pkce_challenge(verifier):
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class CodestraOrbitSso(http.Controller):
    """Keycloak authorization-code flow with PKCE and no browser token storage."""

    @staticmethod
    def _configuration():
        parameters = request.env["ir.config_parameter"].sudo()
        issuer = parameters.get_param("codestra_orbit_theme.keycloak_issuer", "").rstrip("/")
        client_id = parameters.get_param("codestra_orbit_theme.keycloak_client_id", "")
        if not issuer or not client_id:
            raise AccessDenied("Codestra SSO is not configured")
        provider = request.env.ref("codestra_orbit_theme.provider_codestra_keycloak").sudo()
        if not provider.enabled:
            raise AccessDenied("Codestra SSO is not enabled")
        return issuer, client_id

    @staticmethod
    def _redirect_uri():
        return request.httprequest.url_root.rstrip("/") + "/codestra/sso/callback"

    @staticmethod
    def _safe_redirect(value):
        return value if value and value.startswith("/") and not value.startswith("//") else "/web"

    @http.route("/codestra/sso/login", type="http", auth="none", methods=["GET"], csrf=False)
    def login(self, redirect=None, **_params):
        issuer, client_id = self._configuration()
        nonce = secrets.token_urlsafe(24)
        code_verifier = secrets.token_urlsafe(64)
        state_data = {
            "db": request.db,
            "nonce": nonce,
            "redirect": self._safe_redirect(redirect),
            "timestamp": int(time.time()),
        }
        request.session["codestra_oidc_state"] = json.dumps(
            state_data, separators=(",", ":"), sort_keys=True
        )
        request.session["codestra_oidc_code_verifier"] = code_verifier
        query = urlencode({
            "client_id": client_id,
            "redirect_uri": self._redirect_uri(),
            "response_type": "code",
            "scope": "openid profile email",
            "state": nonce,
            "nonce": nonce,
            "code_challenge": _pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
        })
        return request.redirect(f"{issuer}/protocol/openid-connect/auth?{query}", local=False)

    @http.route("/codestra/sso/callback", type="http", auth="none", methods=["GET"], csrf=False)
    def callback(self, code=None, state=None, error=None, **_params):
        if error or not code or not state:
            return request.redirect("/web/login?oauth_error=1")
        issuer, client_id = self._configuration()
        payload = request.session.pop("codestra_oidc_state", None)
        code_verifier = request.session.pop("codestra_oidc_code_verifier", None)
        if not payload or not code_verifier:
            raise AccessDenied("Invalid SSO state")
        state_data = json.loads(payload)
        if (
            not secrets.compare_digest(state, str(state_data.get("nonce", "")))
            or state_data.get("db") != request.db
            or int(time.time()) - int(state_data.get("timestamp", 0)) > _STATE_TTL_SECONDS
        ):
            raise AccessDenied("Expired SSO state")

        token_response = requests.post(
            f"{issuer}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": self._redirect_uri(),
                "code_verifier": code_verifier,
            },
            timeout=10,
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        access_token = token_payload.get("access_token")
        if not access_token:
            raise AccessDenied("Identity provider returned no access token")
        provider = request.env.ref("codestra_orbit_theme.provider_codestra_keycloak").sudo()
        users = request.env["res.users"].with_user(SUPERUSER_ID).with_context(no_user_creation=True)
        validation = users._auth_oauth_validate(provider.id, access_token)
        login = users._auth_oauth_signin(
            provider.id,
            validation,
            {"access_token": access_token, "state": json.dumps({"d": request.db})},
        )
        if not login:
            raise AccessDenied("Codestra account is not provisioned in Odoo")
        request.env.cr.commit()
        request.session.authenticate(
            request.env,
            {"login": login, "token": access_token, "type": "oauth_token"},
        )
        request.session["codestra_oidc_id_token"] = token_payload.get("id_token")
        _logger.info("Codestra Keycloak login completed for database %s", request.db)
        return request.redirect(self._safe_redirect(state_data.get("redirect")))

    @http.route("/codestra/sso/logout", type="http", auth="user", methods=["POST"], csrf=True)
    def logout(self, **_params):
        issuer, client_id = self._configuration()
        id_token = request.session.pop("codestra_oidc_id_token", None)
        request.session.logout(keep_db=True)
        query_values = {
            "client_id": client_id,
            "post_logout_redirect_uri": request.httprequest.url_root.rstrip("/") + "/web/login?logout=1",
        }
        if id_token:
            query_values["id_token_hint"] = id_token
        return request.redirect(
            f"{issuer}/protocol/openid-connect/logout?{urlencode(query_values)}",
            local=False,
        )


class CodestraOrbitLogin(OAuthLogin):
    @http.route()
    def web_login(self, *args, **kwargs):
        response = super().web_login(*args, **kwargs)
        if response.is_qweb:
            parameters = request.env["ir.config_parameter"].sudo()
            provider = request.env.ref("codestra_orbit_theme.provider_codestra_keycloak").sudo()
            configured = all((
                parameters.get_param("codestra_orbit_theme.keycloak_issuer"),
                parameters.get_param("codestra_orbit_theme.keycloak_client_id"),
            ))
            destination = CodestraOrbitSso._safe_redirect(request.params.get("redirect"))
            response.qcontext["codestra_sso_enabled"] = bool(provider.enabled and configured)
            response.qcontext["codestra_sso_url"] = "/codestra/sso/login?" + urlencode({"redirect": destination})
        return response


class CodestraOrbitSession(Session):
    @http.route()
    def logout(self, redirect="/odoo"):
        id_token = request.session.get("codestra_oidc_id_token")
        if not id_token:
            return super().logout(redirect=redirect)
        try:
            issuer, client_id = CodestraOrbitSso._configuration()
        except AccessDenied:
            return super().logout(redirect=redirect)
        request.session.logout(keep_db=True)
        query = urlencode({
            "client_id": client_id,
            "id_token_hint": id_token,
            "post_logout_redirect_uri": request.httprequest.url_root.rstrip("/") + "/web/login?logout=1",
        })
        return request.redirect(f"{issuer}/protocol/openid-connect/logout?{query}", 303, local=False)
