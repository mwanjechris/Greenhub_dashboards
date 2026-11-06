/** @odoo-module **/

import { registry } from "@web/core/registry";
import { GhDashboardBase } from "../components/gh_base";
import { PAR_COLORS, RISK_COLORS, RISK_INK } from "../components/gh_common";

/** Portfolio Health & Credit Risk (spec 5.2, mockup tab 2). */
export class PortfolioDashboard extends GhDashboardBase {
    static template = "greenhub_dashboards.PortfolioDashboard";
    method = "get_portfolio_dashboard";

    initialState() {
        return { asOf: false, year: false, range: "26w" };
    }

    params() {
        return { product_group_id: this.state.productGroupId || false, grain: this.state.grain,
                 as_of: this.state.asOf || false, year: this.state.year || false, range_key: this.state.range };
    }

    onAsOf(ev) {
        this.set("asOf", ev.target.value || false);
    }

    riskColor(key) {
        return `var(${RISK_COLORS[key]})`;
    }

    parColor(key) {
        return `var(${PAR_COLORS[key]})`;
    }

    get riskBar() {
        return { cats: this.d.core.risk.map((r) => ({ name: r.label, value: r.count, color: RISK_COLORS[r.key], def: r.rule, ink: RISK_INK[r.key] })) };
    }

    get parBar() {
        return { cats: this.d.core.par.map((r) => ({ name: r.label, value: r.count, color: PAR_COLORS[r.key], def: r.rule,
                                                     ink: ["par7", "par14"].includes(r.key) ? "#16242B" : undefined })) };
    }

    get tr() {
        return this.ok("trends") ? this.d.trends : null;
    }

    get hasTrend() {
        return Boolean(this.tr && this.tr.periods.length >= 2);
    }

    get labels() {
        return this.tr.periods.map((p) => this.periodLabel(p));
    }

    get arrearsChart() {
        return { labels: this.labels, h: 180, yFmt: (v) => this.fmtMoney(v), tipFmt: (v) => this.fmtInt(v),
                 series: [{ name: "Total arrears", values: this.tr.arrears, color: "--gh-red" }] };
    }

    get avgArrearsChart() {
        return { labels: this.labels, h: 180, yFmt: (v) => (v / 1000).toFixed(0) + "k", tipFmt: (v) => this.fmtInt(v),
                 series: [{ name: "Avg arrears / contract", values: this.tr.avg_arrears, color: "--gh-slate" }] };
    }

    get riskTrend() {
        const keys = Object.keys(RISK_COLORS);
        return { labels: this.labels, h: 210,
                 cats: this.d.core.risk.map((r) => ({ name: r.label, color: RISK_COLORS[r.key] })),
                 data: this.tr.risk.map((row) => keys.map((k) => row[k] || 0)) };
    }

    get lossChart() {
        const m = this.d.defaults.monthly;
        return { labels: m.map((r) => r.month), h: 200, yFmt: (v) => this.fmtMoney(v), tipFmt: (v) => this.fmtInt(v),
                 topLabels: m.map((r) => (r.loss_pct !== null ? r.loss_pct.toFixed(1) + "%" : "")),
                 series: [{ name: "Default loss", values: m.map((r) => r.loss || 0), color: "--gh-red" }] };
    }

    get defaultTrend() {
        const rows = this.d.default_trend.rows;
        return { labels: rows.map((r) => this.shortDate(r.end)), h: 180, yFmt: (v) => v.toFixed(0), tipFmt: (v) => v,
                 series: [{ name: "New defaults", values: rows.map((r) => r.new), color: "--gh-red" },
                          { name: "Outstanding at period end", values: rows.map((r) => r.outstanding), color: "--gh-slate", dash: true }] };
    }

    get heroParts() {
        return this.moneyParts(this.d.core.total_arrears.value);
    }
}

registry.category("actions").add("gh_dashboards.portfolio", PortfolioDashboard);
