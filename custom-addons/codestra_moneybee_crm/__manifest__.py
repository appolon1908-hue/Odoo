{
    "name": "Codestra MoneyBee CRM Identity Mapping",
    "version": "19.0.1.2.0",
    "summary": "Tenant-bound, receipted MoneyBee account/contact mapping",
    "license": "LGPL-3",
    "depends": ["base", "contacts", "crm", "codestra_middleware_bridge"],
    "data": [
        "security/moneybee_security.xml",
        "security/ir.model.access.csv",
        "views/res_partner_views.xml",
    ],
    "installable": True,
    "application": False,
}
