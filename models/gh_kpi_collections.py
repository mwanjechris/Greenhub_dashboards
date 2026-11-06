"""Collections & Payments KPIs (spec 5.3, C01-C17). Cash received, never called revenue."""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

from .gh_history import ACTIVE_STATES, OPEN_SCHEDULE_STATES, RISK_ORDER, month_ends, week_ends
from .gh_mapping import INSTALMENT_CATEGORIES, PAYMENT_CATEGORIES


class GhKpiServiceCollections(models.AbstractModel):
    _inherit = "gh.kpi.service"

    def _period(self, period, date_from, date_to, on):
        if period == "last_month":
            start = (on.replace(day=1) - relativedelta(months=1))
            return start, on.replace(day=1) - timedelta(days=1)
        if period == "custom" and date_from and date_to:
            return fields.Date.to_date(date_from), min(fields.Date.to_date(date_to), on)
        return on.replace(day=1), on

    def _logs(self, date_from, date_to, product_group_id=None):
        logs = self.env["payment.log"].sudo().search([
            ("status", "=", "success"), ("payment_type", "!=", "outbound"),
            ("attempt_date", ">=", datetime.combine(date_from, time.min)),
            ("attempt_date", "<=", datetime.combine(date_to, time.max))])
        if product_group_id:
            by_product, _m, _g = self.env["gh.product.group"]._group_maps()
            logs = logs.filtered(lambda l: l.contract_id and by_product.get(l.contract_id.product_product_id.id)
                                 and by_product[l.contract_id.product_product_id.id].id == product_group_id)
        return logs

    def _by_category(self, logs):
        classify = self.env["gh.payment.category.rule"]._classifier()
        amounts, ids = defaultdict(float), defaultdict(list)
        for log in logs:
            cat = classify(log)
            amounts[cat] += log.amount
            ids[cat].append(log.id)
        return amounts, ids

    def _contracts_of_group(self, product_group_id, domain):
        contracts = self.env["rider.contract"].sudo().search(domain)
        if product_group_id:
            by_product, _m, _g = self.env["gh.product.group"]._group_maps()
            contracts = contracts.filtered(lambda c: by_product.get(c.product_product_id.id)
                                           and by_product[c.product_product_id.id].id == product_group_id)
        return contracts

    def _due(self, date_from, date_to, contracts, lease_only=False):
        domain = [("due_date", ">=", date_from), ("due_date", "<=", date_to), ("state", "!=", "cancelled"),
                  ("contract_id", "in", contracts.ids)]
        if lease_only:
            domain.append(("contract_id.type", "=", "Lease_to_own"))
        lines = self.env["payment.schedule"].sudo().search(domain)
        return lines

    def _convert(self, amount, currency, on):
        company_currency = self.env.company.currency_id
        if amount is None or currency == company_currency:
            return amount
        return company_currency._convert(amount, currency, self.env.company, on)

    def _rates_for_month(self, month_end, product_group_id):
        """C08/C09 for one calendar month, from month snapshots when present, else live."""
        start = month_end.replace(day=1)
        snaps = self.env["gh.contract.snapshot"].sudo().search([
            ("period_type", "=", "month"), ("period_end", "=", month_end), ("is_active", "=", True),
            ("company_id", "=", self.env.company.id)] + ([("product_group_id", "=", product_group_id)] if product_group_id else []))
        if snaps:
            contract_ids = snaps.mapped("contract_id").ids
        else:
            contract_ids = self._contracts_of_group(product_group_id, [("state", "in", ACTIVE_STATES)]).ids
        history = self.env["gh.history.service"]
        collected = sum(history._collected_by_contract(start, month_end, contract_ids).values())
        due = sum(history._due_by_contract(start, month_end, contract_ids).values())
        fleet = self._fleet(month_end, product_group_id) if month_end >= self._today() - timedelta(days=31) else None
        standard = history._group_standard_instalment()
        available_due = 0.0
        available_count = 0
        if fleet:
            _p, by_model, _g = self.env["gh.product.group"]._group_maps()
            available = self.env["fleet.vehicle"].sudo().browse(fleet["unassigned"]["domain"][0][2])
            available_count = len(available)
            weeks = ((month_end - start).days + 1) / 7.0
            available_due = sum(standard.get(by_model[v.model_id.id].id, 0.0) for v in available
                                if by_model.get(v.model_id.id)) * weeks
        return {"month": month_end.strftime("%B %Y"), "collected": collected, "due": due,
                "active_rate": self._pct(collected, due),
                "fleet_rate": self._pct(collected, due + available_due), "available": available_count,
                "available_due": available_due}

    def _forecast(self, on, product_group_id):
        config = self.env["gh.dashboard.config"]._get_config()
        contracts = self._contracts_of_group(product_group_id, [("state", "in", ACTIVE_STATES)])
        rows = {r["contract_id"]: r for r in self.env["gh.history.service"]._live_contract_rows(on)}
        # expected rate per risk category: trailing weekly snapshots, collected / due
        snaps = self.env["gh.contract.snapshot"].sudo().search([
            ("period_type", "=", "week"), ("is_active", "=", True), ("company_id", "=", self.env.company.id),
            ("period_end", ">=", on - timedelta(weeks=config.rate_window_weeks)), ("period_end", "<=", on)])
        due_by, coll_by = defaultdict(float), defaultdict(float)
        for s in snaps:
            due_by[s.risk_category] += s.due_in_period
            coll_by[s.risk_category] += s.collected_in_period
        rates = {k: (coll_by[k] / due_by[k]) if due_by[k] else None for k in RISK_ORDER}
        weeks = []
        start = on + timedelta(days=1)
        lines = self.env["payment.schedule"].sudo().search([
            ("contract_id", "in", contracts.ids), ("state", "in", OPEN_SCHEDULE_STATES),
            ("due_date", ">=", start), ("due_date", "<", start + timedelta(weeks=config.forecast_weeks))])
        buckets = defaultdict(lambda: [0.0, 0.0])
        missing_rate = False
        for line in lines:
            week = (line.due_date - start).days // 7
            amount = line.balance if line.state == "partial" else line.amount
            buckets[week][0] += amount
            cat = rows.get(line.contract_id.id, {}).get("risk_category")
            rate = rates.get(cat)
            if rate is None:
                missing_rate = True
                rate = 1.0
            buckets[week][1] += amount * rate
        for i in range(config.forecast_weeks):
            ws = start + timedelta(weeks=i)
            weeks.append({"week": ws.strftime("%d %b"), "contractual": buckets[i][0], "risk_adjusted": buckets[i][1]})
        return {"weeks": weeks, "rates": {k: round(v * 100, 1) if v is not None else None for k, v in rates.items()},
                "window": config.rate_window_weeks, "rates_complete": not missing_rate,
                "schedule_horizon": max((l.due_date for l in lines), default=None) and
                fields.Date.to_string(max(l.due_date for l in lines))}

    def _monthly_vs_due(self, on, product_group_id, months=10):
        out = []
        contracts = self._contracts_of_group(product_group_id, [])
        classify = self.env["gh.payment.category.rule"]._classifier()
        start_month = (on.replace(day=1) - relativedelta(months=months - 1))
        for end in month_ends(start_month, on + timedelta(days=31)):
            start = end.replace(day=1)
            if start > on:
                break
            stop = min(end, on)
            logs = self._logs(start, stop, product_group_id)
            collected = sum(l.amount for l in logs if classify(l) in INSTALMENT_CATEGORIES)
            due = sum(self._due(start, end, contracts).mapped("amount"))
            out.append({"month": start.strftime("%b"), "collected": collected, "due": due, "pct": self._pct(collected, due)})
        return out

    def _by_model(self, date_from, date_to):
        classify = self.env["gh.payment.category.rule"]._classifier()
        by_product, _m, groups = self.env["gh.product.group"]._group_maps()
        collected, due = defaultdict(float), defaultdict(float)
        for log in self._logs(date_from, date_to):
            if log.contract_id and classify(log) in INSTALMENT_CATEGORIES:
                g = by_product.get(log.contract_id.product_product_id.id)
                collected[g.id if g else 0] += log.amount
        for line in self._due(date_from, date_to, self.env["rider.contract"].sudo().search([])):
            g = by_product.get(line.contract_id.product_product_id.id)
            due[g.id if g else 0] += line.amount
        total = sum(collected.values())
        rows = [{"label": g.name, "slot": g.color_slot, "collected": collected.get(g.id, 0.0),
                 "share": self._pct(collected.get(g.id, 0.0), total), "due": due.get(g.id, 0.0),
                 "performance": self._pct(collected.get(g.id, 0.0), due.get(g.id, 0.0))} for g in groups]
        if collected.get(0) or due.get(0):
            rows.append({"label": _("Not mapped"), "slot": False, "collected": collected.get(0, 0.0),
                         "share": self._pct(collected.get(0, 0.0), total), "due": due.get(0, 0.0),
                         "performance": self._pct(collected.get(0, 0.0), due.get(0, 0.0)), "warn": True})
        return {"rows": rows, "total": total, "total_due": sum(due.values()),
                "month": date_from.strftime("%B %Y")}

    def _financing(self, date_from, date_to, instalment_cash):
        lines = self.env["gh.financing.schedule"].sudo().search([("due_date", ">=", date_from), ("due_date", "<=", date_to)])
        if not lines:
            return {"has_data": False, "instalment_cash": instalment_cash}
        company = self.env.company
        to_company = lambda l: l.currency_id._convert(l.principal + l.interest + l.fees, company.currency_id,
                                                       company, l.due_date)
        due = sum(to_company(l) for l in lines)
        by_lender = defaultdict(float)
        for l in lines:
            by_lender[l.facility_id.lender_id.display_name] += to_company(l)
        return {"has_data": True, "instalment_cash": instalment_cash, "debt_service_due": due,
                "coverage": round(instalment_cash / due, 2) if due else None,
                "by_lender": [{"lender": k, "due": v} for k, v in by_lender.items()]}

    def _target_version(self, version_id=None):
        Version = self.env["gh.kpi.target.version"].sudo()
        if version_id:
            return Version.browse(version_id)
        today = self._today()
        return Version.search([("state", "=", "approved"), ("effective_from", "<=", today),
                               ("effective_to", ">=", today)], order="kind, approved_on desc", limit=1)

    @api.model
    def get_collections_dashboard(self, period="this_month", date_from=False, date_to=False, product_group_id=None,
                                  grain="week", currency="company"):
        self._check_access()
        on = self._today()
        product_group_id = product_group_id or None
        start, end = self._period(period, date_from, date_to, on)
        cur = self.env.company.currency_id
        if currency == "usd":
            cur = self.env["gh.dashboard.config"]._get_config().fx_currency_id or cur
        conv = lambda v: self._convert(v, cur, end)

        def kpis():
            logs = self._logs(start, end, product_group_id)
            amounts, ids = self._by_category(logs)
            total = sum(amounts.values())
            contracts = self._contracts_of_group(product_group_id, [])
            due_lines = self._due(start, end, contracts, lease_only=True)
            due_lease = sum(due_lines.mapped("amount"))
            paid_lines = due_lines.filtered(lambda l: l.state == "paid")
            version = self._target_version()
            month_days = (start + relativedelta(months=1, days=-1) - start).days + 1 if period != "custom" else None
            elapsed = (end - start).days + 1
            cats = []
            Target = self.env["gh.kpi.target"]
            for key, label in PAYMENT_CATEGORIES:
                target = Target._value(version, "C05", start, start + relativedelta(months=1, days=-1)
                                       if period != "custom" else end, f"category:{key}") if version else None
                pro_rata = target * elapsed / month_days if target is not None and month_days else target
                actual = amounts.get(key, 0.0)
                if not actual and target is None and key == "other":
                    continue
                cats.append({"key": key, "label": label, "actual": conv(actual), "target": conv(target),
                             "pro_rata": conv(pro_rata), "achieved": self._pct(actual, target) if target else None,
                             "variance": conv(actual - pro_rata) if pro_rata is not None else None,
                             "domain": [("id", "in", ids.get(key, []))]})
            total_target = sum(c["target"] for c in cats if c["target"] is not None) if any(
                c["target"] is not None for c in cats) else None
            total_pro = sum(c["pro_rata"] for c in cats if c["pro_rata"] is not None) if total_target is not None else None
            return {
                "period": {"from": fields.Date.to_string(start), "to": fields.Date.to_string(end), "elapsed": elapsed,
                           "days": month_days, "key": period},
                "total": conv(total), "count": len(logs), "domain": [("id", "in", logs.ids)],
                "lease": conv(amounts.get("lease", 0.0)), "late_fees": conv(amounts.get("late_fee", 0.0)),
                "deposits": conv(amounts.get("deposit", 0.0)),
                "lease_due": conv(due_lease), "due_domain": [("id", "in", due_lines.ids)],
                "progress": self._pct(amounts.get("lease", 0.0), due_lease),
                "compliance": self._pct(len(paid_lines), len(due_lines)),
                "categories": cats, "unmapped": amounts.get("other", 0.0), "unmapped_count": len(ids.get("other", [])),
                "target_total": conv(total_target), "target_pro_rata": conv(total_pro),
                "vs_target": self._pct(total, total_target) if total_target else None,
                "variance": conv(total - total_pro) if total_pro is not None else None,
                "variance_pct": self._pct(total - total_pro, abs(total_pro)) if total_pro else None,
                "version": version.name if version else False,
            }

        last_month_end = on.replace(day=1) - timedelta(days=1)
        core = self._panel(kpis)
        rows = self.env["gh.history.service"]._live_contract_rows(on)
        return {
            "as_of": fields.Date.to_string(on), "computed_at": fields.Datetime.to_string(fields.Datetime.now()),
            "company": self.env.company.name, "currency": cur.name, "currency_key": currency,
            "fx_currency": (self.env["gh.dashboard.config"]._get_config().fx_currency_id.name or False),
            "product_groups": self._group_payload(self.env["gh.product.group"].sudo().search([])),
            "core": core,
            "rates": self._panel(self._rates_for_month, last_month_end, product_group_id),
            "rate_trend": self._panel(lambda: self._rate_trend(grain, on)),
            "monthly": self._panel(lambda: {"rows": self._monthly_vs_due(on, product_group_id)}),
            "by_model": self._panel(self._by_model, last_month_end.replace(day=1), last_month_end),
            "forecast": self._panel(self._forecast, on, product_group_id),
            "financing": self._panel(lambda: self._financing(
                last_month_end.replace(day=1), last_month_end,
                sum(self.env["gh.history.service"]._collected_by_contract(last_month_end.replace(day=1), last_month_end).values()))),
            "defaults": self._panel(self._default_block, on, rows, on.year),
            "checks": self._collections_checks(core),
        }

    def _rate_trend(self, grain, on):
        snaps = self.env["gh.kpi.snapshot"].sudo().search([
            ("metric_code", "in", ["C08", "C09"]), ("period_type", "=", grain), ("company_id", "=", self.env.company.id),
            ("period_end", ">=", on - (timedelta(weeks=26) if grain == "week" else relativedelta(months=12)))],
            order="period_end")
        per = defaultdict(dict)
        for s in snaps:
            per[s.period_end][f"{s.metric_code}:{s.dim_key}"] = s.value_float
        ends = sorted(per)
        return {"periods": [fields.Date.to_string(e) for e in ends],
                "active": [self._pct(per[e].get("C08:collected", 0), per[e].get("C08:due", 0)) for e in ends],
                "fleet": [self._pct(per[e].get("C09:collected", 0), per[e].get("C09:due", 0)) for e in ends]}

    def _collections_checks(self, core):
        if not core.get("ok"):
            return []
        cat_sum = sum(c["actual"] or 0 for c in core["categories"])
        return [
            {"code": "C04", "ok": abs(cat_sum - (core["total"] or 0)) < 1 and not core["unmapped_count"],
             "message": _("Categories sum to the %(n)s successful receipts; %(u)s receipts matched no category rule",
                          n=core["count"], u=core["unmapped_count"])},
        ]
