{
    "name": "Codestra Telephony Desired State",
    "version": "19.0.1.2.0",
    "category": "Operations/Telephony",
    "summary": "Odoo-owned telephony desired state and reconciliation projections",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "call_center_campaign",
        "call_center_orchestration",
        "codestra_identity_provisioning",
    ],
    "data": [
        "security/telephony_integration_security.xml",
        "security/ir.model.access.csv",
        "views/telephony_reconciliation_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
