from . import models


def post_init_hook(env):
    """On installation: create the "GreenHub P&L (EBITDA)" variant of Odoo's P&L for every company.

    The variant lives in Accounting > Reporting > Profit and Loss (variant selector). Its EBITDA line is
    Operating Income + the depreciation / amortisation accounts charged above it, suggested by account
    name and editable in Dashboard settings. Odoo computes it; the Budget dashboard reads it.
    """
    env["gh.dashboard.config"]._ensure_pl_variant_all_companies()
