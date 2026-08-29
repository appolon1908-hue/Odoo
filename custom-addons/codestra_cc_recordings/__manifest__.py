{
    "name": "Codestra Contact Center Recordings",
    "summary": "Canonical campaign recording policy, binding, retention, and access evidence",
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_calls",
        "codestra_cc_vicidial",
        "codestra_vicidial_recording",
    ],
    "data": [
        "security/recording_security.xml",
        "security/ir.model.access.csv",
        "data/feature_flags.xml",
        "views/recording_views.xml",
    ],
    "installable": True,
    "application": False,
}
