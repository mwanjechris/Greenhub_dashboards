/** @odoo-module **/

import { registry } from "@web/core/registry";
import { GhDashboardBase } from "../components/gh_base";

/** Collections & Payments (spec 5.3, mockup tab 3). Cash received, not revenue. */
export class CollectionsDashboard extends GhDashboardBase {
    static template = "greenhub_dashboards.CollectionsDashboard";
    method = "get_collections_dashboard";

    initialState() {
        return { period: "this_month", dateFrom: false, dateTo: false, currency: "company" };
    }

    params() {
        return { period: this.state.period, date_from: this.state.dateFrom || false, date_to: this.state.dateTo || false,
                 product_group_id: this.state.productGroupId || false, grain: this.state.grain, currency: this.state.currency };
    }

    onDate(key, ev) {
        this.state[key] = ev.target.value || false;
        if (this.state.dateFrom && this.state.dateTo) {
            this.load();
        }
    }

    get c() {
        return this.d.core;
    }

    get heroParts() {
        return this.moneyParts(this.c.total);
    }

    get periodTitle() {
        const p = this.c.period;
        const from = new Date(`${p.from}T00:00:00`);
        if (p.key === "custom") {
            return `${this.fmtDate(p.from)} – ${this.fmtDate(p.to)}`;
        }
        const month = from.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
        return p.key === "this_month" ? `${month} to date (${p.elapsed} of ${p.days} days)` : month;
    }

    get proRataPct() {
        const p = this.c.period;
        return p.days ? Math.round((100 * p.elapsed) / p.days) : 100;
    }

    achievedWidth(cat) {
        return cat.target ? Math.max(2, Math.min(100, (100 * cat.actual) / cat.target)) : 0;
    }

    get rateChart() {
        const t = this.d.rate_trend;
        return { labels: t.periods.map((p) => this.periodLabel(p)), h: 190, refLine: 100,
                 yFmt: (v) => v.toFixed(0) + "%", tipFmt: (v) => v.toFixed(1) + "%",
                 series: [{ name: "Active contracts", values: t.active, color: "--s-zembo" },
                          { name: "Entire fleet", values: t.fleet, color: "--s-niu" }],
                 onClick: (i) => this.drill("snapshots", { period_type: this.state.grain, period_end: t.periods[i], is_active: true,
                                                           label: "Due and collected per contract" }) };
    }

    get dueChart() {
        const rows = this.d.monthly.rows;
        return { labels: rows.map((r) => r.month), h: 190, yFmt: (v) => this.fmtMoney(v), tipFmt: (v) => this.fmtInt(v),
                 targets: rows.map((r) => r.due), targetStyle: { name: "Due" },
                 topLabels: rows.map((r) => (r.pct !== null ? r.pct.toFixed(0) + "%" : "")),
                 series: [{ name: "Collected", values: rows.map((r) => r.collected), color: "--gh-slate" }],
                 onClick: (i) => this.drill("receipts", { date_from: rows[i].from, date_to: rows[i].to, instalment_only: true,
                                                          product_group_id: this.state.productGroupId || false,
                                                          label: `Instalment receipts · ${rows[i].month}` }) };
    }

    get forecastChart() {
        const w = this.d.forecast.weeks;
        return { labels: w.map((r) => r.week), h: 190, yFmt: (v) => this.fmtMoney(v), tipFmt: (v) => this.fmtInt(v),
                 series: [{ name: "Contractual", values: w.map((r) => r.contractual), color: "--s-zembo" },
                          { name: "Risk-adjusted", values: w.map((r) => r.risk_adjusted), color: "--s-niu" }],
                 onClick: (i) => this.drill("dues", { date_from: w[i].from, date_to: w[i].to, active_only: true, open_only: true,
                                                      product_group_id: this.state.productGroupId || false,
                                                      label: `Instalments due · week of ${w[i].week}` }) };
    }

    receipts(categories, label) {
        const p = this.c.period;
        return this.drill("receipts", { date_from: p.from, date_to: p.to, categories,
                                        product_group_id: this.state.productGroupId || false, label });
    }

    targets(dimKey, label) {
        const p = this.c.period;
        const monthEnd = new Date(`${p.from}T00:00:00`);
        monthEnd.setMonth(monthEnd.getMonth() + 1, 0);
        const to = p.key === "custom" ? p.to : `${monthEnd.getFullYear()}-${String(monthEnd.getMonth() + 1).padStart(2, "0")}-${String(monthEnd.getDate()).padStart(2, "0")}`;
        return this.drill("targets", { metrics: ["C05"], date_from: p.from, date_to: to, label,
                                       ...(dimKey ? { dim_keys: [dimKey] } : { dim_prefix: "category:" }) });
    }

    modelReceipts(groupId, label) {
        const m = this.d.by_model;
        return this.drill("receipts", { date_from: m.from, date_to: m.to, instalment_only: true,
                                        ...(groupId === null ? {} : { group_id: groupId }), label: `Instalment receipts · ${label}` });
    }

    modelDues(groupId, label) {
        const m = this.d.by_model;
        return this.drill("dues", { date_from: m.from, date_to: m.to, ...(groupId === null ? {} : { group_id: groupId }),
                                    label: `Due · ${label}` });
    }

    lossItems(dateFrom, dateTo, label) {
        return this.drill("journal_items", { roles: ["default_loss"], date_from: dateFrom, date_to: dateTo, label });
    }

    goPortfolio() {
        this.action.doAction("greenhub_dashboards.action_gh_portfolio_dashboard");
    }
}

registry.category("actions").add("gh_dashboards.collections", CollectionsDashboard);
