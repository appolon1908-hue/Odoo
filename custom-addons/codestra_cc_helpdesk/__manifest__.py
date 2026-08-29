{
    "name": "Codestra Contact Center Helpdesk",
    "summary": "Campaign queues, governed SLAs, tickets, and escalations",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_crm",
        "codestra_cc_mail",
        "mail",
    ],
    "data": [
        "security/helpdesk_security.xml",
        "security/ir.model.access.csv",
        "data/helpdesk_sequence.xml",
        "views/helpdesk_views.xml",
    ],
    "installable": True,
    "application": True,
}
