{
    "name": "Codestra Middleware Bridge",
    "version": "19.0.2.0.1",
    "summary": "Authenticated, idempotent Odoo middleware service API",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "contacts",
        "crm",
        "mail",
        "call_center_compliance",
        "codestra_integration_hub",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/crm_stages.xml",
    ],
    "installable": True,
    "application": False,
}
