{
    "name": "Codestra Contact Center Quality",
    "summary": "Campaign scorecards, sampling, evaluations, calibration, disputes, and coaching",
    "version": "19.0.2.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_cc_recordings",
        "codestra_ai_call_audit",
        "codestra_ai_review",
        "codestra_transcription",
        "codestra_cc_audit",
    ],
    "data": [
        "security/quality_security.xml",
        "security/ir.model.access.csv",
        "views/quality_views.xml",
    ],
    "installable": True,
    "application": False,
}
