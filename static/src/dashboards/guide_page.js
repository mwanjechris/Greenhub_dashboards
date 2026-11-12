/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";
import { loadGuide } from "../components/gh_help";

/**
 * Guide: the documentation of the four dashboards. Same entries as the hover
 * explainers (gh.kpi.service.get_guide), so the two can never disagree.
 * Bare root div with its own scroll, like the dashboards.
 */
export class GhGuide extends Component {
    static template = "greenhub_dashboards.Guide";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.root = useRef("root");
        this.state = useState({ guide: null, error: null, q: "", hit: false });
        onWillStart(async () => {
            try {
                this.state.guide = await loadGuide(this.orm);
            } catch (err) {
                console.error("Green Hub guide failed", err);
                this.state.error = err?.data?.message || err?.message || "Unknown error";
            }
        });
        onMounted(() => {
            const params = this.props.action?.params || {};
            if (params.key) {
                this.state.hit = params.key;
                this.jump(`k-${params.key}`);
            } else if (params.dashboard) {
                this.jump(`d-${params.dashboard}`);
            }
        });
    }

    get g() {
        return this.state.guide;
    }

    get words() {
        return this.state.q.toLowerCase().split(/\s+/).filter(Boolean);
    }

    matches(...texts) {
        const hay = texts.filter(Boolean).join(" ").toLowerCase();
        return this.words.every((w) => hay.includes(w));
    }

    entriesOf(dashKey) {
        return this.g.entries.filter((e) => e.dash === dashKey &&
            this.matches(e.code, e.title, e.what, e.how, e.source, e.click, e.note));
    }

    get dashboards() {
        return this.g.dashboards.map((d) => Object.assign({}, d, { entries: this.entriesOf(d.key) }))
            .filter((d) => d.entries.length);
    }

    get sections() {
        return this.g.sections.map((s) => Object.assign({}, s, { items: s.items.filter((i) => this.matches(i.h, i.p)) }))
            .filter((s) => s.items.length);
    }

    get terms() {
        return this.g.terms.filter((t) => this.matches(t.term, t.meaning));
    }

    get nothing() {
        return !this.dashboards.length && !this.sections.length && !this.terms.length;
    }

    /** Sections that come before the KPI reference, and those after it. */
    sectionsIn(keys) {
        return this.sections.filter((s) => keys.includes(s.key));
    }

    jump(id) {
        const el = this.root.el?.querySelector(`#gg-${CSS.escape(id)}`);
        if (el) {
            el.scrollIntoView({ block: "start" });
        }
    }

    onSearch(ev) {
        this.state.q = ev.target.value;
        this.state.hit = false;
    }

    openDashboard(xmlid) {
        this.action.doAction(xmlid);
    }
}

registry.category("actions").add("gh_dashboards.guide", GhGuide);
