{
    "name": "Codestra Contact Center Campaign Mail",
    "summary": "Fail-closed campaign aliases, distribution, quarantine, and chatter",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_identity",
        "codestra_mail_inbox",
        "mail",
    ],
    "data": [
        "security/mail_security.xml",
        "security/ir.model.access.csv",
        "data/mail_defaults.xml",
        "views/campaign_mail_views.xml",
    ],
    "installable": True,
    "application": False,
}
