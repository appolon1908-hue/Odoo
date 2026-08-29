{
    "name": "Codestra Data Quality",
    "summary": "Normalization, duplicate, conflict, and incomplete-record review queues",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_core",
        "call_center_lead_validation",
        "codestra_lead_ingestion",
        "codestra_cc_audit",
        "crm",
        "contacts",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/sequence.xml",
        "views/data_quality_views.xml",
    ],
    "installable": True,
    "application": True,
}
