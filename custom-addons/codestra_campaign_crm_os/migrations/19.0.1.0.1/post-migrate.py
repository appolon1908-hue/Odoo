"""Reconcile governed campaign fixtures on upgrades from an installed module."""

from odoo import SUPERUSER_ID, api

from odoo.addons.codestra_campaign_crm_os.hooks import post_init_hook


def migrate(cr, version):
    """Apply the idempotent fixture reconciler that installs use as a hook."""
    del version
    post_init_hook(api.Environment(cr, SUPERUSER_ID, {}))
