{
    "name": "Codestra Contact Center Disposition",
    "summary": "Governed campaign scripts and disposition-set adoption",
    "version": "19.0.2.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_campaign",
        "codestra_cc_identity",
        "codestra_cc_vicidial",
        "call_center_campaign",
        "codestra_vicidial_crm",
    ],
    "data": [
        "security/disposition_security.xml",
        "security/ir.model.access.csv",
        "views/script_disposition_views.xml",
    ],
    "installable": True,
    "application": False,
}
