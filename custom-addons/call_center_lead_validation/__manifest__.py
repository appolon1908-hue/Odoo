{
    "name": "Call Center Lead Validation",
    "version": "19.0.1.1.0",
    "category": "Sales/CRM",
    "summary": "Lead normalization, validation, deduplication, and routing",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": ["call_center_campaign", "phone_validation"],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "views/lead_views.xml",
        "views/duplicate_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
}
