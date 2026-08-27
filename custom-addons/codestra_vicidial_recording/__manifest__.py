{
    "name": "Codestra VICIdial Recording Reference",
    "version": "19.0.1.0.0",
    "summary": "Metadata-only VICIdial recording references and scoped playback",
    "author": "Codestra",
    "license": "LGPL-3",
    "category": "Operations/Call Center",
    "installable": True,
    "application": True,
    "depends": ["base", "web", "codestra_vicidial_crm"],
    "data": [
        "security/recording_security.xml",
        "security/ir.model.access.csv",
        "security/recording_rules.xml",
        "views/recording_views.xml",
        "views/call_campaign_views.xml",
        "views/recording_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "codestra_vicidial_recording/static/src/js/playback_action.js"
        ]
    },
}
