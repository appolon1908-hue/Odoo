{
    "name": "Codestra Interaction Workflow",
    "version": "19.0.1.0.0",
    "category": "Tools/Integration",
    "summary": "Read-only integration operations dashboard and approval requests",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": ["web", "call_center_campaign"],
    "data": [
        "security/ir.model.access.csv",
        "views/activation_request_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "codestra_interaction_workflow/static/src/components/activation_dashboard/activation_dashboard.js",
            "codestra_interaction_workflow/static/src/components/activation_dashboard/activation_dashboard.xml",
            "codestra_interaction_workflow/static/src/components/activation_dashboard/activation_dashboard.scss",
        ],
    },
    "installable": True,
    "application": True,
}
