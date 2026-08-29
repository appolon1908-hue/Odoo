{
    "name": "Codestra Contact Center Workforce Management",
    "summary": "Campaign forecasts, schedules, adherence, exceptions, and real-time capacity",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_security",
        "codestra_cc_calls",
        "codestra_cc_quality",
        "codestra_cc_vicidial",
        "codestra_cc_workforce",
    ],
    "data": [
        "security/groups.xml",
        "security/ir.model.access.csv",
        "security/workforce_security.xml",
        "views/workforce_views.xml",
    ],
    "installable": True,
    "application": False,
}
