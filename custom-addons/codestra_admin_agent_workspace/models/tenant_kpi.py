from odoo import api, fields, models

# Same "operational membership" role set already used as the assignment
# gate in codestra_cc_crm's crm_workspace.py constraints
# (_check_assignment/_check_cc_campaign_scope) - kept identical here rather
# than re-deriving a second, possibly-drifting definition of "an agent".
ACTIVE_AGENT_ROLES = ("agent", "senior_agent", "supervisor")


class CodestraTenantWorkspaceKpi(models.Model):
    """Admin Console KPI tiles for codestra.tenant.

    Deliberately does not add a tenant_id link from cc.campaign to
    codestra.tenant - no such link exists yet anywhere in this codebase
    (codestra.tenant is the SaaS billing/identity boundary,
    cc.business.unit/cc.campaign is the call-center org boundary; see
    codestra.tenant's own docstring). The only real bridge between the two
    today is cc.campaign.membership.platform_user_id (-> tenant) alongside
    the same row's campaign_id, so KPIs here are computed through that
    membership table rather than inventing a new field on a governed model.
    Tenant scoping (platform_admin/operator see all, tenant_admin sees only
    their own) is NOT reimplemented here - it already exists as
    rule_tenant_scope in codestra_identity_provisioning, which this model
    inherits automatically since it is the same codestra.tenant recordset.
    """

    _inherit = "codestra.tenant"

    workspace_platform_user_count = fields.Integer(
        compute="_compute_workspace_kpis",
        string="Platform Users",
    )
    workspace_active_agent_count = fields.Integer(
        compute="_compute_workspace_kpis",
        string="Active Agents",
        help="Distinct platform users in this tenant with at least one "
        "active agent/senior_agent/supervisor campaign membership.",
    )
    workspace_campaign_count = fields.Integer(
        compute="_compute_workspace_kpis",
        string="Campaigns",
        help="Distinct campaigns reachable through this tenant's platform "
        "users' campaign memberships.",
    )
    workspace_drift_count = fields.Integer(
        compute="_compute_workspace_kpis",
        string="Provisioning Drift",
        help="Platform users in this tenant whose "
        "provisioning_drift_status (codestra_agent_onboarding) is 'drift'.",
    )

    @api.depends(
        "platform_user_ids",
        "platform_user_ids.provisioning_drift_status",
        "platform_user_ids.membership_ids.role",
        "platform_user_ids.membership_ids.state",
        "platform_user_ids.membership_ids.campaign_id",
    )
    def _compute_workspace_kpis(self):
        self.check_access("read")
        Membership = self.env["cc.campaign.membership"].sudo()
        for tenant in self:
            users = tenant.sudo().platform_user_ids
            tenant.workspace_platform_user_count = len(users)
            tenant.workspace_drift_count = len(
                users.filtered(lambda u: u.provisioning_drift_status == "drift")
            )
            if not users:
                tenant.workspace_active_agent_count = 0
                tenant.workspace_campaign_count = 0
                continue
            memberships = Membership.search(
                [
                    ("platform_user_id", "in", users.ids),
                    ("role", "in", ACTIVE_AGENT_ROLES),
                    ("state", "=", "active"),
                ]
            )
            tenant.workspace_active_agent_count = len(
                set(memberships.mapped("platform_user_id").ids)
            )
            tenant.workspace_campaign_count = len(
                set(memberships.mapped("campaign_id").ids)
            )
