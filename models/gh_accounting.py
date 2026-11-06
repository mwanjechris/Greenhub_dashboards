"""Financial figures come from Odoo accounting, never from the dashboard's own maths.

* P&L figures are read from Odoo's P&L report engine (the standard report, or a
  variant of it chosen in settings), with Odoo's own report budgets as the budget
  column. Clicking a figure runs Odoo's audit of that report cell.
* EBITDA is a line of a P&L variant ("GreenHub P&L (EBITDA)") that lives in
  Accounting > Reporting like any other report: Operating Income plus the
  depreciation / amortisation accounts charged above it. Odoo computes it.
* Default losses and lender repayments are posted journal items on ledger
  accounts picked from the chart of accounts in settings.
* Currency conversion uses Odoo's rates.
"""
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

VARIANT_NAME = "GreenHub P&L (EBITDA)"
VARIANT_XMLID = "greenhub_dashboards.gh_pl_ebitda_variant"
# standard P&L line codes the dashboard reads; a variant made by the button prefixes them with GH_
PL_KEYS = ("REV", "COS", "GRP", "EXP", "INC", "EBITDA", "OIN", "OEXP", "NEP")


class GhDashboardConfigAccounting(models.Model):
    _inherit = "gh.dashboard.config"

    pl_report_id = fields.Many2one(
        "account.report", string="P&L report",
        help="Odoo P&L (or a variant of it) the Budget dashboard reads. Empty = Odoo's standard Profit and Loss.")
    budget_id = fields.Many2one(
        "account.report.budget", string="Approved budget",
        help="Odoo report budget (Accounting > Reporting > Profit and Loss > Budget) shown as the budget column.")
    forecast_budget_id = fields.Many2one(
        "account.report.budget", string="Forecast budget",
        help="Odoo report budget used for the rest of the year in the year-end outlook.")
    ebitda_addback_account_ids = fields.Many2many(
        "account.account", "gh_config_ebitda_addback_rel", "config_id", "account_id",
        string="Depreciation / amortisation above Operating Income",
        help="Added back to Operating Income for the EBITDA line of the GreenHub P&L variant. Odoo already places "
             "'Depreciation' type accounts below Operating Income; list here the ones posted in cost of revenue or "
             "operating expenses (e.g. EV fleet depreciation).")
    default_loss_account_ids = fields.Many2many(
        "account.account", "gh_config_default_loss_rel", "config_id", "account_id",
        string="Default-loss (write-off) accounts", domain="[('account_type', 'like', 'expense')]",
        help="Expense ledger(s) where defaulted balances are written off, e.g. Bad Debts Written Off.")
    loan_account_ids = fields.Many2many(
        "account.account", "gh_config_loan_rel", "config_id", "account_id",
        string="Lender loan accounts", domain="[('account_type', 'like', 'liability')]",
        help="Loan liability accounts. Debits posted to them in a period = principal repaid.")
    loan_interest_account_ids = fields.Many2many(
        "account.account", "gh_config_loan_interest_rel", "config_id", "account_id",
        string="Loan interest & fee accounts", domain="[('account_type', 'like', 'expense')]",
        help="Expense accounts for lender interest and fees. Debits in a period = interest paid or accrued.")

    @api.model
    def _standard_pl(self):
        return self.env.ref("account_reports.profit_and_loss", raise_if_not_found=False)

    def _pl_report(self):
        self.ensure_one()
        return self.pl_report_id or self._standard_pl()

    # ------------------------------------------------------------ EBITDA variant
    def _addback_formula(self):
        return str([("account_id", "in", self.ebitda_addback_account_ids.ids)])

    def action_create_pl_variant(self):
        """Create (once) the GreenHub P&L variant with an EBITDA line, in Odoo's own report configuration."""
        self.ensure_one()
        std = self._standard_pl()
        if not std:
            raise UserError(_("Odoo's Profit and Loss report (Accounting reports) is not installed."))
        Report = self.env["account.report"].sudo()
        # identified by a module xmlid, so finance can rename it without a second copy appearing on upgrade
        variant = self.env.ref(VARIANT_XMLID, raise_if_not_found=False) or \
            Report.search([("root_report_id", "=", std.id), ("name", "=", VARIANT_NAME)], limit=1)
        if not variant:
            variant = std.sudo().copy({"root_report_id": std.id})
            variant.name = VARIANT_NAME  # copy() forces "<name> (copy)"
            # rename the copied codes REV_COPY.. to GH_REV.. (the standard report keeps its own codes)
            mapping = {}
            for line in variant.line_ids:
                if line.code:
                    base = re.sub(r"(_COPY)+$", "", line.code)
                    mapping[line.code] = f"GH_{base}"
            for line in variant.line_ids:
                if line.code in mapping:
                    line.code = mapping[line.code]
            for expr in variant.line_ids.expression_ids.filtered(lambda e: e.engine == "aggregation"):
                formula = f" {expr.formula} "
                for old, new in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
                    formula = re.sub(rf"(?<=\W){re.escape(old)}(?=\W)", new, formula)
                expr.formula = formula.strip()
            inc = variant.line_ids.filtered(lambda l: l.code == "GH_INC")
            seq = inc.sequence if inc else 60
            later = variant.line_ids.filtered(lambda l: l.sequence > seq)
            for line in later:
                line.sequence += 2
            Line = self.env["account.report.line"].sudo()
            Line.create({
                "report_id": variant.id, "name": _("Plus depreciation & amortisation above Operating Income"),
                "code": "GH_DA", "sequence": seq + 1, "hierarchy_level": 1, "groupby": "account_id", "foldable": True,
                "expression_ids": [(0, 0, {"label": "balance", "engine": "domain", "formula": self._addback_formula(),
                                           "subformula": "sum", "date_scope": "strict_range"})],
            })
            Line.create({
                "report_id": variant.id, "name": _("EBITDA"), "code": "GH_EBITDA", "sequence": seq + 2,
                "hierarchy_level": 0,
                "expression_ids": [(0, 0, {"label": "balance", "engine": "aggregation",
                                           "formula": "GH_INC.balance + GH_DA.balance", "date_scope": "strict_range"})],
            })
        module, name = VARIANT_XMLID.split(".")
        if not self.env["ir.model.data"].sudo().search_count([("module", "=", module), ("name", "=", name)]):
            self.env["ir.model.data"].sudo().create({"module": module, "name": name, "model": "account.report",
                                                     "res_id": variant.id, "noupdate": True})
        self.pl_report_id = variant
        self._sync_addback()
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "success", "sticky": False,
            "message": _("'%s' is in Accounting > Reporting > Profit and Loss (variant selector). "
                         "The Budget dashboard now reads it.", VARIANT_NAME)}}

    @api.model
    def _ensure_pl_variant_all_companies(self):
        """Install / upgrade trigger: one GreenHub P&L variant, add-backs suggested when none are set."""
        if not self._standard_pl():
            return
        for company in self.env["res.company"].search([]):
            config = self.with_company(company).with_context(allowed_company_ids=company.ids)._get_config(company)
            if not config.ebitda_addback_account_ids:
                config.action_suggest_addback_accounts()
            config.action_create_pl_variant()

    def _sync_addback(self):
        for config in self:
            report = config.pl_report_id
            line = report.line_ids.filtered(lambda l: l.code == "GH_DA") if report else False
            if line:
                expr = line.expression_ids.filtered(lambda e: e.label == "balance")
                if expr and expr.formula != config._addback_formula():
                    expr.sudo().formula = config._addback_formula()

    def write(self, vals):
        res = super().write(vals)
        if "ebitda_addback_account_ids" in vals:
            self._sync_addback()
        return res

    def action_suggest_addback_accounts(self):
        self.ensure_one()
        accounts = self.env["account.account"].with_company(self.company_id).search([
            ("company_ids", "in", self.company_id.ids),
            ("account_type", "in", ("expense_direct_cost", "expense")),
            "|", "|", ("name", "ilike", "depreciat"), ("name", "ilike", "amorti"), ("name", "ilike", "amortiz")])
        self.ebitda_addback_account_ids = [(6, 0, accounts.ids)]

    def action_suggest_ledgers(self):
        self.ensure_one()
        Account = self.env["account.account"]
        if not self.default_loss_account_ids:
            # what the write-off journal actually posts to (live: 601058 Lease Default), else by name
            used = self.env["account.move.line"].sudo()._read_group(
                [("parent_state", "=", "posted"), ("debit", ">", 0), ("account_id.account_type", "like", "expense"),
                 ("company_id", "=", self.company_id.id), "|", ("journal_id.name", "ilike", "write"),
                 ("journal_id.code", "ilike", "WROFF")], ["account_id"], ["debit:sum"])
            accounts = Account.browse([acc.id for acc, _d in used])
            self.default_loss_account_ids = accounts or Account.search([
                ("account_type", "like", "expense"), "|", "|", ("name", "ilike", "bad debt"),
                ("name", "ilike", "written off"), ("name", "ilike", "lease default")])
        if not self.loan_account_ids:
            self.loan_account_ids = Account.search([("account_type", "like", "liability"), ("name", "ilike", "loan")])


class GhKpiServiceAccounting(models.AbstractModel):
    _inherit = "gh.kpi.service"

    # ------------------------------------------------------------ Odoo P&L engine
    def _pl_options(self, report, date_from, date_to, budget=None):
        prev = {"date": {"date_from": fields.Date.to_string(date_from), "date_to": fields.Date.to_string(date_to),
                         "filter": "custom", "mode": "range"},
                "budgets": [{"id": budget.id, "selected": True}] if budget else []}
        return report.with_company(self.env.company).get_options(prev)

    def _pl_read(self, date_from, date_to, budget=None):
        """{code: {"line_id", "name", "level", "actual", "budget", "dict_id", "actual_key"}} straight from Odoo's P&L."""
        config = self.env["gh.dashboard.config"]._get_config()
        report = config._pl_report()
        if not report:
            return {}, None, None
        options = self._pl_options(report, date_from, date_to, budget)
        out = {}
        for line in report._get_lines(options):
            model, res_id = report._get_model_info_from_id(line["id"])
            if model != "account.report.line" or report._parse_line_id(line["id"])[-1][0]:
                continue  # only the report's own lines, not unfolded accounts or totals
            rline = self.env["account.report.line"].browse(res_id)
            actual = budget_val = None
            actual_key = None
            for col in line["columns"]:
                group = options["column_groups"].get(col.get("column_group_key"), {}).get("forced_options", {})
                if col.get("figure_type") == "percentage" or group.get("budget_percentage"):
                    continue
                value = col.get("no_format")
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue  # e.g. the budget % column ("0.0%") shares the budget's column group
                if group.get("compute_budget"):
                    budget_val = value
                else:
                    actual, actual_key = value, col.get("column_group_key")
            key = re.sub(r"^GH_", "", rline.code or f"line{rline.id}")
            out[key] = {"line_id": rline.id, "name": line["name"], "level": rline.hierarchy_level,
                        "sequence": rline.sequence, "actual": actual or 0.0,
                        "budget": budget_val if budget else None, "dict_id": line["id"], "actual_key": actual_key}
        return out, report, options

    # ------------------------------------------------------------ ledger sums on accounts picked in settings
    def _ledger_sum(self, accounts, date_from, date_to, side="balance"):
        if not accounts:
            return None
        field = {"balance": "balance:sum", "debit": "debit:sum", "credit": "credit:sum"}[side]
        rows = self.env["account.move.line"].sudo()._read_group(
            [("account_id", "in", accounts.ids), ("parent_state", "=", "posted"), ("date", ">=", date_from),
             ("date", "<=", date_to), ("company_id", "=", self.env.company.id)], [], [field])
        return rows[0][0] or 0.0
