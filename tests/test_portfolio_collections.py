import base64
import io
from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPortfolioCollections(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, mail_notrack=True))
        cls.today = fields.Date.context_today(cls.env["gh.kpi.service"])
        cls.history = cls.env["gh.history.service"]
        cls.config = cls.env["gh.dashboard.config"]._get_config()
        cls.config.write({"risk_band_basis": "instalments", "default_scope": "episode", "band_ontrack": 0.1267,
                          "band_norisk": 0.3801, "band_low": 0.9501, "band_atrisk": 1.2668, "band_high": 2.0269,
                          "par_1": 7, "par_2": 14, "par_3": 21})

    # ---------------------------------------------------------------- classification
    def test_risk_bands_instalment_multiples(self):
        risk = lambda ps, arrears, inst=78940, dflt=False: self.history._risk_category(ps, arrears, inst, dflt, self.config)
        self.assertEqual(risk("ahead", 0), "ahead")
        self.assertEqual(risk("ontrack", 50000), "ontrack", "payment status On track wins")
        self.assertEqual(risk("behind", 10000), "ontrack", "<= 0.127 x 78,940 = 10,025")
        self.assertEqual(risk("behind", 30000), "norisk")
        self.assertEqual(risk("behind", 75000), "low")
        self.assertEqual(risk("behind", 100000), "atrisk")
        self.assertEqual(risk("behind", 160000), "high")
        self.assertEqual(risk("behind", 236820), "critical", "the spreadsheet's gap above 236,820 now lands in Critical")
        self.assertEqual(risk("behind", 999999), "critical")
        self.assertEqual(risk("behind", 999999, dflt=True), "default")
        # an iQube instalment scales the same bands
        self.assertEqual(risk("behind", 20000, inst=200000), "ontrack")
        self.assertEqual(risk("behind", 30000, inst=200000), "norisk")

    def test_par_buckets(self):
        par = lambda dpd: self.history._par_bucket(dpd, self.config)
        self.assertEqual([par(0), par(1), par(7), par(8), par(14), par(15), par(21), par(22), par(90)],
                         ["par0", "par7", "par7", "par14", "par14", "par21", "par21", "par28", "par28"])

    def test_default_scope(self):
        rider = self.env["rider"].create({"first_name": "D", "last_name": "Scope"})
        c = self.env["rider.contract"].create({"rider_id": rider.id})
        c.write({"state": "terminated"})
        self.env["default.tracking"].create({"contract_id": c.id, "date": self.today, "state": "ongoing"})
        ids = self.history._in_default_ids({c.id: "terminated"}, {c.id: "behind"}, self.config)
        self.assertIn(c.id, ids, "episode scope: terminated after a default, not written off")
        self.config.default_scope = "payment_state"
        self.assertNotIn(c.id, self.history._in_default_ids({c.id: "terminated"}, {c.id: "behind"}, self.config))
        self.config.default_scope = "episode"

    # ---------------------------------------------------------------- collections
    def test_payment_categories_and_check(self):
        rider = self.env["rider"].create({"first_name": "P", "last_name": "Cat"})
        contract = self.env["rider.contract"].create({"rider_id": rider.id})
        Log = self.env["payment.log"]
        when = datetime.combine(self.today, datetime.min.time()) + timedelta(hours=9)
        base = {"status": "success", "payment_type": "inbound", "attempt_date": when, "contract_id": contract.id}
        logs = Log.create([dict(base, amount=100, payment_reference="t-l", request_data='{"memo": "LEASE - MOBILE_MONEY - UXX1"}'),
                           dict(base, amount=50, payment_reference="t-s", request_data='{"memo": "SWAP"}'),
                           dict(base, amount=7, payment_reference="t-x", request_data='{"memo": "MYSTERY"}')])
        classify = self.env["gh.payment.category.rule"]._classifier()
        cats = {l.payment_reference: classify(l) for l in logs}
        self.assertEqual(cats, {"t-l": "lease", "t-s": "swap", "t-x": "other"})
        service = self.env["gh.kpi.service"]
        amounts, _ids = service._by_category(logs)
        self.assertEqual(amounts["lease"], 100)
        core = {"ok": True, "categories": [{"actual": v} for v in amounts.values()], "total": 157,
                "count": 3, "unmapped_count": 1}
        check = service._collections_checks(core)[0]
        self.assertFalse(check["ok"], "an unmapped receipt must fail C04")

    # ---------------------------------------------------------------- history
    def test_tracked_state_reconstruction_and_growth(self):
        rider = self.env["rider"].create({"first_name": "H", "last_name": "Ist"})
        contract = self.env["rider.contract"].create({"rider_id": rider.id})
        contract.write({"state": "running"})
        field = self.env["ir.model.fields"]._get("rider.contract", "state")
        msg = self.env["mail.message"].create({"model": "rider.contract", "res_id": contract.id,
                                               "message_type": "notification",
                                               "date": datetime.combine(self.today - timedelta(days=20), datetime.min.time())})
        self.env["mail.tracking.value"].create({"mail_message_id": msg.id, "field_id": field.id,
                                                "old_value_char": "Deposit", "new_value_char": "Running"})
        self.env.cr.execute("UPDATE rider_contract SET create_date = %s WHERE id = %s",
                            (datetime.combine(self.today - timedelta(days=40), datetime.min.time()), contract.id))
        contract.invalidate_recordset(["create_date"])
        d_before, d_after = self.today - timedelta(days=30), self.today - timedelta(days=10)
        values = self.history._tracked_values_at("rider.contract", "state", contract, [d_before, d_after])
        self.assertEqual(values[(contract.id, d_before)], "deposit", "before the first change: its old value, label mapped to key")
        self.assertEqual(values[(contract.id, d_after)], "running")

    def test_growth_identity_from_snapshots(self):
        Snap = self.env["gh.contract.snapshot"]
        Snap.search([]).unlink()
        riders = self.env["rider"].create([{"first_name": f"G{i}", "last_name": "Row"} for i in range(4)])
        contracts = self.env["rider.contract"].create([{"rider_id": r.id} for r in riders])
        e1, e2 = self.today - timedelta(days=14), self.today - timedelta(days=7)
        mk = lambda c, end: {"contract_id": c.id, "rider_id": c.rider_id.id, "period_type": "week", "period_end": end,
                             "is_active": True, "source": "manual"}
        Snap.create([mk(contracts[0], e1), mk(contracts[1], e1), mk(contracts[1], e2), mk(contracts[2], e2), mk(contracts[3], e2)])
        rows = self.env["gh.kpi.service"]._growth_rows("week", None, 10)
        self.assertEqual(len(rows), 1)
        g = rows[0]
        self.assertEqual((g["opening"], g["first_time"], g["returning"], g["exits"], g["closing"]), (2, 2, 0, 1, 3))
        self.assertTrue(g["ok"])
        self.assertEqual(g["retention"], 50.0)

    # ---------------------------------------------------------------- targets and budget
    def _xlsx(self, rows):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["metric_code", "period", "dimension", "value"])
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        return base64.b64encode(buf.getvalue())

    def test_target_import_validation_and_lock(self):
        year = self.today.year
        version = self.env["gh.kpi.target.version"].create({"name": "Test plan", "kind": "original"})
        wizard = self.env["gh.target.import.wizard"].create({"version_id": version.id, "file": self._xlsx([
            ["C05", f"{year}-01", "lease", 1000], ["XX9", f"{year}-01", "", 1], ["C05", f"{year}-01", "lease", 2]])})
        wizard.action_import()
        self.assertIn("unknown metric code", wizard.report)
        self.assertIn("duplicate", wizard.report)
        self.assertFalse(version.line_ids, "nothing is imported while any row is invalid")
        wizard.file = self._xlsx([["C05", f"{year}-{m:02d}", "lease", 3100] for m in range(1, 13)])
        wizard.action_import()
        self.assertEqual(len(version.line_ids), 12)
        version.action_approve()
        self.assertEqual(version.state, "approved")
        with self.assertRaises(UserError):
            version.line_ids[0].value = 1
        with self.assertRaises(UserError):
            version.unlink()
        # monthly target spread by day: January 1-10 = 10/31 of 3,100
        Target = self.env["gh.kpi.target"]
        jan = fields.Date.to_date(f"{year}-01-01")
        self.assertAlmostEqual(Target._value(version, "C05", jan, jan + timedelta(days=9), "category:lease"), 1000.0)

    def test_variance_direction(self):
        v = self.env["gh.kpi.service"]._variance
        self.assertTrue(v(110, 100, "up")["favourable"])
        self.assertFalse(v(110, 100, "down")["favourable"], "costs above budget are unfavourable")
        self.assertEqual(v(110, 100, "up")["pct"], 10.0)
        self.assertIsNone(v(5, 0, "up")["pct"], "budget 0 gives n/a")
        self.assertIsNone(v(None, 100, "up")["favourable"])

    def test_all_dashboards_return_every_panel(self):
        service = self.env["gh.kpi.service"]
        for method in ("get_riders_dashboard", "get_portfolio_dashboard", "get_collections_dashboard", "get_budget_dashboard"):
            payload = getattr(service, method)()
            failed = {k: v.get("error") for k, v in payload.items()
                      if isinstance(v, dict) and v.get("ok") is False and v.get("error") != "live_only"}
            self.assertFalse(failed, f"{method}: {failed}")
