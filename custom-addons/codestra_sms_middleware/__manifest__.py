{
    "name": "Codestra SMS via Middleware",
    "version": "19.0.1.0.0",
    "summary": "Durable CRM SMS submission and Telnexa delivery reconciliation",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": ["crm_sms", "codestra_middleware_bridge", "codestra_campaign_crm_os"],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/cron.xml",
        "views/outbox.xml",
    ],
    "installable": True,
    "application": False,
}
