{
    "name": "Codestra Agent Onboarding",
    "summary": "Hiring, evidence, equipment, access approval, activation, and offboarding gates",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_identity",
        "codestra_cc_workforce",
        "hr",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/sequence.xml",
        "views/onboarding_views.xml",
    ],
    "installable": True,
    "application": True,
}
