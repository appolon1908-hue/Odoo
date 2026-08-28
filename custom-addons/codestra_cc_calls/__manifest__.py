{
    "name": "Codestra Contact Center Calls",
    "summary": "Campaign callbacks, appointments, transfers, referrals, and pop-outs",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_crm",
        "codestra_cc_disposition",
        "codestra_appointments",
    ],
    "data": [
        "security/calls_security.xml",
        "security/ir.model.access.csv",
        "data/feature_flags.xml",
        "views/callback_transfer_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "codestra_cc_calls/static/src/js/call_workspace_popouts.js",
            "codestra_cc_calls/static/src/xml/call_workspace_popouts.xml",
        ],
    },
    "installable": True,
    "application": False,
}
