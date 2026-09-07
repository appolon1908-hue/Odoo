from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    codestra_keycloak_issuer = fields.Char(
        string="Keycloak issuer",
        config_parameter="codestra_orbit_theme.keycloak_issuer",
    )
    codestra_keycloak_client_id = fields.Char(
        string="Keycloak client ID",
        config_parameter="codestra_orbit_theme.keycloak_client_id",
    )
    codestra_keycloak_client_secret = fields.Char(
        string="Keycloak client secret",
        config_parameter="codestra_orbit_theme.keycloak_client_secret",
        groups="base.group_system",
    )

    @api.constrains("codestra_keycloak_issuer")
    def _check_codestra_keycloak_issuer(self):
        for settings in self:
            issuer = (settings.codestra_keycloak_issuer or "").rstrip("/")
            parsed = urlparse(issuer)
            if issuer and (parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment):
                raise ValidationError(_("The Keycloak issuer must be an HTTPS realm URL."))

    def set_values(self):
        result = super().set_values()
        issuer = (self.codestra_keycloak_issuer or "").rstrip("/")
        provider = self.env.ref("codestra_orbit_theme.provider_codestra_keycloak")
        provider.write({
            "client_id": self.codestra_keycloak_client_id or False,
            "auth_endpoint": f"{issuer}/protocol/openid-connect/auth" if issuer else provider.auth_endpoint,
            "validation_endpoint": f"{issuer}/protocol/openid-connect/userinfo" if issuer else provider.validation_endpoint,
        })
        return result
