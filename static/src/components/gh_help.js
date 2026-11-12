/** @odoo-module **/

/**
 * Hover explainers for the Green Hub dashboards.
 *
 * The text lives on the server (models/gh_guide.py) and is shared with the
 * Guide page. A card is matched to its entry by, in order: its data-gh-help
 * attribute, the KPI code chip it already carries (<span class="kc">), or,
 * for a filter, its label. No per-card wiring is needed in the templates.
 */

let guidePromise = null;

/** One fetch per browser session; a failed fetch is retried on the next call. */
export function loadGuide(orm) {
    if (!guidePromise) {
        guidePromise = orm.call("gh.kpi.service", "get_guide", []).catch((err) => {
            guidePromise = null;
            throw err;
        });
    }
    return guidePromise;
}

/** "R10–R12" -> [R10, R11, R12]; "R07 · R09" -> [R07, R09]; "P22" -> [P22]. */
export function expandCodes(text) {
    const out = [];
    for (const part of (text || "").split(/[·,]/)) {
        const range = part.trim().match(/^([A-Z])(\d+)\s*[–-]\s*\1?(\d+)$/);
        if (range) {
            const width = range[2].length;
            for (let n = Number(range[2]); n <= Number(range[3]); n++) {
                out.push(range[1] + String(n).padStart(width, "0"));
            }
        } else if (part.trim()) {
            out.push(part.trim());
        }
    }
    return out;
}

const HOSTS = ".gh-tile, .gh-ptitle, .gh-h3, .gh-pcap, .gh-mhead, .gh-hr, .gh-f, .gh-checks > button";
const SHOW_DELAY = 350;

export class GhHelp {
    /**
     * @param {Object} byKey  guide entries indexed by key
     * @param {Function} extraKeys  (element) => keys for elements the generic rules can't name (the hero figure)
     */
    constructor(byKey, extraKeys) {
        this.byKey = byKey;
        this.extraKeys = extraKeys || (() => []);
        this.enabled = true;
        this.host = null;
        this.timer = null;
        this.el = document.createElement("div");
        this.el.className = "gh-help";
        this.el.setAttribute("role", "tooltip");
        document.body.appendChild(this.el);
        this.onOver = this.onOver.bind(this);
        this.hide = this.hide.bind(this);
    }

    destroy() {
        clearTimeout(this.timer);
        this.el.remove();
    }

    /** Keys for the element under the pointer, or [] when it has no explainer. */
    keysFor(host) {
        if (host.dataset.ghHelp) {
            return expandCodes(host.dataset.ghHelp);
        }
        if (host.classList.contains("gh-hr")) {
            return this.extraKeys(host);
        }
        if (host.classList.contains("gh-codes-toggle")) {
            return host.classList.contains("gh-guide-btn") || /hints/.test(host.textContent) ? [] : ["F:codes"];
        }
        if (host.parentElement?.classList.contains("gh-checks")) {
            return ["F:checks"];
        }
        if (host.classList.contains("gh-f")) {
            const label = [...host.childNodes].find((n) => n.nodeType === Node.TEXT_NODE && n.textContent.trim());
            return label ? [`F:${label.textContent.trim().toLowerCase()}`] : [];
        }
        const card = host.closest("[data-gh-help], .gh-tile, .gh-panel, .gh-mcard");
        if (!card) {
            return [];
        }
        if (card.dataset.ghHelp) {
            return expandCodes(card.dataset.ghHelp);
        }
        const chip = [...card.children].find((c) => c.classList.contains("kc"));
        return chip ? expandCodes(chip.textContent) : [];
    }

    onOver(ev) {
        if (!this.enabled || !(ev.target instanceof Element) || !ev.target.closest(".gh")) {
            return this.hide();
        }
        const host = ev.target.closest(HOSTS);
        if (host === this.host) {
            return;
        }
        const entries = host ? this.keysFor(host).map((k) => this.byKey[k]).filter(Boolean) : [];
        const sig = entries.map((e) => e.key).join("|");
        if (sig && sig === this.sig && host.closest(".gh-panel, .gh-mcard") === this.card) {
            this.host = host;  // title -> caption of the same panel: keep the explainer where it is
            return;
        }
        this.hide();
        if (!entries.length) {
            return;
        }
        this.host = host;
        this.sig = sig;
        this.card = host.closest(".gh-panel, .gh-mcard");
        this.timer = setTimeout(() => this.show(host, entries), SHOW_DELAY);
    }

    hide() {
        clearTimeout(this.timer);
        this.host = null;
        this.sig = null;
        this.card = null;
        this.el.classList.remove("on");
    }

    row(parent, label, text) {
        if (!text) {
            return;
        }
        const p = document.createElement("p");
        const b = document.createElement("b");
        b.textContent = label;
        p.append(b, document.createTextNode(` ${text}`));
        parent.appendChild(p);
    }

    show(host, entries) {
        if (!host.isConnected) {
            return this.hide();
        }
        const single = entries.length === 1;
        this.el.replaceChildren();
        for (const e of entries) {
            const block = document.createElement("div");
            block.className = "gh-help-e";
            const head = document.createElement("div");
            head.className = "gh-help-h";
            if (e.code) {
                const chip = document.createElement("span");
                chip.className = "gh-help-c";
                chip.textContent = e.code;
                head.appendChild(chip);
            }
            head.appendChild(document.createTextNode(e.title));
            block.appendChild(head);
            const what = document.createElement("p");
            what.className = "gh-help-w";
            what.textContent = e.what;
            block.appendChild(what);
            this.row(block, "How it is worked out:", e.how);
            if (single) {
                this.row(block, "Where it comes from:", e.source);
                this.row(block, "Click:", e.click);
                this.row(block, "Good to know:", e.note);
            }
            this.el.appendChild(block);
        }
        const foot = document.createElement("div");
        foot.className = "gh-help-f";
        foot.textContent = "Full definitions: Guide, in the bar above";
        this.el.appendChild(foot);

        // below the hovered element, flipped above when there is no room; always inside the window
        this.el.style.left = "0px";
        this.el.style.top = "0px";
        this.el.classList.add("on");
        const r = host.getBoundingClientRect();
        const w = this.el.offsetWidth;
        const h = this.el.offsetHeight;
        const gap = 8;
        let top = r.bottom + gap;
        if (top + h > window.innerHeight - gap) {
            top = r.top - h - gap >= gap ? r.top - h - gap : Math.max(gap, window.innerHeight - h - gap);
        }
        const left = Math.max(gap, Math.min(r.left, window.innerWidth - w - gap));
        this.el.style.left = `${left}px`;
        this.el.style.top = `${top}px`;
    }
}
