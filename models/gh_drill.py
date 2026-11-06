"""Drill-through for every dashboard figure.

The dashboards call ``get_drill(kind, args)`` when a figure is clicked. Each kind
rebuilds the exact records the figure was computed from and returns a window
action on them, so the list a user lands on always adds up to the number they
clicked. Figures that come from the general ledger also offer the matching
Odoo accounting report (``report`` kind) for the same dates, and P&L figures
open Odoo's own audit of the report cell (``pl_cell``).
"""
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .gh_history import ACTIVE_STATES, OPEN_SCHEDULE_STATES
from .gh_mapping import INSTALMENT_CATEGORIES

# Odoo accounting reports (Enterprise account_reports). Fallback when absent: journal items.
REPORTS = {
    "pl": ("account_reports.action_account_report_pl", "Profit and Loss"),
    "bs": ("account_reports.action_account_report_bs", "Balance Sheet"),
    "gl": ("account_reports.action_account_report_general_ledger", "General Ledger"),
    "ar": ("account_reports.action_account_report_ar", "Aged Receivable"),
    "partner": ("account_reports.action_account_report_partner_ledger", "Partner Ledger"),
}


class GhKpiServiceDrill(models.AbstractModel):
    _inherit = "gh.kpi.service"

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _d(value):
        return fields.Date.to_date(value) if value else None

    def _window_action(self, model, ids, name, views=None, context=None):
        return {
            "type": "ir.actions.act_window", "name": name, "res_model": model,
            "views": views or [[False, "list"], [False, "form"]],
            "domain": [("id", "in", list(ids))], "target": "current",
            "context": dict(context or {}, create=False),
        }

    def _drill_view(self, xmlid):
        view = self.env.ref(xmlid, raise_if_not_found=False)
        return view.id if view else False

    def _available_reports(self):
        return {key: bool(self.env.ref(xmlid, raise_if_not_found=False)) for key, (xmlid, _l) in REPORTS.items()}

    # ------------------------------------------------------------------ entry point
    @api.model
    def get_drill(self, kind, args=None):
        """Return an action for one figure. ``kind`` picks the record source; ``args`` scope it."""
        self._check_access()
        args = dict(args or {})
        method = getattr(self, f"_drill_{kind}", None)
        if not method:
            raise UserError(_("Unknown drill-through: %s", kind))
        return method(**args)

    # ------------------------------------------------------------------ accounting (all computed by Odoo)
    def _drill_report(self, report="pl", date_from=None, date_to=None, label=None, budget_id=None):
        """Odoo's own accounting report for the figure's dates (and the dashboard's budget, for the P&L)."""
        xmlid, title = REPORTS[report]
        date_from, date_to = self._d(date_from), self._d(date_to) or self._today()
        if self.env.ref(xmlid, raise_if_not_found=False):
            action = self.env["ir.actions.actions"]._for_xml_id(xmlid)
            options = {"date": {
                "date_from": fields.Date.to_string(date_from or date_to.replace(month=1, day=1)),
                "date_to": fields.Date.to_string(date_to), "filter": "custom", "mode": "range"}}
            if report == "pl":
                config = self.env["gh.dashboard.config"]._get_config()
                pl = config._pl_report()
                if pl:
                    options["selected_variant_id"] = pl.id
                    action.setdefault("context", {})
                if budget_id:
                    options["budgets"] = [{"id": budget_id, "selected": True}]
            action["params"] = dict(action.get("params") or {}, ignore_session=True, options=options)
            return action
        domain = [("parent_state", "=", "posted"), ("company_id", "=", self.env.company.id), ("date", "<=", date_to)]
        if date_from and report != "bs":
            domain.append(("date", ">=", date_from))
        lines = self.env["account.move.line"].search(domain)
        return self._window_action("account.move.line", lines.ids, label or title)

    def _drill_pl_cell(self, report_line_id=None, date_from=None, date_to=None, label=None):
        """Exactly what clicking this cell in Odoo's P&L opens (Odoo's audit of the report line)."""
        line = self.env["account.report.line"].browse(int(report_line_id))
        report = line.report_id
        options = self._pl_options(report, self._d(date_from), self._d(date_to))
        rows = report._get_lines(options)
        row = next((r for r in rows if report._get_model_info_from_id(r["id"]) == ("account.report.line", line.id)), None)
        if not row:
            raise UserError(_("Line %s not found in %s.", line.name, report.display_name))
        col = row["columns"][0]
        action = report.action_audit_cell(options, {
            "report_line_id": line.id, "calling_line_dict_id": row["id"],
            "expression_label": col.get("expression_label") or "balance", "column_group_key": col["column_group_key"]})
        if action.get("type") == "ir.actions.act_window":
            action["name"] = _("%(line)s · %(f)s – %(t)s", line=label or line.name, f=date_from, t=date_to)
            if not any(v[1] == "form" for v in action.get("views", [])):
                action["views"] = list(action.get("views") or [[False, "list"]]) + [[False, "form"]]
        return action

    def _drill_ledger(self, account_ids=(), date_from=None, date_to=None, label=None, side="balance"):
        """Posted journal items on ledger accounts picked in settings (default losses, lender loans)."""
        if not account_ids:
            action = self.env["ir.actions.actions"]._for_xml_id("greenhub_dashboards.action_gh_dashboard_config")
            action["name"] = _("Settings: pick the ledger accounts for %s", label or _("this figure"))
            return action
        domain = [("account_id", "in", list(account_ids)), ("parent_state", "=", "posted"),
                  ("company_id", "=", self.env.company.id),
                  ("date", ">=", self._d(date_from)), ("date", "<=", self._d(date_to))]
        if side == "debit":
            domain.append(("debit", ">", 0))
        lines = self.env["account.move.line"].search(domain)
        action = self._window_action("account.move.line", lines.ids, _("Journal items · %s", label or ""))
        action["context"].update(group_by=["account_id"])
        return action

    def _drill_payments(self, date_from=None, date_to=None, matched=None, label=None):
        """Odoo customer payments (Accounting) for the side-by-side with GreenHub payment logs."""
        payments = self._odoo_payments(self._d(date_from), self._d(date_to))
        if matched is not None:
            linked = set(self._logs(self._d(date_from), self._d(date_to)).mapped("payment_id").ids)
            payments = payments.filtered(lambda p: (p.id in linked) == bool(matched))
        return self._window_action("account.payment", payments.ids, label or _("Customer payments (Odoo)"))

    def _drill_logs_unmatched(self, date_from=None, date_to=None, label=None, matched=False):
        """GreenHub logs with (matched=True) or without an Odoo payment in the same dates."""
        logs = self._logs(self._d(date_from), self._d(date_to))
        payments = set(self._odoo_payments(self._d(date_from), self._d(date_to)).ids)
        logs = logs.filtered(lambda l: (l.payment_id.id in payments) == bool(matched))
        return self._window_action("payment.log", logs.ids, label or (
            _("Payment logs matched to an Odoo payment") if matched else _("Payment logs without an Odoo payment")))

    # ------------------------------------------------------------------ targets / plans
    def _drill_targets(self, version_id=None, metrics=(), dim_keys=None, dim_prefix=None, date_from=None, date_to=None,
                       point_on=None, label=None):
        """The target lines a plan / budget figure was summed from."""
        version = self.env["gh.kpi.target.version"].sudo().browse(version_id) if version_id else self._target_version()
        if not version:
            action = self.env["ir.actions.actions"]._for_xml_id("greenhub_dashboards.action_gh_kpi_target_version")
            action["name"] = _("No approved target version yet")
            return action
        domain = [("version_id", "=", version.id), ("metric_code", "in", list(metrics))]
        if dim_keys is not None:
            domain.append(("dim_key", "in", [k or "" for k in dim_keys]))
        elif dim_prefix:
            domain.append(("dim_key", "=like", f"{dim_prefix}%"))
        if point_on:
            domain.append(("period_start", "=", self._d(point_on).replace(day=1)))
        else:
            if date_from:
                domain.append(("period_start", ">=", self._d(date_from).replace(day=1)))
            if date_to:
                domain.append(("period_start", "<=", self._d(date_to)))
        targets = self.env["gh.kpi.target"].search(domain)
        return self._window_action("gh.kpi.target", targets.ids,
                                   _("%(label)s · %(version)s", label=label or _("Targets"), version=version.name),
                                   views=[[self._drill_view("greenhub_dashboards.view_gh_kpi_target_drill_list"), "list"]])

    # ------------------------------------------------------------------ snapshots
    def _drill_snapshots(self, period_type="week", period_end=None, product_group_id=None, is_active=None,
                         in_default=None, risk_category=None, par_bucket=None, arrears=None, label=None):
        """Contract snapshot rows behind a historic figure (one row per contract per period end)."""
        domain = [("period_type", "=", period_type), ("period_end", "=", self._d(period_end)),
                  ("company_id", "=", self.env.company.id)]
        if product_group_id:
            domain.append(("product_group_id", "=", product_group_id))
        if is_active is not None:
            domain.append(("is_active", "=", is_active))
        if in_default is not None:
            domain.append(("in_default", "=", in_default))
        if risk_category:
            domain.append(("risk_category", "=", risk_category))
        if par_bucket:
            domain.append(("par_bucket", "=", par_bucket))
        if arrears:
            domain.append(("arrears", ">", 0))
        snaps = self.env["gh.contract.snapshot"].search(domain)
        name = _("%(label)s · %(end)s", label=label or _("Contract snapshot"), end=self._d(period_end).strftime("%d %b %Y"))
        return self._window_action("gh.contract.snapshot", snaps.ids, name,
                                   views=[[self._drill_view("greenhub_dashboards.view_gh_contract_snapshot_drill_list"), "list"],
                                          [False, "form"]])

    def _drill_kpi_snapshots(self, metric_codes=(), period_type="week", period_end=None, label=None):
        snaps = self.env["gh.kpi.snapshot"].search([
            ("metric_code", "in", list(metric_codes)), ("period_type", "=", period_type),
            ("period_end", "=", self._d(period_end)), ("company_id", "=", self.env.company.id)])
        return self._window_action("gh.kpi.snapshot", snaps.ids, _("%(label)s · stored KPI values · %(end)s",
                                   label=label or ", ".join(metric_codes), end=period_end))

    def _drill_growth(self, grain="week", period_end=None, part="closing", product_group_id=None, since=None, label=None):
        """Riders behind one cell of the growth table (opening, first-time, returning, exits, closing, retained)."""
        end = self._d(period_end)
        all_ends = self._period_ends(grain, None, end)
        if not all_ends or all_ends[-1] != end:
            raise UserError(_("No %(grain)s snapshot for %(end)s.", grain=grain, end=period_end))
        prev_end = self._d(since) if since else (all_ends[-2] if len(all_ends) > 1 else None)
        if prev_end and prev_end not in all_ends:
            all_ends = sorted(set(all_ends) | {prev_end})
        sets, _c = self._active_sets(grain, all_ends, product_group_id or None)
        cur, prev = sets.get(end, set()), sets.get(prev_end, set()) if prev_end else set()
        seen = set()
        for e in all_ends:
            if e >= end:
                break
            seen |= sets.get(e, set())
        additions = cur - prev
        first = {r for r in additions if r not in seen}
        ids = {"opening": prev, "closing": cur, "first_time": first, "returning": additions - first,
               "exits": prev - cur, "retained": prev & cur}[part]
        return self._window_action("rider", ids, _("%(label)s · %(end)s", label=label or part, end=end.strftime("%d %b %Y")))

    # ------------------------------------------------------------------ cash
    def _drill_receipts(self, date_from=None, date_to=None, product_group_id=None, categories=None, group_id=None,
                        instalment_only=False, label=None):
        """Successful inbound payment logs (cash received) behind a collections figure."""
        logs = self._logs(self._d(date_from), self._d(date_to), product_group_id or None)
        if categories or instalment_only:
            classify = self.env["gh.payment.category.rule"]._classifier()
            wanted = set(categories or INSTALMENT_CATEGORIES)
            logs = logs.filtered(lambda l: classify(l) in wanted)
        if group_id is not None:
            by_product, _m, _g = self.env["gh.product.group"]._group_maps()
            logs = logs.filtered(lambda l: l.contract_id and (
                (by_product.get(l.contract_id.product_product_id.id).id
                 if by_product.get(l.contract_id.product_product_id.id) else 0) == group_id))
        return self._window_action("payment.log", logs.ids, label or _("Receipts"))

    def _drill_dues(self, date_from=None, date_to=None, product_group_id=None, lease_only=False, active_only=False,
                    open_only=False, group_id=None, state=None, label=None):
        """Scheduled instalments (payment.schedule) behind an amount-due figure."""
        domain = [("state", "in", ACTIVE_STATES)] if active_only else []
        contracts = self._contracts_of_group(product_group_id or None, domain)
        lines = self._due(self._d(date_from), self._d(date_to), contracts, lease_only=lease_only)
        if open_only:
            lines = lines.filtered(lambda l: l.state in OPEN_SCHEDULE_STATES)
        if state:
            lines = lines.filtered(lambda l: l.state == state)
        if group_id is not None:
            by_product, _m, _g = self.env["gh.product.group"]._group_maps()
            lines = lines.filtered(lambda l: (by_product.get(l.contract_id.product_product_id.id).id
                                              if by_product.get(l.contract_id.product_product_id.id) else 0) == group_id)
        return self._window_action("payment.schedule", lines.ids, label or _("Instalments due"))

    def _drill_month_contracts(self, month_end=None, product_group_id=None, label=None):
        """Contracts counted in a month's collection rate (month snapshot, else live active)."""
        month_end = self._d(month_end)
        snaps = self.env["gh.contract.snapshot"].sudo().search([
            ("period_type", "=", "month"), ("period_end", "=", month_end), ("is_active", "=", True),
            ("company_id", "=", self.env.company.id)] + ([("product_group_id", "=", product_group_id)] if product_group_id else []))
        ids = snaps.mapped("contract_id").ids or self._contracts_of_group(
            product_group_id or None, [("state", "in", ACTIVE_STATES)]).ids
        return self._window_action("rider.contract", ids, label or _("Contracts in the rate"))

    # ------------------------------------------------------------------ portfolio
    def _drill_contracts(self, on=None, keys=(), label=None, product_group_id=None):
        """Live portfolio rows filtered on a flag (e.g. arrears, credit, in_default)."""
        rows = self._portfolio_rows(self._d(on) or self._today(), False, product_group_id or None)
        ids = [r["contract_id"] for r in rows if all(r.get(k) for k in keys)]
        return self._window_action("rider.contract", ids, label or _("Contracts"))

    def _drill_refinanced(self, year=None, product_group_id=None, label=None):
        rep = self._repossessions(int(year or self._today().year), product_group_id or None)
        return self._window_action("rider.contract", rep["refinanced_ids"], label or _("Refinanced after repossession"))

    def _drill_vehicles_at(self, period_end=None, label=None):
        """Stored unassigned-vehicle counts for a past period (vehicle lists are not snapshotted)."""
        return self._drill_kpi_snapshots(["R06"], "week", period_end, label)

    def _drill_first_time_range(self, date_from=None, date_to=None, grain="week", product_group_id=None, label=None):
        """Riders who appeared for the first time in any period ending inside [date_from, date_to]."""
        date_from, date_to = self._d(date_from), self._d(date_to)
        all_ends = self._period_ends(grain, None, date_to)
        sets, _c = self._active_sets(grain, all_ends, product_group_id or None)
        seen, prev, ids = set(), set(), set()
        for i, end in enumerate(all_ends):
            cur = sets.get(end, set())
            if i and end >= date_from:
                ids |= {r for r in cur - prev if r not in seen}
            seen |= cur
            prev = cur
        return self._window_action("rider", ids, label or _("First-time riders"))

    def _drill_fleet_cell(self, group_id=None, category=None, on=None, product_group_id=None, label=None):
        """Vehicles in one cell of the vehicle-distribution matrix (live)."""
        fleet = self._fleet(self._d(on) or self._today(), product_group_id or None)
        ids = []
        for row in fleet["matrix"]["rows"]:
            if group_id is None or row.get("group_id") == group_id:
                for cell in row["cells"]:
                    if category is None or cell["category"] == category:
                        ids += cell["domain"][0][2]
        return self._window_action("fleet.vehicle", ids, label or _("Vehicles"))

    def _drill_available_vehicles(self, on=None, product_group_id=None, label=None):
        fleet = self._fleet(self._d(on) or self._today(), product_group_id or None)
        return self._window_action("fleet.vehicle", fleet["unassigned"]["domain"][0][2], label or _("Available vehicles"))
