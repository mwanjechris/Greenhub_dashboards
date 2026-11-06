"""Budget, actuals & performance (spec 5.4, B01-B12).

Every financial figure is read from Odoo's P&L report engine (gh_accounting.py):
actuals from the report, budgets from Odoo's report budgets. The dashboard does
no ledger maths of its own, so it always agrees with Accounting > Reporting.
Operational plans (riders, fleet, collections) stay in gh.kpi.target.
"""
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

from .gh_history import month_ends

# dashboard tiles: (code, P&L line key, label, direction). EBITDA falls back to Operating Income on Odoo's standard P&L.
FIN_TILES = [("B03", "REV", "Revenue", "up"), ("B04", "GRP", "Gross profit", "up"),
             ("B05", "EBITDA", "EBITDA", "up"), ("B11", "NEP", "Net profit", "up")]


class GhKpiServiceBudget(models.AbstractModel):
    _inherit = "gh.kpi.service"

    @staticmethod
    def _variance(actual, budget, direction):
        if actual is None or budget is None:
            return {"abs": None, "pct": None, "favourable": None}
        diff = actual - budget
        pct = round(100.0 * diff / abs(budget), 1) if budget else None
        return {"abs": diff, "pct": pct, "favourable": diff >= 0 if direction == "up" else diff <= 0}

    def _window(self, period, through):
        month_start = through.replace(day=1)
        if period == "month":
            return month_start, through
        if period == "quarter":
            q_start = date(through.year, 3 * ((through.month - 1) // 3) + 1, 1)
            return q_start, through
        return date(through.year, 1, 1), through

    @staticmethod
    def _line_direction(key):
        return "down" if key in ("COS", "EXP", "OEXP", "ALLOC") else "up"

    @api.model
    def get_budget_dashboard(self, version_id=None, period="ytd", through=False, budget_id=None):
        self._check_access()
        on = self._today()
        config = self.env["gh.dashboard.config"]._get_config()
        Version = self.env["gh.kpi.target.version"].sudo()
        versions = Version.search([("company_id", "=", self.env.company.id)])
        version = Version.browse(version_id) if version_id else self._target_version()
        Budget = self.env["account.report.budget"].sudo()
        budgets = Budget.search([("company_id", "=", self.env.company.id)])
        budget = Budget.browse(budget_id) if budget_id else (config.budget_id or Budget)
        if through:
            through_end = (fields.Date.to_date(through).replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
        else:
            through_end = on.replace(day=1) - timedelta(days=1)
        through_end = min(through_end, on)
        start, end = self._window(period, through_end)
        month_start = end.replace(day=1)
        ds = fields.Date.to_string
        vid = version.id if version else False

        def cell(key, line, date_from, date_to):
            return {"kind": "pl_cell", "args": {"report_line_id": line["line_id"], "date_from": ds(date_from),
                                                "date_to": ds(date_to), "label": line["name"]}}

        def pl_report(date_from, date_to, with_budget=True):
            return {"kind": "report", "args": {"report": "pl", "date_from": ds(date_from), "date_to": ds(date_to),
                                               "budget_id": budget.id if (with_budget and budget) else False}}

        def pl():
            period_lines, report, _o = self._pl_read(start, end, budget or None)
            if not report:
                return {"lines": [], "tiles": [], "report": False}
            month_lines, _r, _o = self._pl_read(month_start, end, budget or None)
            lines = []
            for key, line in sorted(period_lines.items(), key=lambda kv: kv[1]["sequence"]):
                m = month_lines.get(key, {})
                direction = self._line_direction(key)
                lines.append({
                    "key": key, "label": line["name"], "level": 0 if line["level"] == 0 else 1,
                    "total": line["level"] == 0,
                    "actual": line["actual"], "budget": line["budget"],
                    "month_actual": m.get("actual"), "month_budget": m.get("budget"),
                    "variance": self._variance(line["actual"], line["budget"], direction),
                    "drill": cell(key, line, start, end), "month_drill": cell(key, line, month_start, end),
                    "plan_drill": pl_report(start, end), "month_plan_drill": pl_report(month_start, end),
                })
            by_key = {l["key"]: l for l in lines}
            tiles = []
            for code, key, label, direction in FIN_TILES:
                line = by_key.get(key) or (by_key.get("INC") if key == "EBITDA" else None)
                if not line:
                    continue
                tiles.append({"code": code, "label": label if line["key"] == key else line["label"],
                              "actual": line["actual"], "budget": line["budget"],
                              "var": self._variance(line["actual"], line["budget"], direction),
                              "drill": line["drill"], "plan_drill": line["plan_drill"],
                              "fallback": line["key"] != key})
            return {"lines": lines, "tiles": tiles, "report": report.display_name,
                    "has_ebitda": "EBITDA" in by_key, "budget": budget.name if budget else False}

        def revenue_by_month():
            out = []
            for m_end in month_ends(date(end.year, 1, 1), end + timedelta(days=31)):
                m_start = m_end.replace(day=1)
                if m_start > end:
                    break
                lines, _r, _o = self._pl_read(m_start, min(m_end, end), budget or None)
                rev = lines.get("REV")
                if not rev:
                    continue
                out.append({"month": m_start.strftime("%b"), "from": ds(m_start), "to": ds(min(m_end, end)),
                            "actual": rev["actual"], "budget": rev["budget"],
                            "drill": cell("REV", rev, m_start, min(m_end, end)),
                            "plan_drill": pl_report(m_start, m_end)})
            return {"rows": out}

        def operational():
            Target = self.env["gh.kpi.target"]
            rows = []
            portfolio = self._portfolio_core(self.env["gh.history.service"]._live_contract_rows(on))
            active = portfolio["active_contracts"]["value"]
            rows.append({"code": "B07", "label": _("Active rider portfolio"), "basis": "end-date", "actual": active,
                         "plan": Target._point_value(version, "B07", on), "direction": "up", "unit": "count",
                         "drill": {"kind": "contracts", "args": {"keys": ["is_active"], "label": _("Active contracts")}},
                         "plan_drill": {"kind": "targets", "args": {"version_id": vid, "metrics": ["B07"], "point_on": ds(on),
                                                                    "label": _("Active rider portfolio plan")}}})
            growth = [g for g in self._growth_rows("week", None, 400, start, end)]
            first = sum(g["first_time"] for g in growth)
            returning = sum(g["returning"] for g in growth)
            rows.append({"code": "B08", "label": _("New rider onboarding (first-time)"), "basis": "sum", "actual": first,
                         "plan": Target._value(version, "B08", start, end), "direction": "up", "unit": "count",
                         "note": _("+ %s returning", returning), "history": bool(growth),
                         "drill": {"kind": "first_time_range", "args": {"date_from": ds(start), "date_to": ds(end),
                                                                        "label": _("First-time riders")}},
                         "plan_drill": {"kind": "targets", "args": {"version_id": vid, "metrics": ["B08"], "date_from": ds(start),
                                                                    "date_to": ds(end), "label": _("Onboarding plan")}}})
            fleet = self._fleet(on, None)
            per_group = {r["group_id"]: r for r in fleet["matrix"]["rows"]}
            for group in self.env["gh.product.group"].sudo().search([]):
                cell = next((c for c in per_group.get(group.id, {}).get("cells", []) if c["category"] == "on_contract"), None)
                rows.append({"code": "B09", "label": _("Fleet deployment: %s", group.name), "basis": "end-date",
                             "actual": cell["count"] if cell else 0,
                             "plan": Target._point_value(version, "B09", on, f"group:{group.id}"), "direction": "up",
                             "unit": "count",
                             "drill": {"kind": "fleet_cell", "args": {"group_id": group.id, "category": "on_contract",
                                                                      "label": _("On contract: %s", group.name)}},
                             "plan_drill": {"kind": "targets", "args": {"version_id": vid, "metrics": ["B09"], "point_on": ds(on),
                                                                        "dim_keys": [f"group:{group.id}"],
                                                                        "label": _("Fleet deployment plan: %s", group.name)}}})
            collected = sum(l.amount for l in self._logs(start, end))
            plan_c = None
            if version:
                parts = [Target._value(version, "C05", start, end, f"category:{k}") for k, _l in
                         self.env["gh.payment.category.rule"]._fields["category"].selection]
                parts = [p for p in parts if p is not None]
                plan_c = sum(parts) if parts else None
            rows.append({"code": "B06", "label": _("Cash collections"), "basis": "sum", "actual": collected,
                         "plan": plan_c, "direction": "up", "unit": "ugx",
                         "drill": {"kind": "receipts", "args": {"date_from": ds(start), "date_to": ds(end),
                                                                "label": _("Receipts")}},
                         "plan_drill": {"kind": "targets", "args": {"version_id": vid, "metrics": ["C05"], "dim_prefix": "category:",
                                                                    "date_from": ds(start), "date_to": ds(end),
                                                                    "label": _("Collections targets")}}})
            loss_accounts = config.default_loss_account_ids
            loss = self._ledger_sum(loss_accounts, start, end)
            rows.append({"code": "B10", "label": _("Default loss (loss, not arrears)"), "basis": "sum", "actual": loss,
                         "plan": Target._value(version, "B10", start, end), "direction": "down", "unit": "ugx",
                         "drill": {"kind": "ledger", "args": {"account_ids": loss_accounts.ids, "date_from": ds(start),
                                                              "date_to": ds(end), "label": _("Default losses")}},
                         "report": "gl",
                         "plan_drill": {"kind": "targets", "args": {"version_id": vid, "metrics": ["B10"], "date_from": ds(start),
                                                                    "date_to": ds(end), "label": _("Default loss plan")}}})
            for r in rows:
                r["variance"] = self._variance(r["actual"], r["plan"], r["direction"])
            return {"rows": rows}

        def outlook():
            year_start, year_end = date(end.year, 1, 1), date(end.year, 12, 31)
            key = "EBITDA"
            ytd, _r, _o = self._pl_read(year_start, end)
            if key not in ytd:
                key = "INC"
            actual = ytd.get(key, {}).get("actual")
            forecast = config.forecast_budget_id
            rest_from = end + timedelta(days=1)
            fc = None
            if forecast and rest_from <= year_end:
                rest, _r, _o = self._pl_read(rest_from, year_end, forecast)
                fc = rest.get(key, {}).get("budget")
            approved = None
            if budget:
                full, _r, _o = self._pl_read(year_start, year_end, budget)
                approved = full.get(key, {}).get("budget")
            return {"line": ytd.get(key, {}).get("name") or key, "ytd_from": ds(year_start), "ytd_to": ds(end),
                    "actual_ytd_drill": cell(key, ytd[key], year_start, end) if key in ytd else None,
                    "forecast_drill": {"kind": "report", "args": {"report": "pl", "date_from": ds(rest_from),
                                                                  "date_to": ds(year_end), "budget_id": forecast.id}}
                    if forecast else None,
                    "approved_drill": {"kind": "report", "args": {"report": "pl", "date_from": ds(year_start),
                                                                  "date_to": ds(year_end), "budget_id": budget.id}}
                    if budget else None,
                    "actual_ytd": actual, "forecast_rest": fc, "forecast_version": forecast.name if forecast else False,
                    "approved_full_year": approved,
                    "outlook": (actual + fc) if actual is not None and fc is not None else None}

        return {
            "as_of": ds(on), "computed_at": fields.Datetime.to_string(fields.Datetime.now()),
            "company": self.env.company.name, "currency": self.env.company.currency_id.name,
            "budgets": [{"id": b.id, "name": b.name, "items": len(b.item_ids)} for b in budgets],
            "budget": {"id": budget.id, "name": budget.name} if budget else False,
            "versions": [{"id": v.id, "name": v.name, "kind": v.kind, "state": v.state,
                          "approved_by": v.approved_by.name or False,
                          "approved_on": fields.Datetime.to_string(v.approved_on) if v.approved_on else False,
                          "lines": v.line_count} for v in versions],
            "version": {"id": version.id, "name": version.name, "state": version.state, "kind": version.kind}
            if version else False,
            "period": {"key": period, "from": ds(start), "to": ds(end)},
            "through_options": [ds(d.replace(day=1)) for d in month_ends(date(on.year, 1, 1), on)] + [ds(on.replace(day=1))],
            "pl": self._panel(pl),
            "revenue_by_month": self._panel(revenue_by_month),
            "operational": self._panel(operational),
            "outlook": self._panel(outlook),
            "is_manager": self.env.user.has_group("greenhub_dashboards.group_gh_dashboard_manager"),
        }
