from odoo import SUPERUSER_ID, api


ROLE_TEMPLATES = {
    "AGENT": {},
    "CLOSER": {},
    "SUPERVISOR": {"allows_monitoring": True},
    "QA_REVIEWER": {"allows_recordings": True, "requires_compliance_approval": True},
    "CAMPAIGN_MANAGER": {"requires_compliance_approval": True},
    "COMPLIANCE": {"allows_recordings": True, "requires_compliance_approval": True},
    "AUDITOR": {"allows_recordings": True, "requires_security_approval": True},
    "SYSTEM_ADMIN": {"requires_security_approval": True},
    "INTEGRATION_SERVICE": {"requires_security_approval": True},
}


def post_init_hook(env):
    """Seed scoped templates and grant the built-in administrator menu access."""
    if not isinstance(env, api.Environment):
        env = api.Environment(env, SUPERUSER_ID, {})
    security_admin_group = env.ref(
        "codestra_identity_provisioning.group_provisioning_security_admin"
    )
    administrator = env.ref("base.user_admin", raise_if_not_found=False)
    if administrator:
        administrator.group_ids = [(4, security_admin_group.id)]

    model = env["codestra.role.template"].with_context(
        tracking_disable=True, mail_create_nolog=True
    )
    for unit in env["call.center.business.unit"].search([]):
        for code, policy in ROLE_TEMPLATES.items():
            if not model.search_count([
                ("business_unit_id", "=", unit.id),
                ("code", "=", code),
                ("version", "=", 1),
            ]):
                model.create({
                    "name": code.replace("_", " ").title(),
                    "code": code,
                    "business_unit_id": unit.id,
                    "company_id": unit.company_id.id,
                    **policy,
                })
