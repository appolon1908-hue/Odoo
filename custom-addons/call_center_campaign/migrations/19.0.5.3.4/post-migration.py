from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Preserve immutable legacy previews and enqueue revision-bound successors."""
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["codestra.runtime.integration.outbox"]._supersede_legacy_design_requests()
