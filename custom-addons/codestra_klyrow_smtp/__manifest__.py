{
    "name": "Codestra Klyrow SMTP Routing",
    "summary": "Fail-closed Klyrow SMTP routing and domain reconciliation for Odoo",
    "version": "19.0.1.0.0",
    "category": "Productivity/Discuss",
    "license": "LGPL-3",
    "author": "Codestra",
    "depends": ["base", "mail", "codestra_mail_inbox"],
    "data": [
        "security/ir.model.access.csv",
        "data/outgoing_mail_server_data.xml",
        "data/routing_policy_data.xml",
        "views/mail_routing_views.xml",
        "views/ir_mail_server_views.xml",
    ],
    "application": False,
    "installable": True,
}
