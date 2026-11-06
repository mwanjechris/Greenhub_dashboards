"""Financial figures must equal Odoo accounting: the P&L report, report budgets and posted journal items."""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAccountingAlignment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.svc = cls.env["gh.kpi.service"]
        cls.config = cls.env["gh.dashboard.config"]._get_config()
        today = fields.Date.context_today(cls.svc)
        cls.last_month_end = today.replace(day=1) - timedelta(days=1)
        cls.day = cls.last_month_end.replace(day=15)
        Account = cls.env["account.account"]
        mk = lambda code, name, kind: Account.create({"code": code, "name": name, "account_type": kind})
        cls.income = mk("GHT4001", "GH test lease income", "income")
        cls.ev_dep = mk("GHT5001", "GH test EV depreciation", "expense_direct_cost")
        cls.bad_debt = mk("GHT5002", "GH test bad debts written off", "expense")
        cls.loan = mk("GHT2001", "GH test lender loan", "liability_non_current")
        cls.interest = mk("GHT5003", "GH test loan interest", "expense")
        cls.cash = mk("GHT1001", "GH test clearing", "asset_current")
        cls.journal = cls.env["account.journal"].search([("type", "=", "general"), ("company_id", "=", cls.env.company.id)], limit=1)

    def _post(self, lines, date=None):
        move = self.env["account.move"].create({
            "move_type": "entry", "journal_id": self.journal.id, "date": date or self.day,
            "line_ids": [(0, 0, {"account_id": acc.id, "debit": max(amt, 0), "credit": max(-amt, 0), "name": "gh test"})
                         for acc, amt in lines]})
        move.action_post()
        return move

    def _pl(self, **kw):
        data = self.svc.get_budget_dashboard(period="ytd", **kw)
        self.assertTrue(data["pl"]["ok"], data["pl"])
        return {l["key"]: l for l in data["pl"]["lines"]}, data

    def _odoo_pl(self, date_from, date_to, report=None, budget=None):
        report = report or self.env.ref("account_reports.profit_and_loss")
        options = report.get_options({"date": {"date_from": fields.Date.to_string(date_from), "date_to": fields.Date.to_string(date_to),
                                               "filter": "custom", "mode": "range"},
                                      "budgets": [{"id": budget.id, "selected": True}] if budget else []})
        out = {}
        for line in report._get_lines(options):
            model, res_id = report._get_model_info_from_id(line["id"])
            if model == "account.report.line" and not report._parse_line_id(line["id"])[-1][0]:
                code = self.env["account.report.line"].browse(res_id).code
                out[code.replace("GH_", "")] = [c.get("no_format") for c in line["columns"]]
        return out

    def test_pl_equals_odoo_report_and_moves_with_postings(self):
        before, data = self._pl()
        self._post([(self.income, -1_000_000), (self.ev_dep, 200_000), (self.cash, 800_000)])
        after, data = self._pl()
        period = data["period"]
        odoo = self._odoo_pl(fields.Date.to_date(period["from"]), fields.Date.to_date(period["to"]))
        for key, line in after.items():
            self.assertAlmostEqual(line["actual"], odoo[key][0] or 0.0, places=2, msg=f"{key} must equal Odoo's P&L")
        self.assertAlmostEqual(after["REV"]["actual"] - before["REV"]["actual"], 1_000_000, places=2)
        self.assertAlmostEqual(after["NEP"]["actual"] - before["NEP"]["actual"], 800_000, places=2)
        # the cell drill is Odoo's own audit and finds the posted line
        action = self.svc.get_drill(after["REV"]["drill"]["kind"], after["REV"]["drill"]["args"])
        lines = self.env["account.move.line"].search(action["domain"])
        self.assertIn(self.income, lines.account_id)

    def test_ebitda_variant_is_operating_income_plus_addbacks(self):
        self.config.action_create_pl_variant()
        self.config.ebitda_addback_account_ids = [(6, 0, self.ev_dep.ids)]
        variant = self.config.pl_report_id
        self.assertEqual(variant.root_report_id, self.env.ref("account_reports.profit_and_loss"))
        self.assertEqual(variant.name, "GreenHub P&L (EBITDA)")
        before, _d = self._pl()
        self._post([(self.income, -1_000_000), (self.ev_dep, 200_000), (self.cash, 800_000)])
        after, data = self._pl()
        self.assertAlmostEqual(after["INC"]["actual"] - before["INC"]["actual"], 800_000, places=2)
        self.assertAlmostEqual(after["EBITDA"]["actual"] - before["EBITDA"]["actual"], 1_000_000, places=2,
                               msg="EBITDA adds the depreciation back")
        period = data["period"]
        std = self._odoo_pl(fields.Date.to_date(period["from"]), fields.Date.to_date(period["to"]))
        self.assertAlmostEqual(after["NEP"]["actual"], std["NEP"][0] or 0.0, places=2,
                               msg="the variant's Net Profit equals Odoo's standard P&L")
        tile = next(t for t in data["pl"]["tiles"] if t["code"] == "B05")
        self.assertFalse(tile["fallback"])
        self.config.action_create_pl_variant()  # idempotent
        self.assertEqual(self.env["account.report"].search_count([("name", "=", variant.name)]), 1)

    def test_budget_column_is_odoo_report_budget(self):
        budget = self.env["account.report.budget"].create({"name": "GH test budget"})
        self.env["account.report.budget.item"].create({"budget_id": budget.id, "account_id": self.income.id,
                                                       "amount": -500_000, "date": self.day.replace(day=1)})
        before, _d = self._pl()
        lines, data = self._pl(budget_id=budget.id)
        period = data["period"]
        odoo = self._odoo_pl(fields.Date.to_date(period["from"]), fields.Date.to_date(period["to"]), budget=budget)
        self.assertAlmostEqual(lines["REV"]["budget"], odoo["REV"][1], places=2)
        self.assertGreaterEqual(lines["REV"]["budget"], 500_000 - 0.01)

    def test_default_losses_and_lender_repayments_from_ledgers(self):
        self.config.write({"default_loss_account_ids": [(6, 0, self.bad_debt.ids)],
                           "loan_account_ids": [(6, 0, self.loan.ids)],
                           "loan_interest_account_ids": [(6, 0, self.interest.ids)]})
        self._post([(self.bad_debt, 50_000), (self.cash, -50_000)])
        self._post([(self.loan, 300_000), (self.interest, 40_000), (self.cash, -340_000)])
        portfolio = self.svc.get_portfolio_dashboard()
        self.assertTrue(portfolio["defaults"]["ok"])
        self.assertAlmostEqual(portfolio["defaults"]["losses_ytd"], 50_000, places=2)
        coll = self.svc.get_collections_dashboard()
        fin = coll["financing"]
        self.assertTrue(fin["ok"] and fin["has_data"])
        self.assertAlmostEqual(fin["principal"], 300_000, places=2)
        self.assertAlmostEqual(fin["interest"], 40_000, places=2)
        action = self.svc.get_drill("ledger", {"account_ids": self.loan.ids, "date_from": fin["from"], "date_to": fin["to"],
                                               "side": "debit"})
        self.assertAlmostEqual(sum(self.env["account.move.line"].search(action["domain"]).mapped("debit")), 300_000, places=2)

    def test_logs_vs_payments_counts_odoo_payments(self):
        coll = self.svc.get_collections_dashboard()
        lp = coll["logs_vs_payments"]
        self.assertTrue(lp["ok"])
        p = coll["core"]["period"]
        action = self.svc.get_drill("payments", {"date_from": p["from"], "date_to": p["to"]})
        self.assertEqual(len(action["domain"][0][2]), lp["payments"]["count"])
        self.assertAlmostEqual(lp["difference"], lp["logs"]["amount"] - lp["payments"]["amount"], places=2)
