# ruff: noqa: B018
{
    "name": "Codestra Lead Automation",
    "version": "19.0.2.0.0",
    "category": "CRM",
    "summary": "Default-off, policy-bound lead automation application API",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "crm",
        "call_center_compliance",
        "call_center_orchestration",
        "codestra_telephony_bridge",
    ],
    "data": [
        "security/lead_automation_security.xml",
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/nonce_cron.xml",
        "views/lead_automation_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
