{
    "name": "Codestra Case Management",
    "summary": "Company-scoped complaints, disputes, refunds, incidents, and executive escalations",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_core",
        "codestra_cc_campaign",
        "codestra_cc_compliance",
        "codestra_cc_audit",
        "mail",
        "crm",
        "contacts",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/sequence.xml",
        "views/case_views.xml",
    ],
    "installable": True,
    "application": True,
}
