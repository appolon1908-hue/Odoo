{
    "name": "Codestra Agent Onboarding",
    "summary": "Governed agent onboarding, campaign assignment, provisioning, and secure activation",
    "version": "19.0.2.0.2",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "call_center_campaign",
        "codestra_cc_identity",
        "codestra_cc_security",
        "codestra_cc_workforce",
        "codestra_identity_provisioning",
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
