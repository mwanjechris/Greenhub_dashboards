from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestRidersDashboardUi(HttpCase):
    """Open the dashboard in a real browser: it must render and its filters must work."""

    def test_riders_dashboard_renders_and_filters(self):
        product = self.env["product.product"].create({"name": "UI lease"})
        group = self.env["gh.product.group"].create({"name": "UI Group", "product_ids": [(6, 0, product.ids)]})
        rider = self.env["rider"].create({"first_name": "Ui", "last_name": "Rider", "gender": "female"})
        contract = self.env["rider.contract"].create({"rider_id": rider.id, "product_product_id": product.id})
        contract.write({"state": "running"})
        action = self.env.ref("greenhub_dashboards.action_gh_riders_dashboard")
        code = """
            const wait = async (test, what) => {
                for (let i = 0; i < 100; i++) {
                    const el = test();
                    if (el) { return el; }
                    await new Promise((r) => setTimeout(r, 100));
                }
                throw new Error("timed out waiting for " + what);
            };
            (async () => {
                await wait(() => document.querySelector(".gh .gh-title"), "dashboard title");
                const tiles = document.querySelectorAll(".gh .gh-tile");
                if (tiles.length < 4) { throw new Error("expected KPI tiles, got " + tiles.length); }
                const active = tiles[0].querySelector(".gh-tile-n").textContent.trim();
                if (!/^[0-9,]+$/.test(active)) { throw new Error("R01 tile is not a number: " + active); }
                const btn = [...document.querySelectorAll(".gh .gh-filters button")].find((b) => b.textContent.trim() === "%(group)s");
                if (!btn) { throw new Error("product filter button missing"); }
                btn.click();
                await wait(() => btn.classList.contains("on"), "filter to apply");
                await wait(() => document.querySelector(".gh .gh-tile .gh-tile-n").textContent.trim() === "1", "filtered R01 = 1");
                console.log("test successful");
            })().catch((e) => console.error(e.message));
        """ % {"group": group.name}
        self.browser_js(f"/odoo/action-{action.id}", code, login="admin", timeout=90)
