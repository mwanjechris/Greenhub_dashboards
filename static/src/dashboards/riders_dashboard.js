/** @odoo-module **/

import { registry } from "@web/core/registry";
import { GhDashboardBase } from "../components/gh_base";
import { sparkPoints } from "../components/gh_common";

/** Riders & Customers (spec 5.1, mockup tab 1). */
export class RidersDashboard extends GhDashboardBase {
    static template = "greenhub_dashboards.RidersDashboard";
    method = "get_riders_dashboard";

    initialState() {
        return { asOf: false, range: "26w" };
    }

    params() {
        return { product_group_id: this.state.productGroupId || false, grain: this.state.grain,
                 as_of: this.state.asOf || false, range_key: this.state.range };
    }

    onAsOf(ev) {
        this.set("asOf", ev.target.value || false);
    }

    get t() {
        return this.ok("trends") ? this.d.trends : null;
    }

    get hasTrend() {
        return Boolean(this.t && this.t.periods.length >= 2);
    }

    get labels() {
        return this.t ? this.t.periods.map((p) => this.periodLabel(p)) : [];
    }

    get r01Spark() {
        return this.t ? sparkPoints(this.t.active.slice(-12)) : "";
    }

    get retentionChart() {
        const vals = this.t.growth.map((g) => g.retention);
        const present = vals.filter((v) => v !== null);
        const low = present.length ? Math.max(0, Math.floor((Math.min(...present) - 2) / 5) * 5) : 80;
        return { labels: this.labels, h: 150, yMin: low, yMax: 100, yFmt: (v) => v.toFixed(0) + "%",
                 tipFmt: (v) => v.toFixed(1) + "%",
                 series: [{ name: `${this.state.grain === "week" ? "Weekly" : "Monthly"} retention`, values: vals, color: "--gh-green" }],
                 onClick: (i) => this.growth(this.t.growth[i].end, "retained", "Retained riders") };
    }

    get growthChart() {
        const g = this.t.growth;
        return { labels: this.labels, h: 170, series: [
            { name: "First-time riders", values: g.map((r) => r.first_time), color: "--s-zembo" },
            { name: "Returning riders", values: g.map((r) => r.returning), color: "--s-niu" },
            { name: "Exits", values: g.map((r) => r.exits), color: "--s-4" },
        ], onClick: (i, j) => {
            const part = ["first_time", "returning", "exits"][j ?? 0];
            return this.growth(g[i].end, part, { first_time: "First-time riders", returning: "Returning riders", exits: "Exits" }[part]);
        } };
    }

    get growthRows() {
        return this.t.growth.slice(-6).reverse();
    }

    get demoChart() {
        const keys = ["m_u", "f_u", "m_o", "f_o"];
        const limit = this.ok("core") ? this.d.core.youth.limit : 35;
        return {
            labels: this.labels, h: 200,
            cats: [
                { name: `Men <${limit}`, color: "--s-zembo" }, { name: `Women <${limit}`, color: "--s-iqube" },
                { name: `Men ${limit}+`, color: "--s-niu" }, { name: `Women ${limit}+`, color: "--s-4" },
            ],
            data: this.t.demo.map((d) => keys.map((k) => d[k] || 0)),
            onClick: (i) => this.growth(this.t.growth[i].end, "closing", "Active riders"),
        };
    }

    get unassignedChart() {
        return { labels: this.labels, h: 190, stacked: true, series: [
            { name: "New (never contracted)", values: this.t.unassigned.map((u) => u.new || 0), color: "--s-zembo" },
            { name: "Re-financing", values: this.t.unassigned.map((u) => u.refinancing || 0), color: "--s-niu" },
        ], onClick: (i) => this.drill("kpi_snapshots", { metric_codes: ["R06"], period_type: this.state.grain,
                                                         period_end: this.t.periods[i], label: "Unassigned e-bodas" }) };
    }

    licenceCount(key) {
        return this.d.safety.licences.counts[key];
    }

    growth(end, part, label, since) {
        return this.drill("growth", { grain: this.state.grain, period_end: end, part, label, since: since || false,
                                      product_group_id: this.state.productGroupId || false });
    }

    retention(grain, since, end, label) {
        return this.drill("growth", { grain, period_end: end, part: "retained", since, label,
                                      product_group_id: this.state.productGroupId || false });
    }

    openRider(riderId) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "rider", res_id: riderId, views: [[false, "form"]] });
    }
}

registry.category("actions").add("gh_dashboards.riders", RidersDashboard);
