from odoo.tests import HttpCase, tagged

RENDER_JS = """
    const wait = async (test, what) => {
        for (let i = 0; i < 150; i++) {
            const el = test();
            if (el) { return el; }
            await new Promise((r) => setTimeout(r, 100));
        }
        throw new Error("timed out waiting for " + what);
    };
    (async () => {
        await wait(() => document.querySelector(".gh .gh-title"), "dashboard title");
        if (document.querySelector(".gh .gh-fatal")) { throw new Error("dashboard failed: " + document.querySelector(".gh .gh-fatal").textContent); }
        const errors = [...document.querySelectorAll(".gh .gh-panel-error")].filter((e) => !/Showing the week/.test(e.textContent));
        if (errors.length) { throw new Error("panel error: " + errors[0].textContent); }
        if (!document.querySelectorAll(".gh .gh-tile").length) { throw new Error("no KPI tiles"); }
        const codes = [...document.querySelectorAll(".gh .gh-codes-toggle")][0];
        codes.click();
        await wait(() => document.querySelector(".gh .show-codes"), "KPI codes toggle");
        console.log("test successful");
    })().catch((e) => console.error(e.message));
"""


@tagged("post_install", "-at_install")
class TestDashboardsUi(HttpCase):

    def _open(self, xmlid):
        action = self.env.ref(xmlid)
        self.browser_js(f"/odoo/action-{action.id}", RENDER_JS, login="admin", timeout=120)

    def test_portfolio_renders(self):
        self._open("greenhub_dashboards.action_gh_portfolio_dashboard")

    def test_collections_renders(self):
        self._open("greenhub_dashboards.action_gh_collections_dashboard")

    def test_budget_renders(self):
        self._open("greenhub_dashboards.action_gh_budget_dashboard")
