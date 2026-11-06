"""Budget, actuals & performance (spec 5.4, B01-B12)."""
from collections import defaultdict
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

from .gh_history import month_ends

# P&L layout: (label, roles, sign for actual (+1 revenue/-1 cost), level, direction)
PL_LINES = [
    ("Revenue", ["revenue_lease", "revenue_rental", "revenue_monitoring", "revenue_other"], 1, 1, "up"),
    ("Lease interest & fees", ["revenue_lease"], 1, 0, "up"),
    ("Rental", ["revenue_rental"], 1, 0, "up"),
    ("Monitoring fees", ["revenue_monitoring"], 1, 0, "up"),
    ("Swap, spare parts & other", ["revenue_other"], 1, 0, "up"),
    ("Cost of sales", ["cost_of_sales"], -1, 1, "down"),
    ("Operating expenses", ["opex_staff", "opex_fleet", "opex_admin", "default_loss"], -1, 1, "down"),
    ("Staff", ["opex_staff"], -1, 0, "down"),
    ("Fleet operations & maintenance", ["opex_fleet"], -1, 0, "down"),
    ("Admin & other", ["opex_admin"], -1, 0, "down"),
    ("Default losses", ["default_loss"], -1, 0, "down"),
]
REVENUE_ROLES = PL_LINES[0][1]
EBITDA_COST_ROLES = ["cost_of_sales", "opex_staff", "opex_fleet", "opex_admin", "default_loss"]
FINANCING_ROLES = ["financing_interest", "financing_fees"]


class GhKpiServiceBudget(models.AbstractModel):
    _inherit = "gh.kpi.service"

    def _role_actual(self, role, date_from, date_to):
        """Revenue roles positive (credit), cost roles positive (debit). None = not mapped."""
        sign = -1 if role.startswith("revenue") else 1
        return self._account_amount(role, date_from, date_to, sign)

    def _roles_actual(self, roles, date_from, date_to):
        values = [self._role_actual(r, date_from, date_to) for r in roles]
        values = [v for v in values if v is not None]
        return sum(values) if values else None

    def _roles_budget(self, version, roles, date_from, date_to):
        Target = self.env["gh.kpi.target"]
        values = [Target._value(version, "PL", date_from, date_to, f"role:{r}") for r in roles]
        values = [v for v in values if v is not None]
        return sum(values) if values else None

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

    @api.model
    def get_budget_dashboard(self, version_id=None, period="ytd", through=False):
        self._check_access()
        on = self._today()
        Version = self.env["gh.kpi.target.version"].sudo()
        versions = Version.search([("company_id", "=", self.env.company.id)])
        version = Version.browse(version_id) if version_id else self._target_version()
        if through:
            through_end = (fields.Date.to_date(through).replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
        else:
            through_end = on.replace(day=1) - timedelta(days=1)
        through_end = min(through_end, on)
        start, end = self._window(period, through_end)
        mapped = {m.role for m in self.env["gh.account.mapping"].sudo().search([("company_id", "=", self.env.company.id)])
                  if m.account_ids}
        month_start = end.replace(day=1)

        def pl():
            lines = []
            for label, roles, _sign, level, direction in PL_LINES:
                actual = self._roles_actual(roles, start, end)
                budget = self._roles_budget(version, roles, start, end) if version else None
                m_actual = self._roles_actual(roles, month_start, end)
                m_budget = self._roles_budget(version, roles, month_start, end) if version else None
                accounts = self.env["account.account"]
                for r in roles:
                    accounts |= self.env["gh.account.mapping"]._accounts(r)
                lines.append({"label": label, "level": level, "actual": actual, "budget": budget,
                              "month_actual": m_actual, "month_budget": m_budget,
                              "variance": self._variance(actual, budget, direction),
                              "mapped": any(r in mapped for r in roles),
                              "domain": [("account_id", "in", accounts.ids), ("parent_state", "=", "posted"),
                                         ("date", ">=", fields.Date.to_string(start)),
                                         ("date", "<=", fields.Date.to_string(end))]})
            rev = lines[0]
            costs = [self._roles_actual([r], start, end) for r in EBITDA_COST_ROLES]
            ebitda = (rev["actual"] - sum(c for c in costs if c is not None)) if rev["actual"] is not None else None
            costs_b = [self._roles_budget(version, [r], start, end) for r in EBITDA_COST_ROLES] if version else []
            ebitda_b = (rev["budget"] - sum(c for c in costs_b if c is not None)) if version and rev["budget"] is not None else None
            m_costs = [self._roles_actual([r], month_start, end) for r in EBITDA_COST_ROLES]
            m_ebitda = (rev["month_actual"] - sum(c for c in m_costs if c is not None)) if rev["month_actual"] is not None else None
            lines.append({"label": "EBITDA", "level": 2, "actual": ebitda, "budget": ebitda_b,
                          "month_actual": m_ebitda, "month_budget": None,
                          "variance": self._variance(ebitda, ebitda_b, "up"), "mapped": bool(mapped), "domain": False})
            expenses = self._roles_actual(EBITDA_COST_ROLES, start, end)
            expenses_b = self._roles_budget(version, EBITDA_COST_ROLES, start, end) if version else None
            financing = self._roles_actual(FINANCING_ROLES, start, end)
            financing_b = self._roles_budget(version, FINANCING_ROLES, start, end) if version else None
            return {"lines": lines, "mapped_roles": sorted(mapped),
                    "tiles": {
                        "revenue": {"actual": rev["actual"], "budget": rev["budget"], "var": rev["variance"]},
                        "expenses": {"actual": expenses, "budget": expenses_b, "var": self._variance(expenses, expenses_b, "down")},
                        "ebitda": {"actual": ebitda, "budget": ebitda_b, "var": self._variance(ebitda, ebitda_b, "up")},
                        "financing": {"actual": financing, "budget": financing_b,
                                      "var": self._variance(financing, financing_b, "down")}}}

        def revenue_by_month():
            out = []
            for m_end in month_ends(date(end.year, 1, 1), end + timedelta(days=31)):
                m_start = m_end.replace(day=1)
                if m_start > end:
                    break
                out.append({"month": m_start.strftime("%b"),
                            "actual": self._roles_actual(REVENUE_ROLES, m_start, min(m_end, end)),
                            "budget": self._roles_budget(version, REVENUE_ROLES, m_start, m_end) if version else None})
            return {"rows": out}

        def operational():
            Target = self.env["gh.kpi.target"]
            rows = []
            portfolio = self._portfolio_core(self.env["gh.history.service"]._live_contract_rows(on))
            active = portfolio["active_contracts"]["value"]
            rows.append({"code": "B07", "label": _("Active rider portfolio"), "basis": "end-date", "actual": active,
                         "plan": Target._point_value(version, "B07", on), "direction": "up", "unit": "count"})
            growth = [g for g in self._growth_rows("week", None, 400, start, end)]
            first = sum(g["first_time"] for g in growth)
            returning = sum(g["returning"] for g in growth)
            rows.append({"code": "B08", "label": _("New rider onboarding (first-time)"), "basis": "sum", "actual": first,
                         "plan": Target._value(version, "B08", start, end), "direction": "up", "unit": "count",
                         "note": _("+ %s returning", returning), "history": bool(growth)})
            fleet = self._fleet(on, None)
            per_group = {r["group_id"]: r for r in fleet["matrix"]["rows"]}
            for group in self.env["gh.product.group"].sudo().search([]):
                cell = next((c for c in per_group.get(group.id, {}).get("cells", []) if c["category"] == "on_contract"), None)
                rows.append({"code": "B09", "label": _("Fleet deployment: %s", group.name), "basis": "end-date",
                             "actual": cell["count"] if cell else 0,
                             "plan": Target._point_value(version, "B09", on, f"group:{group.id}"), "direction": "up",
                             "unit": "count"})
            collected = sum(l.amount for l in self._logs(start, end))
            plan_c = None
            if version:
                parts = [Target._value(version, "C05", start, end, f"category:{k}") for k, _l in
                         self.env["gh.payment.category.rule"]._fields["category"].selection]
                parts = [p for p in parts if p is not None]
                plan_c = sum(parts) if parts else None
            rows.append({"code": "B06", "label": _("Cash collections"), "basis": "sum", "actual": collected,
                         "plan": plan_c, "direction": "up", "unit": "ugx"})
            loss = self._role_actual("default_loss", start, end)
            rows.append({"code": "B10", "label": _("Default loss (loss, not arrears)"), "basis": "sum", "actual": loss,
                         "plan": Target._value(version, "B10", start, end), "direction": "down", "unit": "ugx"})
            for r in rows:
                r["variance"] = self._variance(r["actual"], r["plan"], r["direction"])
            return {"rows": rows}

        def outlook():
            year_end = date(end.year, 12, 31)
            forecast = Version.search([("kind", "=", "forecast"), ("effective_to", ">=", end)], order="id desc", limit=1)
            actual = None
            ytd_actual = self._roles_actual(REVENUE_ROLES, date(end.year, 1, 1), end)
            costs = self._roles_actual(EBITDA_COST_ROLES, date(end.year, 1, 1), end)
            if ytd_actual is not None:
                actual = ytd_actual - (costs or 0.0)
            rest_from = end + timedelta(days=1)
            fc = None
            if forecast and rest_from <= year_end:
                rev = self._roles_budget(forecast, REVENUE_ROLES, rest_from, year_end)
                cost = self._roles_budget(forecast, EBITDA_COST_ROLES, rest_from, year_end)
                fc = (rev or 0.0) - (cost or 0.0) if rev is not None else None
            approved = None
            if version:
                rev = self._roles_budget(version, REVENUE_ROLES, date(end.year, 1, 1), year_end)
                cost = self._roles_budget(version, EBITDA_COST_ROLES, date(end.year, 1, 1), year_end)
                approved = (rev or 0.0) - (cost or 0.0) if rev is not None else None
            return {"actual_ytd": actual, "forecast_rest": fc, "forecast_version": forecast.name if forecast else False,
                    "approved_full_year": approved,
                    "outlook": (actual + fc) if actual is not None and fc is not None else None}

        return {
            "as_of": fields.Date.to_string(on), "computed_at": fields.Datetime.to_string(fields.Datetime.now()),
            "company": self.env.company.name, "currency": self.env.company.currency_id.name,
            "versions": [{"id": v.id, "name": v.name, "kind": v.kind, "state": v.state,
                          "approved_by": v.approved_by.name or False,
                          "approved_on": fields.Datetime.to_string(v.approved_on) if v.approved_on else False,
                          "lines": v.line_count} for v in versions],
            "version": {"id": version.id, "name": version.name, "state": version.state, "kind": version.kind,
                        "approved_by": version.approved_by.name or False,
                        "approved_on": fields.Date.to_string(version.approved_on.date()) if version.approved_on else False,
                        "effective_from": fields.Date.to_string(version.effective_from),
                        "effective_to": fields.Date.to_string(version.effective_to)} if version else False,
            "period": {"key": period, "from": fields.Date.to_string(start), "to": fields.Date.to_string(end)},
            "through_options": [fields.Date.to_string(d.replace(day=1)) for d in
                                month_ends(date(on.year, 1, 1), on)] + [fields.Date.to_string(on.replace(day=1))],
            "pl": self._panel(pl),
            "revenue_by_month": self._panel(revenue_by_month),
            "operational": self._panel(operational),
            "outlook": self._panel(outlook),
            "is_manager": self.env.user.has_group("greenhub_dashboards.group_gh_dashboard_manager"),
        }
