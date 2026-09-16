{
    "name": "Codestra Agent Onboarding",
    "summary": (
        "Governed agent onboarding, campaign assignment, provisioning, "
        "and secure activation"
    ),
    "version": "19.0.2.0.9",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "call_center_campaign",
        "codestra_cc_identity",
        "codestra_cc_security",
        "codestra_cc_workforce",
        "codestra_identity_provisioning",
        "codestra_middleware_bridge",
        "hr",
        "mail",
    ],
    "data": [
        "security/record_rules.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/onboarding_views.xml",
        "views/platform_user_dashboard_views.xml",
    ],
    "installable": True,
    "application": True,
}
