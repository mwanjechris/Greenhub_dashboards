/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";
import { fmtDate, fmtInt, fmtPct, slotColor, sparkPoints } from "../components/gh_common";

/**
 * Riders & Customers (spec section 5.1, mockup tab 1).
 *
 * A bare root div with height:100% / overflow-y:auto, not Odoo's Layout:
 * nesting a scroll region inside Layout's .o_content broke scrolling on
 * the sister Nexus module. All numbers come from gh.kpi.service; this
 * component only renders them and opens the records behind each one.
 */
export class RidersDashboard extends Component {
    static template = "greenhub_dashboards.RidersDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.fmtInt = fmtInt;
        this.fmtPct = fmtPct;
        this.fmtDate = fmtDate;
        this.slotColor = slotColor;
        this.state = useState({
            data: null,
            loading: true,
            loadError: null,
            productGroupId: false,
            grain: "week",
            showCodes: false,
            showChecks: false,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.loadError = null;
        try {
            this.state.data = await this.orm.call("gh.kpi.service", "get_riders_dashboard", [], {
                product_group_id: this.state.productGroupId || false,
                grain: this.state.grain,
            });
        } catch (err) {
            console.error("Green Hub Riders dashboard failed to load", err);
            this.state.loadError =
                err?.data?.message || err?.message?.data?.message || err?.message || "Unknown error";
        } finally {
            this.state.loading = false;
        }
    }

    setProduct(groupId) {
        this.state.productGroupId = groupId;
        this.load();
    }

    setGrain(grain) {
        this.state.grain = grain;
        this.load();
    }

    get d() {
        return this.state.data;
    }

    ok(key) {
        return Boolean(this.d && this.d[key] && this.d[key].ok);
    }

    get checksFailed() {
        return (this.d?.checks || []).filter((c) => !c.ok);
    }

    get readAt() {
        if (!this.d) {
            return "";
        }
        const t = new Date(`${this.d.computed_at.replace(" ", "T")}Z`);
        return t.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    }

    get r01Spark() {
        const h = this.ok("history") ? this.d.history : null;
        if (!h) {
            return "";
        }
        const s = h.series["R01|"] || {};
        return sparkPoints(h.periods.map((p) => s[p]).filter((v) => v !== undefined));
    }

    get hasHistory() {
        return this.ok("history") && this.d.history.periods.length >= 2;
    }

    licenceCount(key) {
        return this.d.safety.licences.counts[key];
    }

    open(resModel, domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name || resModel,
            res_model: resModel,
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: domain || [],
            target: "current",
        });
    }

    openRider(riderId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "rider",
            res_id: riderId,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("gh_dashboards.riders", RidersDashboard);
