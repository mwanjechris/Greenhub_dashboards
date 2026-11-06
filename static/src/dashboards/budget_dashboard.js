/** @odoo-module **/

import { registry } from "@web/core/registry";
import { GhDashboardBase } from "../components/gh_base";

/** Budget, Actuals & Performance (spec 5.4, mockup tab 4). */
export class BudgetDashboard extends GhDashboardBase {
    static template = "greenhub_dashboards.BudgetDashboard";
    method = "get_budget_dashboard";

    initialState() {
        return { versionId: false, period: "ytd", through: false };
    }

    params() {
        return { version_id: this.state.versionId || false, period: this.state.period, through: this.state.through || false };
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
        return { code, label, actual: t.actual, budget: t.budget, v, pill: this.variancePill(v), unit };
    }

    get finTiles() {
        const t = this.d.pl.tiles;
        return [this.tile("B03", "Revenue", t.revenue), this.tile("B04", "Expenses", t.expenses),
                this.tile("B05", "EBITDA", t.ebitda), this.tile("B11", "Financing costs", t.financing)];
    }

    get opsTiles() {
        const rows = this.d.operational.rows;
        const pick = (code) => rows.filter((r) => r.code === code);
        const sumRows = (rs) => ({ actual: rs.reduce((a, r) => a + (r.actual || 0), 0),
                                   plan: rs.every((r) => r.plan === null) ? null : rs.reduce((a, r) => a + (r.plan || 0), 0) });
        const fleet = sumRows(pick("B09"));
        const out = [];
        for (const r of [pick("B07")[0], pick("B08")[0], { code: "B09", label: "Fleet deployed", actual: fleet.actual, plan: fleet.plan, direction: "up", unit: "count" }, pick("B10")[0]]) {
            const v = r.variance || this.localVariance(r.actual, r.plan, r.direction);
            out.push({ code: r.code, label: r.label, actual: r.actual, budget: r.plan, v, pill: this.variancePill(v), unit: r.unit, note: r.note });
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
                 series: [{ name: "Actual", values: rows.map((r) => r.actual || 0), color: "--gh-slate" }] };
    }

    get hasActuals() {
        return this.ok("pl") && this.d.pl.mapped_roles.length > 0;
    }

    outlookWidth(v) {
        const o = this.d.outlook;
        const base = Math.max(Math.abs(o.approved_full_year || 0), Math.abs((o.actual_ytd || 0) + (o.forecast_rest || 0)), 1);
        return Math.max(0, Math.min(100, (100 * Math.abs(v || 0)) / base));
    }

    openLine(line) {
        if (line.domain) {
            this.open("account.move.line", line.domain, line.label);
        }
    }
}

registry.category("actions").add("gh_dashboards.budget", BudgetDashboard);
