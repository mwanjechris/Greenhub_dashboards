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
