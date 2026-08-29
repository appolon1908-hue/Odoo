{
    "name": "Call Center Compliance",
    "version": "19.0.1.0.0",
    "category": "Sales/CRM",
    "summary": "Consent, DNC, suppression, calling windows, and contact eligibility",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": ["call_center_lead_validation"],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "views/compliance_views.xml",
        "views/lead_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
}
