from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestRidersKpis(TransactionCase):
    """Riders & Customers KPIs on a small, fully known fixture."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, mail_notrack=True))
        cls.today = fields.Date.context_today(cls.env["gh.kpi.service"])
        cls.service = cls.env["gh.kpi.service"]

        # Start from a clean configuration so seed data can't skew the counts.
        cls.env["gh.product.group"].search([]).write({"active": False})
        cls.env["gh.vehicle.category.rule"].search([]).write({"active": False})

        brand = cls.env["fleet.vehicle.model.brand"].create({"name": "TestBrand"})
        cls.model_a = cls.env["fleet.vehicle.model"].create({"name": "Alpha", "brand_id": brand.id})
        cls.model_b = cls.env["fleet.vehicle.model"].create({"name": "Beta", "brand_id": brand.id})
        cls.product_a = cls.env["product.product"].create({"name": "Lease A"})
        cls.product_b = cls.env["product.product"].create({"name": "Lease B"})
        cls.product_x = cls.env["product.product"].create({"name": "Unmapped lease"})
        cls.group_a = cls.env["gh.product.group"].create({
            "name": "Group A", "color_slot": "zembo",
            "product_ids": [(6, 0, cls.product_a.ids)], "vehicle_model_ids": [(6, 0, cls.model_a.ids)]})
        cls.group_b = cls.env["gh.product.group"].create({
            "name": "Group B", "color_slot": "iqube",
            "product_ids": [(6, 0, cls.product_b.ids)], "vehicle_model_ids": [(6, 0, cls.model_b.ids)]})

        cls.tag_test = cls.env["fleet.vehicle.tag"].create({"name": "Test bike (fixture)"})
        Rule = cls.env["gh.vehicle.category.rule"]
        Rule.create({"name": "contract", "sequence": 1, "category": "on_contract", "on_active_contract": True})
        Rule.create({"name": "test", "sequence": 5, "category": "test", "tag_ids": [(6, 0, cls.tag_test.ids)]})
        Rule.create({"name": "available", "sequence": 80, "category": "available", "vehicle_states": "available"})

        def vehicle(model, state="available", tags=None):
            vals = {"model_id": model.id}
            v = cls.env["fleet.vehicle"].create(vals)
            v.write({"state": state, "tag_ids": [(6, 0, tags or [])]})
            return v

        cls.v1 = vehicle(cls.model_a, "active")
        cls.v2 = vehicle(cls.model_a, "available")           # tagged test, but on a contract
        cls.v2.tag_ids = [(6, 0, cls.tag_test.ids)]
        cls.v3 = vehicle(cls.model_b, "available")           # new, never contracted
        cls.v4 = vehicle(cls.model_b, "available")           # re-financing: had a closed contract
        cls.v5 = vehicle(cls.model_a, "available", cls.tag_test.ids)  # test bike, excluded
        cls.v6 = vehicle(cls.model_b, "active")

        def rider(first, gender, age_years):
            dob = cls.today - relativedelta(years=age_years) if age_years is not None else False
            return cls.env["rider"].create({"first_name": first, "last_name": "Fixture",
                                            "gender": gender, "date_of_birth": dob})

        cls.r_young_f = rider("Ann", "female", 25)
        cls.r_old_m = rider("Bob", "male", 40)
        cls.r_young_m = rider("Cid", "male", 34)
        cls.r_no_dob = rider("Dee", "female", None)
        cls.r_closed = rider("Eve", "male", 30)

        def contract(r, product, bike, state):
            c = cls.env["rider.contract"].create({"rider_id": r.id, "product_product_id": product.id,
                                                   "bike_id": bike.id if bike else False})
            c.write({"state": state, "contract_start_date": cls.today - timedelta(days=10)})
            return c

        cls.c1 = contract(cls.r_young_f, cls.product_a, cls.v1, "running")
        cls.c2 = contract(cls.r_old_m, cls.product_a, cls.v2, "pause")
        cls.c3 = contract(cls.r_young_m, cls.product_b, cls.v6, "running")
        cls.c3b = contract(cls.r_young_m, cls.product_b, False, "running")   # second contract, same rider
        cls.c4 = contract(cls.r_no_dob, cls.product_x, False, "running")     # unmapped product
        cls.c5 = contract(cls.r_closed, cls.product_b, cls.v4, "closed")

        # Restrict every count to this fixture so existing data in the db can't interfere.
        cls.fixture_riders = cls.r_young_f | cls.r_old_m | cls.r_young_m | cls.r_no_dob | cls.r_closed
        cls.fixture_vehicles = cls.v1 | cls.v2 | cls.v3 | cls.v4 | cls.v5 | cls.v6

    def _fixture_only(self):
        """Archive anything outside the fixture for the duration of the test."""
        others = self.env["rider.contract"].search([("rider_id", "not in", self.fixture_riders.ids),
                                                     ("state", "in", ("running", "pause"))])
        others.write({"state": "draft"})
        self.env["fleet.vehicle"].search([("id", "not in", self.fixture_vehicles.ids)]).write({"active": False})

    def test_active_riders_and_demographics(self):
        self._fixture_only()
        core = self.service._riders_core(self.today, None)
        self.assertEqual(core["active_riders"]["value"], 4, "distinct riders on running/pause contracts")
        self.assertEqual(core["active_contracts"]["value"], 5)
        self.assertEqual(core["active_riders"]["paused"], 1)
        self.assertEqual(core["women"]["value"], 2)
        self.assertEqual(core["men"]["value"], 2)
        self.assertEqual(core["youth"]["value"], 2, "25 and 34 are under 35; 40 and no-DOB are not")
        self.assertEqual(core["youth"]["no_dob"], 1)
        buckets = {r["key"]: r["count"] for r in core["gender_age"]}
        self.assertEqual(buckets, {"m_u": 1, "f_u": 1, "m_o": 1, "f_o": 0, "unknown": 1})
        self.assertEqual(sum(buckets.values()), 4)
        self.assertEqual(core["multi_contract_riders"], [self.r_young_m.id])

    def test_products_and_unmapped_warning(self):
        self._fixture_only()
        core = self.service._riders_core(self.today, None)
        rows = {r["label"]: r["count"] for r in core["by_product"]}
        self.assertEqual(rows["Group A"], 2)
        self.assertEqual(rows["Group B"], 1)
        unmapped = [r for r in core["by_product"] if r.get("warn")]
        self.assertEqual(len(unmapped), 1)
        self.assertEqual(unmapped[0]["count"], 1)
        checks = {c["code"]: c for c in self.service._riders_checks(dict(core, ok=True), {"ok": False})}
        self.assertTrue(checks["R05"]["ok"])
        self.assertFalse(checks["R08"]["ok"], "an unmapped product must fail the R08 check")
        self.assertTrue(checks["P01"]["ok"])

    def test_product_filter(self):
        self._fixture_only()
        core = self.service._riders_core(self.today, self.group_b.id)
        self.assertEqual(core["active_riders"]["value"], 1)

    def test_vehicle_categories(self):
        self._fixture_only()
        fleet = self.service._fleet(self.today, None)
        self.assertEqual(fleet["fleet_total"], 5, "test bike v5 excluded; v2 is on contract so not a test bike")
        self.assertEqual(fleet["test_excluded"], 1)
        self.assertEqual(fleet["on_contract"]["value"], 3)
        self.assertEqual(fleet["unassigned"]["value"], 2)
        self.assertEqual(fleet["unassigned"]["new"], 1)
        self.assertEqual(fleet["unassigned"]["refinancing"], 1)
        self.assertEqual(sum(r["total"] for r in fleet["matrix"]["rows"]), fleet["fleet_total"])
        self.assertEqual(fleet["uncategorised"], 0)

    def test_licences(self):
        self._fixture_only()
        self.r_young_f.license_end_date = self.today + timedelta(days=5)
        self.r_old_m.license_end_date = self.today - timedelta(days=1)
        self.r_young_m.license_end_date = self.today + timedelta(days=200)
        safety = self.service._safety(self.today, None)
        counts = {k: v["count"] for k, v in safety["licences"]["counts"].items()}
        self.assertEqual(counts["expiring"], 1)
        self.assertEqual(counts["expired"], 1)
        self.assertEqual(counts["valid"], 1)
        self.assertEqual(sum(counts.values()), 4)
        self.assertEqual(safety["licences"]["expiring"][0]["days_left"], 5)

    def test_dashboard_payload_and_access(self):
        self._fixture_only()
        payload = self.service.get_riders_dashboard()
        for key in ("core", "fleet", "referrals", "safety", "history"):
            self.assertTrue(payload[key]["ok"], f"panel {key} failed: {payload[key].get('error')}")
        outsider = new_test_user(self.env, login="gh_outsider", groups="base.group_user")
        with self.assertRaises(AccessError):
            self.service.with_user(outsider).get_riders_dashboard()

    def test_snapshot_upsert_is_idempotent(self):
        Snapshot = self.env["gh.kpi.snapshot"]
        end = self.today
        rows = [("R01", "", 0.0, 7)]
        Snapshot._upsert(self.env.company, "week", end - timedelta(days=6), end, rows, "manual")
        Snapshot._upsert(self.env.company, "week", end - timedelta(days=6), end, [("R01", "", 0.0, 9)], "manual")
        snaps = Snapshot.search([("metric_code", "=", "R01"), ("period_end", "=", end), ("period_type", "=", "week")])
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps.value_count, 9)
