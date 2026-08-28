from odoo import SUPERUSER_ID, api

from odoo.addons.codestra_campaign_crm_os.hooks import post_init_hook


def migrate(cr, version):
    post_init_hook(api.Environment(cr, SUPERUSER_ID, {}))
