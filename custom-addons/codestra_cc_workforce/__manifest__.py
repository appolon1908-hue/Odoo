{
    "name": "Codestra Contact Center Workforce",
    "summary": "Agent schedules, attendance linkage, adherence, and staffing controls",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_core",
        "codestra_cc_vicidial",
        "hr",
        "hr_attendance",
        "resource",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/record_rules.xml",
        "data/sequence.xml",
        "views/shift_views.xml",
    ],
    "installable": True,
    "application": True,
}
