{
    "name": "Codestra Client Operations",
    "summary": "Versioned client contracts, authorized contacts, campaign onboarding, and SLAs",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_core",
        "codestra_cc_campaign",
        "codestra_case_management",
        "call_center_campaign",
        "contacts",
        "mail",
    ],
    "data": [
        "security/groups.xml",
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/sequence.xml",
        "views/client_contract_views.xml",
    ],
    "installable": True,
    "application": True,
}
