{
    "name": "Codestra Klyrow SMTP Routing",
    "summary": "Fail-closed Klyrow SMTP routing with CRM Email Center",
    "version": "19.0.1.0.0",
    "category": "Sales/CRM",
    "license": "LGPL-3",
    "author": "Codestra",
    "depends": [
        "base",
        "mail",
        "crm",
        "codestra_mail_inbox",
        "codestra_cc_mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/outgoing_mail_server_data.xml",
        "data/routing_policy_data.xml",
        "views/mail_routing_views.xml",
        "views/ir_mail_server_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "codestra_klyrow_smtp/static/src/js/crm_email_center_popout.js",
            "codestra_klyrow_smtp/static/src/xml/crm_email_center_popout.xml",
            "codestra_klyrow_smtp/static/src/css/crm_email_center_popout.css",
        ],
    },
    "application": False,
    "installable": True,
}
