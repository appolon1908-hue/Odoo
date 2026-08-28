{
    "name": "Codestra Contact Center Core",
    "summary": "Canonical campaign workspaces over the audited Codestra foundation",
    "version": "19.0.2.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "call_center_core",
        "codestra_interaction_workflow",
        "codestra_vicidial_crm",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/core_domain_views.xml",
        "adopt_legacy_records.xml",
    ],
    "installable": True,
    "application": False,
}
