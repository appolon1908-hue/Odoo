{
    "name": "Codestra Contact Center Reporting",
    "summary": "Campaign KPI definitions, immutable snapshots, dashboards, and export evidence",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_wfm",
        "codestra_cc_quality",
        "codestra_cc_calls",
        "codestra_cc_mail",
        "codestra_cc_helpdesk",
        "codestra_cc_analytics",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/reporting_security.xml",
        "views/reporting_views.xml",
    ],
    "installable": True,
    "application": False,
}
