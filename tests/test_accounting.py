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
        odoo = self._odoo_pl(fields.Date.to_date(period["from"]), fields.Date.to_date(period["to"]),
                             report=self.config._pl_report())
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
        odoo = self._odoo_pl(fields.Date.to_date(period["from"]), fields.Date.to_date(period["to"]),
                             report=self.config._pl_report(), budget=budget)
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

    def test_install_trigger_creates_variant_once(self):
        self.env["gh.dashboard.config"]._ensure_pl_variant_all_companies()
        self.env["gh.dashboard.config"]._ensure_pl_variant_all_companies()
        variants = self.env.ref("greenhub_dashboards.gh_pl_ebitda_variant")
        self.assertEqual(self.env["account.report"].search_count([("name", "=", "GreenHub P&L (EBITDA)")]), 1,
                         "install + upgrade trigger is idempotent")
        self.assertEqual(self.config.pl_report_id, variants)
        codes = set(variants.line_ids.mapped("code"))
        self.assertTrue({"GH_REV", "GH_INC", "GH_DA", "GH_EBITDA", "GH_NEP"} <= codes, codes)
        self.assertEqual(self.env.ref("greenhub_dashboards.gh_pl_ebitda_variant"), variants)
        variants.name = "Renamed by finance"
        self.env["gh.dashboard.config"]._ensure_pl_variant_all_companies()
        self.assertEqual(self.env["account.report"].search_count([("root_report_id", "=", variants.root_report_id.id),
                                                                  ("line_ids.code", "=", "GH_EBITDA")]), 1,
                         "renaming does not create a second variant")
        ebitda = variants.line_ids.filtered(lambda l: l.code == "GH_EBITDA").expression_ids
        self.assertEqual(ebitda.formula, "GH_INC.balance + GH_DA.balance")

    def test_logs_match_payments_by_reference(self):
        used = set(self.env["account.payment"].search([("payment_reference", "!=", False)]).mapped("payment_reference"))
        log = self.env["payment.log"].search([("payment_reference", "!=", False), ("status", "=", "success"),
                                              ("payment_type", "!=", "outbound"), ("payment_reference", "not in", list(used))],
                                             limit=1)
        if not log:
            self.skipTest("no payment log in this database")
        day = log.attempt_date.date()
        before = self.svc._logs_vs_payments(day, day)
        journal = self.env["account.journal"].search([("type", "in", ("bank", "cash")), ("company_id", "=", self.env.company.id)], limit=1)
        partner = log.partner_id or self.env["res.partner"].create({"name": "gh test payer"})
        pay = self.env["account.payment"].create({"payment_type": "inbound", "partner_type": "customer", "partner_id": partner.id,
                                                  "amount": log.amount, "date": day, "journal_id": journal.id,
                                                  "payment_reference": log.payment_reference})
        pay.action_post()
        after = self.svc._logs_vs_payments(day, day)
        self.assertEqual(after["payments"]["count"], before["payments"]["count"] + 1)
        self.assertEqual(after["matched"]["payments"], before["matched"]["payments"] + 1,
                         "matched on payment_reference, as on live (payment_id is never filled there)")
        action = self.svc.get_drill("payments", {"date_from": str(day), "date_to": str(day), "matched": True})
        self.assertIn(pay.id, action["domain"][0][2])

    def test_analytic_budgets_panel_reads_odoo_budgets(self):
        plan = self.env["account.analytic.plan"].create({"name": "GH test plan"})
        acc = self.env["account.analytic.account"].create({"name": "GH test cost centre", "plan_id": plan.id})
        budget = self.env["budget.analytic"].create({"name": "GH test analytic budget", "budget_type": "expense",
                                                     "date_from": self.day.replace(month=1, day=1),
                                                     "date_to": self.day.replace(month=12, day=31)})
        line = self.env["budget.line"].create({"budget_analytic_id": budget.id, plan._column_name(): acc.id,
                                               "budget_amount": 1_000_000})
        budget.action_budget_confirm()
        move = self.env["account.move"].create({
            "move_type": "entry", "journal_id": self.journal.id, "date": self.day,
            "line_ids": [(0, 0, {"account_id": self.interest.id, "debit": 250_000, "name": "gh test",
                                 "analytic_distribution": {str(acc.id): 100}}),
                         (0, 0, {"account_id": self.cash.id, "credit": 250_000, "name": "gh test"})]})
        move.action_post()
        self.env.invalidate_all()  # as a fresh request would: achieved_amount is a non-stored compute
        data = self.svc.get_budget_dashboard(period="ytd")
        panel = data["analytic_budgets"]
        self.assertTrue(panel["ok"], panel)
        row = next(b for b in panel["budgets"] if b["id"] == budget.id)
        got = next(l for l in row["lines"] if l["id"] == line.id)
        self.assertEqual(got["planned"], 1_000_000)
        self.assertAlmostEqual(got["achieved"], 250_000, places=2)
        self.assertAlmostEqual(got["achieved"], line.achieved_amount, places=2, msg="achieved is Odoo's own figure")
        for kind, args in (("budget", {"budget_id": budget.id}), ("budget_report", {"budget_id": budget.id}),
                           ("budget_entries", {"line_id": line.id})):
            action = self.svc.get_drill(kind, args)
            self.assertTrue(action.get("views"), kind)
