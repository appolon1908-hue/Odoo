{
    "name": "Codestra Email via Middleware",
    "version": "19.0.1.0.0",
    "summary": "Durable transactional email submission and Klyrow delivery reconciliation",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": ["mail", "codestra_middleware_bridge"],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/cron.xml",
        "views/outbox.xml",
    ],
    "installable": True,
    "application": False,
}

