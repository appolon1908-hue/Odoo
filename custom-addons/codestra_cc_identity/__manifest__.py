{
    "name": "Codestra Contact Center Identity",
    "summary": "Fail-closed campaign identity, session, and deprovisioning lifecycle",
    "version": "19.0.2.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_core",
        "codestra_cc_security",
        "codestra_cc_workforce",
        "codestra_identity_provisioning",
        "codestra_cc_audit",
        "web",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "views/identity_views.xml",
    ],
    "installable": True,
    "application": False,
}
