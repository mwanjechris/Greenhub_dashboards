import re
from pathlib import Path

from odoo.tests import HttpCase, TransactionCase, tagged

from ..models.gh_kpi_budget import FIN_TILES

TEMPLATES = Path(__file__).resolve().parents[1] / "static" / "src" / "dashboards"


def expand(text):
    """Same rule as expandCodes in gh_help.js: 'R10–R12' -> R10, R11, R12."""
    out = []
    for part in re.split(r"[·,]", text):
        part = part.strip()
        m = re.match(r"^([A-Z])(\d+)\s*[–-]\s*(?:\1)?(\d+)$", part)
        if m:
            out += [f"{m.group(1)}{n:0{len(m.group(2))}d}" for n in range(int(m.group(2)), int(m.group(3)) + 1)]
        elif part:
            out.append(part)
    return out


@tagged("post_install", "-at_install")
class TestGuide(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.guide = cls.env["gh.kpi.service"].get_guide()
        cls.by_key = {e["key"]: e for e in cls.guide["entries"]}

    def test_entries_are_complete_and_unique(self):
        keys = [e["key"] for e in self.guide["entries"]]
        self.assertEqual(len(keys), len(set(keys)), "duplicate guide keys")
        dashboards = {d["key"] for d in self.guide["dashboards"]}
        for e in self.guide["entries"]:
            self.assertIn(e["dash"], dashboards, e["key"])
            for field in ("title", "what", "how"):
                self.assertTrue(e[field].strip(), f"{e['key']} has no {field}")
            self.assertNotIn("%(", " ".join(str(v) for v in e.values()), f"{e['key']} has an unfilled placeholder")

    def test_every_card_on_every_dashboard_has_an_explainer(self):
        """A card is named by data-gh-help, else by its KPI code chip; both must resolve."""
        missing = []
        for path in sorted(TEMPLATES.glob("*_dashboard.xml")):
            xml = path.read_text(encoding="utf-8")
            # every tile, panel and money card must be nameable
            for m in re.finditer(
                    r'<(?:div|button) class="(gh-tile|gh-panel(?: scrollx)?|gh-mcard)"((?:[^>"]|"[^"]*")*)>'
                    r'(\s*<span class="kc"(?:\s+t-esc="[^"]*"/>|>([^<]*)</span>))?', xml):
                attrs, chip_text = m.group(2), m.group(4)
                helped = re.search(r'data-gh-help="([^"]+)"', attrs)
                if helped:
                    keys = expand(helped.group(1))
                elif chip_text:
                    keys = expand(chip_text)
                elif m.group(3):
                    continue  # code set at run time (Budget tiles): checked below
                else:
                    missing.append(f"{path.name}: card without a code near offset {m.start()}")
                    continue
                missing += [f"{path.name}: {k}" for k in keys if k not in self.by_key]
        self.assertFalse(missing, "cards without a guide entry:\n" + "\n".join(missing))

    def test_runtime_codes_and_controls(self):
        runtime = [code for code, *_rest in FIN_TILES] + ["B06", "B07", "B08", "B09", "B10"]
        heroes = ["R01", "P02", "C04", "B05"]
        for key in runtime + heroes:
            self.assertIn(key, self.by_key)
        labels = set()
        for path in TEMPLATES.glob("*_dashboard.xml"):
            labels |= {m.strip().lower() for m in re.findall(r'<div class="gh-f"[^>]*>([^<]+)<', path.read_text(encoding="utf-8"))}
        self.assertTrue(labels)
        for label in labels:
            self.assertIn(f"F:{label}", self.by_key, f"filter '{label}' has no explainer")

    def test_thresholds_come_from_settings(self):
        config = self.env["gh.dashboard.config"]._get_config()
        config.youth_age_limit = 29
        config.licence_notice_days = 45
        entries = {e["key"]: e for e in self.env["gh.kpi.service"].get_guide()["entries"]}
        self.assertIn("29", entries["R04"]["how"])
        self.assertIn("45", entries["R18"]["how"])


HOVER_JS = """
    const wait = async (test, what) => {
        for (let i = 0; i < 150; i++) {
            const el = test();
            if (el) { return el; }
            await new Promise((r) => setTimeout(r, 100));
        }
        throw new Error("timed out waiting for " + what);
    };
    (async () => {
        const tile = await wait(() => document.querySelector(".gh .gh-tile"), "a KPI tile");
        // explainers arrive just after the dashboard: keep hovering until one shows
        let shown = null;
        for (let i = 0; i < 20 && !shown; i++) {
            document.body.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
            tile.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
            await new Promise((r) => setTimeout(r, 700));  // longer than the show delay
            shown = document.querySelector(".gh-help.on");
        }
        if (!shown || !/How it is worked out/.test(shown.textContent)) { throw new Error("explainer has no content: " + (shown && shown.textContent)); }
        document.querySelector(".gh .gh-guide-btn").click();
        await wait(() => document.querySelector(".gh .gg-k"), "the guide page");
        if (document.querySelectorAll(".gh .gg-k").length < 60) { throw new Error("guide lists too few cards"); }
        const search = document.querySelector(".gh .gg-search");
        search.value = "retention";
        search.dispatchEvent(new Event("input", { bubbles: true }));
        await wait(() => document.querySelectorAll(".gh .gg-k").length < 20 && document.querySelector("#gg-k-R11"), "search results");
        console.log("test successful");
    })().catch((e) => console.error(e.message));
"""


@tagged("post_install", "-at_install")
class TestGuideUi(HttpCase):

    def test_hover_explainer_and_guide_page(self):
        action = self.env.ref("Greenhub_dashboards.action_gh_riders_dashboard")
        self.browser_js(f"/odoo/action-{action.id}", HOVER_JS, login="admin", timeout=120)
