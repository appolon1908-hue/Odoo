{
    "name": "Codestra Kyqra Review Hub",
    "summary": "Review-only Odoo projection of canonical Kyqra crawler results",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "category": "Services/Integration",
    "license": "LGPL-3",
    "depends": ["base", "mail"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "views/kyqra_review_views.xml",
    ],
    "installable": True,
    "application": True,
}
