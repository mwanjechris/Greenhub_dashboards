from datetime import timedelta

from odoo import api, fields, models


class GhKpiSnapshot(models.Model):
    """Point-in-time KPI values, one row per metric, dimension and period end.

    Trend charts read only from here. Rows are upserted, so recomputing a
    period never creates duplicates.
    """

    _name = "gh.kpi.snapshot"
    _description = "Green Hub KPI snapshot"
    _order = "period_end desc, metric_code, dim_key"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    period_type = fields.Selection(
        [("week", "Week"), ("month", "Month"), ("year", "Year")], required=True, index=True
    )
    period_start = fields.Date(required=True)
    period_end = fields.Date(required=True, index=True)
    metric_code = fields.Char(required=True, index=True, help="KPI code from the dashboard spec, e.g. R01.")
    dim_key = fields.Char(
        default="", help="Dimension, e.g. 'product:3' or 'gender:female|age:u35'. Empty = total."
    )
    value_float = fields.Float()
    value_count = fields.Integer()
    computed_at = fields.Datetime(default=fields.Datetime.now, required=True)
    source = fields.Selection(
        [("cron", "Cron"), ("backfill", "Backfill"), ("manual", "Manual")], default="cron", required=True
    )

    _snapshot_uniq = models.Constraint(
        "unique(company_id, period_type, period_end, metric_code, dim_key)",
        "Only one snapshot per company, period, metric and dimension.",
    )

    @api.model
    def _upsert(self, company, period_type, period_start, period_end, rows, source):
        """rows: iterable of (metric_code, dim_key, value_float, value_count)."""
        existing = {
            (s.metric_code, s.dim_key or ""): s
            for s in self.sudo().search([
                ("company_id", "=", company.id),
                ("period_type", "=", period_type),
                ("period_end", "=", period_end),
            ])
        }
        to_create = []
        now = fields.Datetime.now()
        merged = {}
        for code, dim, value_float, value_count in rows:
            merged[(code, dim or "")] = (value_float, value_count)  # last definition wins
        for (code, dim), (value_float, value_count) in merged.items():
            vals = {"value_float": value_float, "value_count": value_count, "computed_at": now, "source": source}
            record = existing.get((code, dim or ""))
            if record:
                record.write(vals)
            else:
                to_create.append(dict(vals, company_id=company.id, period_type=period_type,
                                      period_start=period_start, period_end=period_end,
                                      metric_code=code, dim_key=dim or ""))
        if to_create:
            self.sudo().create(to_create)

    @api.model
    def _cron_weekly_snapshot(self):
        """Snapshot live values on each Sunday (week end) and on the last day of each month.

        Live status is only exact for today, so a late run never back-dates live values;
        missed periods are filled by the backfill wizard instead.
        """
        history = self.env["gh.history.service"]
        for company in self.env["res.company"].search([]):
            today = fields.Date.context_today(self.with_company(company))
            if today.weekday() == 6:
                history.with_company(company)._snapshot_live("week", today)
            if (today + timedelta(days=1)).day == 1:
                history.with_company(company)._snapshot_live("month", today)


RISK_CATEGORIES = [
    ("ahead", "Ahead"), ("ontrack", "On track"), ("norisk", "No risk"), ("low", "Low risk"),
    ("atrisk", "At risk"), ("high", "High risk"), ("critical", "Critical"), ("default", "Default"),
]
PAR_BUCKETS = [("par0", "PAR0"), ("par7", "PAR7"), ("par14", "PAR14"), ("par21", "PAR21"), ("par28", "PAR28")]


class GhContractSnapshot(models.Model):
    """One row per contract per period end: the state the portfolio KPIs are built from."""

    _name = "gh.contract.snapshot"
    _description = "Green Hub contract snapshot"
    _order = "period_end desc, contract_id"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    period_type = fields.Selection([("week", "Week"), ("month", "Month")], required=True, index=True)
    period_end = fields.Date(required=True, index=True)
    contract_id = fields.Many2one("rider.contract", required=True, ondelete="cascade", index=True)
    rider_id = fields.Many2one("rider", index=True)
    bike_id = fields.Many2one("fleet.vehicle")
    product_group_id = fields.Many2one("gh.product.group")
    state = fields.Char()
    payment_state = fields.Char()
    is_active = fields.Boolean(index=True, help="Running or paused at the period end.")
    in_default = fields.Boolean()
    arrears = fields.Float()
    penalties = fields.Float()
    credit = fields.Float()
    instalment = fields.Float()
    dpd = fields.Integer("Days past due")
    risk_category = fields.Selection(RISK_CATEGORIES)
    par_bucket = fields.Selection(PAR_BUCKETS)
    due_in_period = fields.Float()
    collected_in_period = fields.Float(help="Instalment receipts (lease and rental) in the period.")
    source = fields.Selection([("cron", "Cron"), ("backfill", "Backfill"), ("manual", "Manual")], required=True)

    _contract_period_uniq = models.Constraint(
        "unique(company_id, period_type, period_end, contract_id)",
        "One snapshot per contract and period end.",
    )
