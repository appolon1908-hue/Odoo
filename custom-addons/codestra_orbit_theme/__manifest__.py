{
    "name": "Codestra Orbit Theme and SSO",
    "summary": "Supported Codestra shell and Keycloak OIDC for Odoo",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "website": "https://codestra.agency",
    "license": "LGPL-3",
    "depends": ["auth_oauth", "portal", "website", "web"],
    "data": [
        "security/ir.model.access.csv",
        "data/oauth_provider.xml",
        "views/res_config_settings_views.xml",
        "views/login_templates.xml",
        "views/website_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "codestra_orbit_theme/static/src/css/tokens.css",
            "codestra_orbit_theme/static/src/css/frontend.css",
        ],
        "web.assets_backend": [
            "codestra_orbit_theme/static/src/css/backend_tokens.css",
            "codestra_orbit_theme/static/src/css/backend.css",
            "codestra_orbit_theme/static/src/js/session_expired.js",
        ],
        "web.assets_tests": [
            "codestra_orbit_theme/static/tests/session_expired.test.js",
        ],
    },
    "installable": True,
    "application": False,
}
