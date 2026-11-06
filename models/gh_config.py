from odoo import api, fields, models


class GhDashboardConfig(models.Model):
    """One configuration record per company.

    Every threshold the dashboards use lives here (or in the mapping models),
    never in code, so Green Hub can change a definition without a release.
    """

    _name = "gh.dashboard.config"
    _description = "Green Hub dashboard configuration"
    _rec_name = "company_id"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, ondelete="cascade"
    )
    history_start = fields.Date(
        default=fields.Date.to_date("2026-03-01"),
        required=True,
        help="First week end that snapshots and the history backfill cover.",
    )
    youth_age_limit = fields.Integer(
        default=35, required=True, help="Riders younger than this at the as-of date count as youth."
    )
    licence_notice_days = fields.Integer(
        default=30, required=True, help="Licences ending within this many days count as expiring."
    )
    accident_window_days = fields.Integer(
        default=30, required=True, help="Look-back window for the accidents tile."
    )
    referral_window_weeks = fields.Integer(
        default=26, required=True, help="Look-back window for the referral-sources table."
    )
    exclude_test_vehicles = fields.Boolean(
        default=True,
        help="Leave vehicles in the 'test' category out of the fleet denominator.",
    )

    # ---- Portfolio & credit risk (spec 4.3) ----
    risk_band_basis = fields.Selection(
        [("instalments", "Multiples of the contract's weekly instalment"), ("ugx", "Fixed UGX amounts")],
        default="instalments", required=True,
        help="Instalment multiples reproduce today's UGX bands for a Zembo contract (78,940 a week) and scale "
             "for iQube/NIU. Four decimals: the brief's rounded 0.38 / 0.95 put 30,000 and 75,000 in the wrong band.",
    )
    band_ontrack = fields.Float("On track up to", default=0.1267, digits=(16, 4))
    band_norisk = fields.Float("No risk up to", default=0.3801, digits=(16, 4))
    band_low = fields.Float("Low risk up to", default=0.9501, digits=(16, 4))
    band_atrisk = fields.Float("At risk up to", default=1.2668, digits=(16, 4))
    band_high = fields.Float("High risk up to", default=2.0269, digits=(16, 4),
                             help="Above this (and not in default) a contract is Critical.")
    band_ugx_ontrack = fields.Float("On track up to (UGX)", default=10000)
    band_ugx_norisk = fields.Float("No risk up to (UGX)", default=30000)
    band_ugx_low = fields.Float("Low risk up to (UGX)", default=75000)
    band_ugx_atrisk = fields.Float("At risk up to (UGX)", default=100000)
    band_ugx_high = fields.Float("High risk up to (UGX)", default=160000)
    par_1 = fields.Integer("PAR7 up to DPD", default=7)
    par_2 = fields.Integer("PAR14 up to DPD", default=14)
    par_3 = fields.Integer("PAR21 up to DPD", default=21)
    default_scope = fields.Selection(
        [("episode", "Running/paused in default, plus terminated after a default and not yet written off"),
         ("payment_state", "Only running/paused contracts whose payment status is Default")],
        default="episode", required=True,
        help="What 'currently in default' covers. Green Hub to confirm (brief section 10).",
    )
    # ---- Collections (spec 5.3) ----
    forecast_weeks = fields.Integer(default=12, required=True)
    rate_window_weeks = fields.Integer(
        "Trailing weeks for expected rates", default=12, required=True,
        help="Risk-adjusted forecast applies each risk category's collected/due rate over this window.",
    )
    fx_currency_id = fields.Many2one("res.currency", string="Lender currency",
                                     default=lambda self: self.env.ref("base.USD", raise_if_not_found=False))

    def _band_limits(self):
        """Upper limits for no-risk .. high, in the configured basis."""
        self.ensure_one()
        if self.risk_band_basis == "ugx":
            return [self.band_ugx_ontrack, self.band_ugx_norisk, self.band_ugx_low, self.band_ugx_atrisk, self.band_ugx_high]
        return [self.band_ontrack, self.band_norisk, self.band_low, self.band_atrisk, self.band_high]

    _company_uniq = models.Constraint(
        "unique(company_id)", "There is already a dashboard configuration for this company."
    )

    @api.model
    def _get_config(self, company=None):
        company = company or self.env.company
        config = self.sudo().search([("company_id", "=", company.id)], limit=1)
        if not config:
            config = self.sudo().create({"company_id": company.id})
        return config
