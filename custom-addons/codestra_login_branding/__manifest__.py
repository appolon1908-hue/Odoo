{
    "name": "Codestra Login Branding",
    "summary": "Secure, responsive Codestra branding for Odoo authentication pages",
    "version": "19.0.1.0.1",
    "category": "Administration",
    "author": "Codestra",
    "website": "https://codestra.co",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": [
        "views/login_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "codestra_login_branding/static/src/css/login.css",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
