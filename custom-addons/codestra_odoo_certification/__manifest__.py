{
    "name": "Codestra Odoo VICIdial Certification",
    "version": "19.0.1.0.0",
    "summary": "Default-off deterministic VICIdial CRM mutation certification lane",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": ["call_center_campaign", "codestra_vicidial_crm"],
    "data": [
        "security/ir.model.access.csv",
        "data/test_syn_mapping.xml",
        "data/disposition_mappings.xml",
    ],
    "installable": True,
    "application": False,
}
