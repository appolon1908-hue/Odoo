{
    "name": "Codestra Call Center Orchestration",
    "version": "19.0.1.0.0",
    "summary": "Fail-closed identity, callback, lead import and provisioning orchestration",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "call_center_core",
        "call_center_campaign",
        "call_center_lead_validation",
        "call_center_compliance",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/cron.xml",
        "data/mail_templates.xml",
        "views/orchestration_views.xml",
    ],
    "installable": True,
    "application": False,
}
