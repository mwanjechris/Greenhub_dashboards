"""Every figure must open its records: drill specs in the payloads resolve, and lists add up to the figure."""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


def _specs(node, path=""):
    """Yield (path, spec) for every {kind, args} drill spec in a dashboard payload."""
    if isinstance(node, dict):
        if "kind" in node and "args" in node and isinstance(node["args"], dict):
            yield path, node
            return
        for key, value in node.items():
            yield from _specs(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _specs(value, f"{path}[{i}]")


@tagged("post_install", "-at_install")
class TestDrill(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.svc = cls.env["gh.kpi.service"]
        cls.today = fields.Date.context_today(cls.svc)
        cls.revenue = cls.env["account.account"].search(
            [("account_type", "=", "income"), ("company_ids", "in", cls.env.company.id)], limit=1)
        if cls.revenue:
            cls.env["gh.account.mapping"].search([("role", "=", "revenue_lease"),
                                                  ("company_id", "=", cls.env.company.id)]).unlink()
            cls.env["gh.account.mapping"].create({"role": "revenue_lease", "account_ids": [(6, 0, cls.revenue.ids)]})

    def _assert_action(self, action, where):
        self.assertTrue(action and action.get("type"), f"{where}: no action")
        if action["type"] == "ir.actions.act_window":
            self.assertTrue(action.get("res_model"), where)
            self.assertTrue(action.get("views"), f"{where}: act_window without views would not open")

    def test_budget_payload_specs_all_resolve(self):
        data = self.svc.get_budget_dashboard(period="ytd")
        specs = list(_specs(data))
        self.assertGreater(len(specs), 20, "P&L lines, tiles, months and ops rows all carry drills")
        for path, spec in specs:
            self._assert_action(self.svc.get_drill(spec["kind"], spec["args"]), path)

    def test_pl_drill_adds_up_to_the_figure(self):
        if not self.revenue:
            self.skipTest("no income account")
        data = self.svc.get_budget_dashboard(period="ytd")
        line = next(l for l in data["pl"]["lines"] if l["label"] == "Lease interest & fees")
        action = self.svc.get_drill(line["drill"]["kind"], line["drill"]["args"])
        lines = self.env["account.move.line"].search(action["domain"])
        self.assertAlmostEqual(-sum(lines.mapped("balance")), line["actual"] or 0.0, places=2)

    def test_report_links(self):
        frm, to = (self.today.replace(month=1, day=1), self.today)
        for key in ("pl", "gl", "bs", "ar"):
            action = self.svc.get_drill("report", {"report": key, "date_from": fields.Date.to_string(frm),
                                                   "date_to": fields.Date.to_string(to)})
            self._assert_action(action, key)
            if action["type"] == "ir.actions.client":
                date = action["params"]["options"]["date"]
                self.assertEqual((date["date_from"], date["date_to"]), (fields.Date.to_string(frm), fields.Date.to_string(to)))
                self.assertTrue(action["params"]["ignore_session"], "dates must win over the user's last report filter")

    def test_collections_drills_match(self):
        data = self.svc.get_collections_dashboard(period="this_month")
        core = data["core"]
        p = core["period"]
        action = self.svc.get_drill("receipts", {"date_from": p["from"], "date_to": p["to"]})
        self.assertEqual(len(action["domain"][0][2]), core["count"])
        lease = self.svc.get_drill("receipts", {"date_from": p["from"], "date_to": p["to"], "categories": ["lease"]})
        logs = self.env["payment.log"].browse(lease["domain"][0][2])
        self.assertAlmostEqual(sum(logs.mapped("amount")), core["lease"], places=2)
        dues = self.svc.get_drill("dues", {"date_from": p["from"], "date_to": p["to"], "lease_only": True})
        self.assertEqual(sorted(dues["domain"][0][2]), sorted(core["due_domain"][0][2]))
        m = data["by_model"]
        for row in m["rows"]:
            got = self.svc.get_drill("receipts", {"date_from": m["from"], "date_to": m["to"], "instalment_only": True,
                                                  "group_id": row["group_id"]})
            amount = sum(self.env["payment.log"].browse(got["domain"][0][2]).mapped("amount"))
            self.assertAlmostEqual(amount, row["collected"], places=2, msg=row["label"])
        for w in data["forecast"]["weeks"][:2]:
            self._assert_action(self.svc.get_drill("dues", {"date_from": w["from"], "date_to": w["to"],
                                                            "active_only": True, "open_only": True}), w["week"])
        self._assert_action(self.svc.get_drill("financing", {"date_from": data["financing"]["from"],
                                                             "date_to": data["financing"]["to"]}), "financing")
        self._assert_action(self.svc.get_drill("available_vehicles", {}), "available")
        self._assert_action(self.svc.get_drill("targets", {"metrics": ["C05"], "dim_prefix": "category:",
                                                           "date_from": p["from"], "date_to": p["to"]}), "targets")

    def test_growth_and_snapshot_drills_match_table(self):
        data = self.svc.get_riders_dashboard()
        trends = data.get("trends") or {}
        if not trends.get("ok") or not trends.get("growth"):
            self.skipTest("no snapshot history in this database")
        row = trends["growth"][-1]
        for part in ("opening", "first_time", "returning", "exits", "closing"):
            action = self.svc.get_drill("growth", {"grain": "week", "period_end": row["end"], "part": part})
            self.assertEqual(len(action["domain"][0][2]), row[part], part)
        snaps = self.svc.get_drill("snapshots", {"period_type": "week", "period_end": row["end"], "is_active": True})
        riders = self.env["gh.contract.snapshot"].browse(snaps["domain"][0][2]).mapped("rider_id")
        self.assertEqual(len(riders), row["closing"])

    def test_portfolio_and_fleet_drills(self):
        data = self.svc.get_portfolio_dashboard()
        core = data["core"]
        action = self.svc.get_drill("contracts", {"keys": ["is_active"]})
        self.assertEqual(len(action["domain"][0][2]), core["active_contracts"]["value"])
        riders = self.svc.get_riders_dashboard()
        fleet = riders["fleet"]
        total = self.svc.get_drill("fleet_cell", {})
        self.assertEqual(len(total["domain"][0][2]), fleet["fleet_total"])
        on_contract = self.svc.get_drill("fleet_cell", {"category": "on_contract"})
        self.assertEqual(len(on_contract["domain"][0][2]), fleet["on_contract"]["value"])
        self._assert_action(self.svc.get_drill("first_time_range", {
            "date_from": fields.Date.to_string(self.today - timedelta(days=90)), "date_to": fields.Date.to_string(self.today)}),
            "first_time_range")
