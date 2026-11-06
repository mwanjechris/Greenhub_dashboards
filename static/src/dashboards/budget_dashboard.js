/** @odoo-module **/

import { registry } from "@web/core/registry";
import { GhDashboardBase } from "../components/gh_base";

/** Budget, Actuals & Performance (spec 5.4, mockup tab 4). */
export class BudgetDashboard extends GhDashboardBase {
    static template = "greenhub_dashboards.BudgetDashboard";
    method = "get_budget_dashboard";

    initialState() {
        return { versionId: false, budgetId: false, period: "ytd", through: false };
    }

    params() {
        return { version_id: this.state.versionId || false, budget_id: this.state.budgetId || false,
                 period: this.state.period, through: this.state.through || false };
    }

    onThrough(ev) {
        this.set("through", ev.target.value || false);
    }

    monthName(iso) {
        return new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
    }

    get periodName() {
        const to = this.monthName(this.d.period.to);
        return { ytd: `YTD ${to}`, quarter: `QTD ${to}`, month: to }[this.d.period.key];
    }

    tile(code, label, t, unit = "money") {
        const v = t.var || {};
        return { code, label, actual: t.actual, budget: t.budget, v, pill: this.variancePill(v, t.budget, t.actual), unit,
                 drill: t.drill, plan_drill: t.plan_drill, fallback: t.fallback };
    }

    get finTiles() {
        return this.d.pl.tiles.map((t) => this.tile(t.code, t.label, t));
    }

    get heroTile() {
        if (!this.ok("pl")) {
            return null;
        }
        const tiles = this.finTiles;
        return tiles.find((t) => t.code === "B05") || tiles[0] || null;
    }

    get opsTiles() {
        const rows = this.d.operational.rows;
        const pick = (code) => rows.filter((r) => r.code === code);
        const sumRows = (rs) => ({ actual: rs.reduce((a, r) => a + (r.actual || 0), 0),
                                   plan: rs.every((r) => r.plan === null) ? null : rs.reduce((a, r) => a + (r.plan || 0), 0) });
        const fleet = sumRows(pick("B09"));
        fleet.drill = { kind: "fleet_cell", args: { category: "on_contract", label: "Vehicles on contract" } };
        fleet.plan_drill = { kind: "targets", args: { version_id: this.d.version ? this.d.version.id : false, metrics: ["B09"], point_on: this.d.as_of, label: "Fleet deployment plan" } };
        const out = [];
        for (const r of [pick("B07")[0], pick("B08")[0], { code: "B09", label: "Fleet deployed", actual: fleet.actual, plan: fleet.plan, direction: "up", unit: "count", drill: fleet.drill, plan_drill: fleet.plan_drill }, pick("B10")[0]]) {
            const v = r.variance || this.localVariance(r.actual, r.plan, r.direction);
            out.push({ code: r.code, label: r.label, actual: r.actual, budget: r.plan, v, pill: this.variancePill(v, r.plan, r.actual), unit: r.unit, note: r.note,
                       drill: r.drill, plan_drill: r.plan_drill });
        }
        return out;
    }

    localVariance(actual, plan, direction) {
        if (actual === null || actual === undefined || plan === null || plan === undefined) {
            return { favourable: null };
        }
        const diff = actual - plan;
        return { abs: diff, pct: plan ? (100 * diff) / Math.abs(plan) : null, favourable: direction === "up" ? diff >= 0 : diff <= 0 };
    }

    fmtVal(v, unit) {
        if (v === null || v === undefined) {
            return "—";
        }
        return unit === "count" ? this.fmtInt(v) : this.fmtMoney(v);
    }

    get revenueChart() {
        const rows = this.d.revenue_by_month.rows;
        return { labels: rows.map((r) => r.month), h: 200, yFmt: (v) => this.fmtMoney(v), tipFmt: (v) => this.fmtInt(v),
                 targets: rows.map((r) => r.budget), targetStyle: { name: "Budget", color: getComputedStyle(document.body).getPropertyValue("--gh-amber") || "#B0751A", dash: "4 3" },
                 series: [{ name: "Actual", values: rows.map((r) => r.actual || 0), color: "--gh-slate" }],
                 onClick: (i) => this.go(rows[i].drill) };
    }

    get hasActuals() {
        return this.ok("pl") && this.d.pl.lines.length > 0;
    }

    outlookWidth(v) {
        const o = this.d.outlook;
        const base = Math.max(Math.abs(o.approved_full_year || 0), Math.abs((o.actual_ytd || 0) + (o.forecast_rest || 0)), 1);
        return Math.max(0, Math.min(100, (100 * Math.abs(v || 0)) / base));
    }

    openLine(line) {
        this.go(line.drill);
    }
}

registry.category("actions").add("gh_dashboards.budget", BudgetDashboard);
