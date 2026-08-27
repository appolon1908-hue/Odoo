{
    "name": "Codestra Client Portal",
    "summary": "Record-rule-safe client contracts, SLAs, approved usage, revenue, and margin portal",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "portal",
        "website",
        "codestra_client_operations",
        "codestra_revenue_assurance",
        "codestra_cc_analytics",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "views/portal_templates.xml",
    ],
    "installable": True,
    "application": False,
}
