"""Upgrades from 19.0.1.0.x get the same P&L variant a fresh install gets (see post_init_hook)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["gh.dashboard.config"]._ensure_pl_variant_all_companies()
