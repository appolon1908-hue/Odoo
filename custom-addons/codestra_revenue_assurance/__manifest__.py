{
    "name": "Codestra Revenue Assurance",
    "summary": "Versioned rate plans, billable usage, provider cost, revenue, margin, and invoice linkage",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_client_operations",
        "codestra_cc_reliability",
        "call_center_campaign",
        "account",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/sequence.xml",
        "views/revenue_views.xml",
    ],
    "installable": True,
    "application": True,
}
