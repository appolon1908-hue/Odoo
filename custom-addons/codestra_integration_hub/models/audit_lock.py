from odoo import fields, models


class IntegrationAuditChainLock(models.Model):
    _name = "codestra.integration.audit.chain.lock"
    _description = "Integration Audit Global Chain Lock"
    _log_access = False

    name = fields.Char(required=True, readonly=True)

    _name_unique = models.Constraint(
        "UNIQUE(name)",
        "An integration audit chain lock already exists with this name.",
    )
