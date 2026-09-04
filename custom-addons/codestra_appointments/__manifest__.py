{
    "name": "Codestra Appointments",
    "summary": "Governed appointment, callback, reminder, and scheduler lifecycle",
    "version": "19.0.3.2.2",
    "license": "LGPL-3",
    "depends": [
        "call_center_orchestration",
        "codestra_vicidial_crm",
        "codestra",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/callback_rules.xml",
        "data/callback_cron.xml",
        "views/appointment_views.xml",
        "views/callback_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "codestra_appointments/static/src/js/appointment_popouts.js",
            "codestra_appointments/static/src/xml/appointment_popouts.xml",
            "codestra_appointments/static/src/css/appointment_popouts.css",
        ],
    },
    "installable": True,
    "application": False,
}
