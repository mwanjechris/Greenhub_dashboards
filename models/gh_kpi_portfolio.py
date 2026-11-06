"""Portfolio Health & Credit Risk KPIs (spec 5.2, P01-P22)."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import median

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

from .gh_history import PAR_ORDER, RISK_ORDER, month_ends

RISK_LABELS = {
    "ahead": "Ahead", "ontrack": "On track", "norisk": "No risk", "low": "Low risk",
    "atrisk": "At risk", "high": "High risk", "critical": "Critical", "default": "Default",
}
PAR_LABELS = {"par0": "PAR0", "par7": "PAR7", "par14": "PAR14", "par21": "PAR21", "par28": "PAR28"}


class GhKpiServicePortfolio(models.AbstractModel):
    _inherit = "gh.kpi.service"

    # ------------------------------------------------------------ rows
    def _portfolio_rows(self, on, historic, product_group_id):
        if historic:
            fields_ = ["contract_id", "rider_id", "bike_id", "product_group_id", "state", "payment_state", "is_active",
                       "in_default", "arrears", "penalties", "credit", "instalment", "dpd", "risk_category",
                       "par_bucket", "due_in_period", "collected_in_period"]
            rows = self.env["gh.contract.snapshot"].sudo().search_read(
                [("period_type", "=", "week"), ("period_end", "=", on), ("company_id", "=", self.env.company.id)], fields_)
            for r in rows:
                for key in ("contract_id", "rider_id", "bike_id", "product_group_id"):
                    r[key] = r[key][0] if r[key] else False
        else:
            rows = self.env["gh.history.service"]._live_contract_rows(on, "week")
        if product_group_id:
            rows = [r for r in rows if r["product_group_id"] == product_group_id]
        return rows

    def _band_descriptions(self):
        config = self.env["gh.dashboard.config"]._get_config()
        lim = config._band_limits()
        unit = "×" if config.risk_band_basis == "instalments" else " UGX"
        fmt = (lambda v: f"{v:g}{unit}") if unit == "×" else (lambda v: f"{v:,.0f}{unit}")
        return {
            "ahead": _("Payment status Ahead"), "ontrack": _("On track, or behind ≤ %s", fmt(lim[0])),
            "norisk": f"{fmt(lim[0])} – {fmt(lim[1])}", "low": f"{fmt(lim[1])} – {fmt(lim[2])}",
            "atrisk": f"{fmt(lim[2])} – {fmt(lim[3])}", "high": f"{fmt(lim[3])} – {fmt(lim[4])}",
            "critical": _("> %s, not in default", fmt(lim[4])), "default": _("In default (see definition)"),
        }, {
            "par0": _("0 days"), "par7": _("1–%s", config.par_1), "par14": f"{config.par_1 + 1}–{config.par_2}",
            "par21": f"{config.par_2 + 1}–{config.par_3}", "par28": _("≥ %s", config.par_3 + 1),
        }

    def _portfolio_core(self, rows):
        active = [r for r in rows if r["is_active"]]
        n = len(active)
        ids = [r["contract_id"] for r in active]
        arrears = sum(r["arrears"] for r in active)
        fees = sum(r["penalties"] for r in active)
        credit_rows = [r for r in active if r["credit"] > 0]
        risk = Counter(r["risk_category"] for r in active)
        par = Counter(r["par_bucket"] for r in active)
        par_arrears = defaultdict(float)
        for r in active:
            par_arrears[r["par_bucket"]] += r["arrears"]
        risk_desc, par_desc = self._band_descriptions()
        by = lambda key, values: [r["contract_id"] for r in active if r[key] in values]
        late = self._ever_late_fee_ids(ids)
        perfect = [cid for cid in ids if cid not in late]
        running = sum(1 for r in active if r["state"] == "running")
        default_rows = [r for r in rows if r["in_default"]]
        return {
            "active_contracts": {"value": n, "running": running, "paused": n - running, "domain": [("id", "in", ids)]},
            "total_arrears": {"value": arrears, "late_fees": fees,
                              "domain": [("id", "in", [r["contract_id"] for r in active if r["arrears"] > 0])]},
            "avg_arrears": {"value": arrears / n if n else None},
            "credit": {"value": sum(r["credit"] for r in credit_rows), "count": len(credit_rows),
                       "domain": [("id", "in", [r["contract_id"] for r in credit_rows])]},
            "perfect": {"value": len(perfect), "pct": self._pct(len(perfect), n), "domain": [("id", "in", perfect)]},
            "ahead_ontrack": {"value": risk["ahead"] + risk["ontrack"], "pct": self._pct(risk["ahead"] + risk["ontrack"], n),
                              "domain": [("id", "in", by("risk_category", ("ahead", "ontrack")))]},
            "behind": {"value": sum(risk[k] for k in ("norisk", "low", "atrisk", "high")),
                       "pct": self._pct(sum(risk[k] for k in ("norisk", "low", "atrisk", "high")), n),
                       "domain": [("id", "in", by("risk_category", ("norisk", "low", "atrisk", "high")))]},
            "in_default": {"value": risk["default"], "pct": self._pct(risk["default"], n),
                           "domain": [("id", "in", by("risk_category", ("default",)))]},
            "critical_default": {"value": risk["critical"] + risk["default"], "pct": self._pct(risk["critical"] + risk["default"], n),
                                 "domain": [("id", "in", by("risk_category", ("critical", "default")))]},
            "risk": [{"key": k, "label": RISK_LABELS[k], "rule": risk_desc[k], "count": risk.get(k, 0),
                      "pct": self._pct(risk.get(k, 0), n), "domain": [("id", "in", by("risk_category", (k,)))]}
                     for k in RISK_ORDER],
            "par": [{"key": k, "label": PAR_LABELS[k], "rule": par_desc[k], "count": par.get(k, 0),
                     "pct": self._pct(par.get(k, 0), n), "arrears": par_arrears.get(k, 0.0),
                     "domain": [("id", "in", by("par_bucket", (k,)))]} for k in PAR_ORDER],
            "default_ids": [r["contract_id"] for r in default_rows],
        }

    def _ever_late_fee_ids(self, contract_ids):
        Schedule = self.env["payment.schedule"].sudo()
        late = set()
        for contract, _n in Schedule._read_group(
                [("contract_id", "in", contract_ids), "|", ("last_penalty_date", "!=", False),
                 ("penalties_invoice_id", "!=", False)], ["contract_id"], ["__count"]):
            late.add(contract.id)
        for c in self.env["rider.contract"].sudo().browse(contract_ids):
            if (c.total_penalties or 0) > 0 or (c.total_paid_late_payment or 0) > 0:
                late.add(c.id)
        return late

    # ------------------------------------------------------------ default block (shared with Collections)
    def _revenue(self, date_from, date_to):
        """Revenue as Odoo's P&L reports it (the Revenue line), for loss / revenue %."""
        lines, _r, _o = self._pl_read(date_from, date_to)
        return lines["REV"]["actual"] if "REV" in lines else None

    def _default_block(self, on, rows, year):
        config = self.env["gh.dashboard.config"]._get_config()
        reporting = [r for r in rows if r["is_active"] or r["in_default"]]
        defaults = [r for r in rows if r["in_default"]]
        year_start = date(year, 1, 1)
        through = min(on, date(year, 12, 31))
        loss_accounts = config.default_loss_account_ids
        losses_ytd = self._ledger_sum(loss_accounts, year_start, through)
        months_elapsed = (through - year_start).days / 30.4375 if through >= year_start else 0
        monthly = []
        for end in month_ends(year_start, through + timedelta(days=31)):
            start = end.replace(day=1)
            if start > through:
                break
            loss = self._ledger_sum(loss_accounts, start, min(end, through))
            revenue = self._revenue(start, min(end, through))
            monthly.append({"month": start.strftime("%b"), "loss": loss, "revenue": revenue,
                            "from": fields.Date.to_string(start), "to": fields.Date.to_string(min(end, through)),
                            "loss_pct": self._pct(loss, revenue) if loss is not None and revenue else None})
        return {
            "year": year,
            "scope": config.default_scope,
            "scope_label": dict(config._fields["default_scope"].selection)[config.default_scope],
            "rate": {"value": self._pct(len(defaults), len(reporting)), "count": len(defaults), "of": len(reporting),
                     "domain": [("id", "in", [r["contract_id"] for r in defaults])]},
            "arrears_in_default": sum(r["arrears"] for r in defaults),
            "losses_ytd": losses_ytd,
            "avg_monthly_loss": losses_ytd / months_elapsed if losses_ytd is not None and months_elapsed else None,
            "ytd_from": fields.Date.to_string(year_start), "ytd_to": fields.Date.to_string(through),
            "months_elapsed": round(months_elapsed, 1),
            "monthly": monthly,
            "loss_accounts_mapped": bool(loss_accounts), "loss_account_ids": loss_accounts.ids,
            "loss_accounts": ", ".join(loss_accounts.mapped("display_name")),
        }

    def _repossessions(self, year, product_group_id):
        Exit = self.env["gh.exit.type.rule"]
        Contract = self.env["rider.contract"].sudo()
        ended = Contract.search([("state", "in", ("closed", "terminated")), ("bike_id", "!=", False)])
        by_product, _m, _g = self.env["gh.product.group"]._group_maps()
        rows, waiting, days, refinanced = [], [], [], []
        for c in ended:
            end_date = c.termination_date or c.contract_end_date
            if not end_date or end_date.year != year or Exit._exit_type(c) != "repossession_default":
                continue
            if product_group_id and not (by_product.get(c.product_product_id.id)
                                         and by_product[c.product_product_id.id].id == product_group_id):
                continue
            nxt = Contract.search([("bike_id", "=", c.bike_id.id), ("id", "!=", c.id),
                                   ("contract_start_date", ">=", end_date)], order="contract_start_date", limit=1)
            if nxt:
                days.append((nxt.contract_start_date - end_date).days)
                refinanced.append(nxt.id)
            else:
                waiting.append(c.bike_id.id)
            rows.append(c.id)
        return {"repossessed": len(rows), "refinanced": len(days), "waiting": len(waiting),
                "avg_days": round(sum(days) / len(days), 1) if days else None,
                "median_days": median(days) if days else None,
                "waiting_domain": [("id", "in", waiting)], "domain": [("id", "in", rows)],
                "refinanced_ids": refinanced, "refinanced_domain": [("id", "in", refinanced)],
                "exit_rules": bool(self.env["gh.exit.type.rule"].sudo().search_count([]))}

    def _default_trend(self, grain, date_from, on):
        events = self.env["default.tracking"].sudo().search([("date", ">=", date_from), ("date", "<=", on)])
        snaps = self.env["gh.kpi.snapshot"].sudo().search(
            [("metric_code", "=", "P13"), ("period_type", "=", grain), ("period_end", ">=", date_from),
             ("company_id", "=", self.env.company.id)], order="period_end")
        out = []
        for snap in snaps:
            start = snap.period_start
            new = {e.contract_id.id for e in events if start <= e.date <= snap.period_end}
            out.append({"end": fields.Date.to_string(snap.period_end), "new": len(new), "outstanding": snap.value_count})
        return out

    def _recovery(self, on, months=6):
        Snap = self.env["gh.contract.snapshot"].sudo()
        ends = self._period_ends("month", None, on)
        out = []
        for prev, end in zip(ends, ends[1:]):
            opening_rows = Snap.search([("period_type", "=", "month"), ("period_end", "=", prev), ("is_active", "=", True)])
            closing = sum(Snap.search([("period_type", "=", "month"), ("period_end", "=", end),
                                       ("is_active", "=", True)]).mapped("arrears"))
            opening = sum(opening_rows.mapped("arrears"))
            with_arrears = {s.contract_id.id: s.arrears for s in opening_rows if s.arrears > 0}
            collected = self.env["gh.history.service"]._collected_by_contract(prev + timedelta(days=1), end, list(with_arrears))
            recovered = sum(min(collected.get(cid, 0.0), amount) for cid, amount in with_arrears.items())
            out.append({"month": end.strftime("%b %Y"), "opening": opening, "closing": closing,
                        "prev_end": fields.Date.to_string(prev), "end": fields.Date.to_string(end),
                        "recovered": recovered, "pct": self._pct(recovered, opening)})
        return out[-months:]

    def _portfolio_trends(self, grain, date_from, on, product_group_id):
        domain = [("period_type", "=", grain), ("period_end", ">=", date_from), ("period_end", "<=", on),
                  ("company_id", "=", self.env.company.id)]
        if product_group_id:
            # per-group trends straight from contract snapshots
            snaps = self.env["gh.contract.snapshot"].sudo().search(domain + [("is_active", "=", True),
                                                                            ("product_group_id", "=", product_group_id)])
            per = defaultdict(list)
            for s in snaps:
                per[s.period_end].append(s)
            ends = sorted(per)
            return {"periods": [fields.Date.to_string(e) for e in ends],
                    "arrears": [sum(x.arrears for x in per[e]) for e in ends],
                    "avg_arrears": [sum(x.arrears for x in per[e]) / len(per[e]) for e in ends],
                    "risk": [{k: sum(1 for x in per[e] if x.risk_category == k) for k in RISK_ORDER} for e in ends]}
        snaps = self.env["gh.kpi.snapshot"].sudo().search(domain + [("metric_code", "in", ["P01", "P02", "P03", "P11"])])
        per = defaultdict(dict)
        risk = defaultdict(dict)
        for s in snaps:
            if s.metric_code == "P11":
                risk[s.period_end][s.dim_key.split(":", 1)[1]] = s.value_count
            else:
                per[s.period_end][s.metric_code] = s.value_float or s.value_count
        ends = sorted(per)
        return {"periods": [fields.Date.to_string(e) for e in ends],
                "arrears": [per[e].get("P02", 0.0) for e in ends],
                "avg_arrears": [per[e].get("P03", 0.0) for e in ends],
                "risk": [{k: risk[e].get(k, 0) for k in RISK_ORDER} for e in ends]}

    def _portfolio_checks(self, core, riders_total):
        n = core["active_contracts"]["value"]
        return [
            {"code": "P11", "ok": sum(r["count"] for r in core["risk"]) == n,
             "message": _("Risk categories sum to %(s)s of %(n)s active contracts", s=sum(r["count"] for r in core["risk"]), n=n)},
            {"code": "P12", "ok": sum(r["count"] for r in core["par"]) == n,
             "message": _("PAR buckets sum to %(s)s of %(n)s active contracts", s=sum(r["count"] for r in core["par"]), n=n)},
            {"code": "P01", "ok": riders_total is None or n >= riders_total,
             "message": _("%(n)s contracts vs %(r)s active riders on Riders & Customers", n=n, r=riders_total)},
        ]

    @api.model
    def get_portfolio_dashboard(self, product_group_id=None, grain="week", as_of=False, year=None, range_key="26w"):
        self._check_access()
        on, historic = self._as_of(as_of)
        product_group_id = product_group_id or None
        year = int(year or on.year)
        rows = self._portfolio_rows(on, historic, product_group_id)
        core = self._panel(self._portfolio_core, rows)
        riders = len({r["rider_id"] for r in rows if r["is_active"] and r["rider_id"]})
        date_from = self._range_start(range_key, grain, on)
        last_snapshot = self.env["gh.kpi.snapshot"].sudo().search(
            [("company_id", "=", self.env.company.id)], order="period_end desc", limit=1)
        return {
            "as_of": fields.Date.to_string(on), "historic": historic, "as_of_options": self._as_of_options(),
            "computed_at": fields.Datetime.to_string(fields.Datetime.now()), "company": self.env.company.name,
            "currency": self.env.company.currency_id.name,
            "product_groups": self._group_payload(self.env["gh.product.group"].sudo().search([])),
            "years": sorted({on.year, on.year - 1}, reverse=True), "year": year,
            "last_snapshot": fields.Date.to_string(last_snapshot.period_end) if last_snapshot else False,
            "band_basis": self.env["gh.dashboard.config"]._get_config().risk_band_basis,
            "core": core,
            "defaults": self._panel(self._default_block, on, rows, year),
            "repossessions": self._panel(self._repossessions, year, product_group_id),
            "default_trend": self._panel(lambda: {"rows": self._default_trend("month", date(year, 1, 1), on)}),
            "recovery": self._panel(lambda: {"rows": self._recovery(on)}),
            "trends": self._panel(self._portfolio_trends, grain, date_from, on, product_group_id),
            "checks": self._portfolio_checks(core, riders) if core.get("ok") else [],
            "is_manager": self.env.user.has_group("greenhub_dashboards.group_gh_dashboard_manager"),
        }
