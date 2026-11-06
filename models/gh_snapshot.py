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
        for code, dim, value_float, value_count in rows:
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
        """Snapshot the live KPIs for the ISO week that ends today or ended last Sunday."""
        service = self.env["gh.kpi.service"]
        for company in self.env["res.company"].search([]):
            today = fields.Date.context_today(self.with_company(company))
            week_end = today + timedelta(days=(6 - today.weekday())) if today.weekday() == 6 else \
                today - timedelta(days=today.weekday() + 1)
            # Live status is only exact for today, so a late run never back-dates live values.
            if week_end != today:
                continue
            rows = service.with_company(company)._riders_snapshot_rows(week_end)
            self._upsert(company, "week", week_end - timedelta(days=6), week_end, rows, "cron")
