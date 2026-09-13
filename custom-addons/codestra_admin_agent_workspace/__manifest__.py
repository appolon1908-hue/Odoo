{
    "name": "Codestra Agent Workspace and Admin Console",
    "summary": (
        "Native Odoo backend screens for the Agent Workspace and Admin "
        "Console, mirroring the codestra-platform React frontend over the "
        "existing platform/tenant/campaign authorization hierarchy."
    ),
    "version": "19.0.1.0.0",
    "author": "Codestra",
    "license": "LGPL-3",
    "depends": [
        "codestra_identity_provisioning",
        "codestra_agent_onboarding",
        "codestra_cc_crm",
        "codestra_vicidial_crm",
        "codestra_cc_security",
        "mail",
    ],
    "data": [
        "security/workspace_roles.xml",
        "security/ir.model.access.csv",
        "views/agent_workspace_views.xml",
        "views/admin_console_views.xml",
    ],
    "installable": True,
    "application": True,
}
