{
    "name": "Codestra Contact Center Audit",
    "summary": "Append-only campaign audit evidence and break-glass accountability",
    "version": "19.0.2.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_core",
        "codestra_cc_security",
        "call_center_core",
        "codestra_integration_hub",
    ],
    "data": [
        "security/audit_security.xml",
        "security/ir.model.access.csv",
        "views/audit_views.xml",
    ],
    "installable": True,
    "application": False,
}
