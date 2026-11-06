/** @odoo-module **/

import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";
import { fmtDate, fmtInt, fmtMoney, fmtPct, moneyParts, shortDate, slotColor } from "./gh_common";
import { GhChart } from "./gh_chart";

/**
 * Shared behaviour for the four dashboards. A bare root div with
 * height:100% / overflow-y:auto (never Odoo's Layout, which broke scrolling
 * on the sister Nexus module); every number comes from gh.kpi.service and
 * every figure opens its records.
 */
export class GhDashboardBase extends Component {
    static props = ["*"];
    static components = { GhChart };
    method = "";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        Object.assign(this, { fmtDate, fmtInt, fmtMoney, fmtPct, moneyParts, shortDate, slotColor });
        this.state = useState(Object.assign({
            data: null, loading: true, loadError: null, productGroupId: false, grain: "week",
            showCodes: false, showChecks: false,
        }, this.initialState()));
        onWillStart(() => this.load());
    }

    initialState() {
        return {};
    }

    params() {
        return {};
    }

    async load() {
        this.state.loading = true;
        this.state.loadError = null;
        try {
            this.state.data = await this.orm.call("gh.kpi.service", this.method, [], this.params());
        } catch (err) {
            console.error(`Green Hub dashboard ${this.method} failed`, err);
            this.state.loadError = err?.data?.message || err?.message?.data?.message || err?.message || "Unknown error";
        } finally {
            this.state.loading = false;
        }
    }

    set(key, value) {
        this.state[key] = value;
        this.load();
    }

    get d() {
        return this.state.data;
    }

    ok(key) {
        return Boolean(this.d && this.d[key] && this.d[key].ok);
    }

    panelError(key) {
        const p = this.d && this.d[key];
        return p && p.ok === false && p.error !== "live_only" ? p.error : false;
    }

    get checksFailed() {
        return (this.d?.checks || []).filter((c) => !c.ok);
    }

    check(code) {
        return (this.d?.checks || []).find((c) => c.code === code);
    }

    get readAt() {
        if (!this.d) {
            return "";
        }
        const t = new Date(`${this.d.computed_at.replace(" ", "T")}Z`);
        return t.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    }

    open(resModel, domain, name) {
        if (!domain) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window", name: name || resModel, res_model: resModel,
            views: [[false, "list"], [false, "form"]], domain, target: "current",
        });
    }

    openAction(xmlid) {
        this.action.doAction(xmlid);
    }

    periodLabel(iso) {
        if (!iso) {
            return "";
        }
        const d = new Date(`${iso}T00:00:00`);
        return this.state.grain === "month"
            ? d.toLocaleDateString("en-GB", { month: "short" })
            : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    }

    variancePill(v, budget, actual) {
        if (!v || v.favourable === null || v.favourable === undefined) {
            if (budget !== null && budget !== undefined && (actual === null || actual === undefined)) {
                return { cls: "neu", text: "no actuals" };
            }
            return { cls: "neu", text: "no plan" };
        }
        const pct = v.pct === null || v.pct === undefined ? "n/a" : `${Math.abs(v.pct).toFixed(1)}%`;
        return v.favourable ? { cls: "fav", text: `▲ Fav ${pct}` } : { cls: "unf", text: `▼ Unfav ${pct}` };
    }
}
