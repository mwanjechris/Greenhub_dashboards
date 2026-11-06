/** @odoo-module **/

import { Component, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";

/**
 * Charts ported 1:1 from the approved mockup's SVG helpers (no Chart.js, no CDN):
 * 2px lines, rounded bar ends at the data end only, 2px gaps between stacked
 * segments, recessive grid, one y-axis, a hover tooltip on every bar and point.
 *
 * props.kind: "bar" | "line" | "stack100" | "stackCols100"
 * props.config: the same option objects the mockup used (labels, series, ...), plus an
 *   optional onClick(index, seriesIndex) that opens the records behind a bar / point.
 */
const NS = "http://www.w3.org/2000/svg";
const fmt = (n) => Math.round(n).toLocaleString("en-US");
const pct = (a, b) => (b ? (100 * a) / b : 0).toFixed(1) + "%";

function el(tag, attrs = {}, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) {
        e.setAttribute(k, attrs[k]);
    }
    if (parent) {
        parent.appendChild(e);
    }
    return e;
}

let tip = null;
function tipEl() {
    if (!tip) {
        tip = document.createElement("div");
        tip.className = "gh-tip";
        document.body.appendChild(tip);
    }
    return tip;
}
function moveTip(ev) {
    const t = tipEl();
    t.style.left = Math.min(ev.clientX + 14, window.innerWidth - 290) + "px";
    t.style.top = ev.clientY + 14 + "px";
}
function showTip(html, ev) {
    const t = tipEl();
    t.innerHTML = html;
    t.style.opacity = 1;
    moveTip(ev);
}
function hideTip() {
    if (tip) {
        tip.style.opacity = 0;
    }
}
function bindTip(node, html) {
    node.addEventListener("mouseenter", (e) => showTip(typeof html === "function" ? html() : html, e));
    node.addEventListener("mousemove", moveTip);
    node.addEventListener("mouseleave", hideTip);
}
function svgPoint(svg, ev) {
    const pt = svg.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
}
const HINT = `<div class="row" style="opacity:.7"><span class="k">Click to open the records</span></div>`;
function bindClick(node, onClick, fn) {
    if (!onClick) {
        return;
    }
    node.style.cursor = "pointer";
    node.addEventListener("click", (ev) => {
        hideTip();
        fn(ev);
    });
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const row = (c, k, v) =>
    `<div class="row"><span class="k">${c ? `<i style="background:${c}"></i>` : ""}${esc(k)}</span><b>${esc(v)}</b></div>`;

function niceMax(v) {
    if (!v || v <= 0) {
        return 1;
    }
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    const m = v / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
}

function frame(host, h, yMax, yFmt, labels, opt = {}) {
    const yMin = opt.yMin || 0;
    const W = host.clientWidth || 600, H = h, L = opt.left ?? 44, R = 8, T = 10, B = 22;
    const svg = el("svg", { class: "ch", viewBox: `0 0 ${W} ${H}`, height: H }, host);
    const pw = W - L - R, ph = H - T - B;
    const span = yMax - yMin || 1;
    const p10 = Math.pow(10, Math.floor(Math.log10(span)));
    const lead = +(span / p10).toFixed(2);
    const ticks = opt.ticks || ({ 1: 5, 2: 4, 2.5: 5, 5: 5, 10: 5 }[lead] || 4);
    for (let i = 0; i <= ticks; i++) {
        const v = yMin + (span * i) / ticks, y = T + ph - (ph * i) / ticks;
        el("line", { class: i ? "grid" : "base", x1: L, x2: W - R, y1: y, y2: y }, svg);
        const t = el("text", { x: L - 6, y: y + 3, "text-anchor": "end" }, svg);
        t.textContent = yFmt(v);
    }
    const step = pw / Math.max(labels.length, 1), every = Math.ceil(labels.length / (W < 500 ? 6 : 12));
    labels.forEach((lb, i) => {
        if (i % every) {
            return;
        }
        const t = el("text", { x: L + step * i + step / 2, y: H - 6, "text-anchor": "middle" }, svg);
        t.textContent = lb;
    });
    return { svg, W, H, L, R, T, B, pw, ph, step, y: (v) => T + ph - ph * ((v - yMin) / span) };
}

function roundTopRect(svg, x, y, w, h, r, fill) {
    r = Math.min(r, w / 2, h);
    const d = `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
    return el("path", { d, fill }, svg);
}

function barChart(host, css, { labels, series, h = 200, yFmt = fmt, tipFmt = fmt, targets, targetStyle, topLabels, stacked = false, onClick }) {
    const totals = labels.map((_, i) =>
        stacked
            ? series.reduce((s, se) => s + Math.max(0, se.values[i] || 0), 0)
            : Math.max(...series.map((se) => se.values[i] || 0), targets ? targets[i] || 0 : 0)
    );
    const yMax = niceMax(Math.max(...totals, 0) * 1.08);
    const f = frame(host, h, yMax, yFmt, labels);
    const n = stacked ? 1 : series.length, gw = f.step * 0.64, bw = Math.max(3, (gw - (n - 1) * 2) / n);
    labels.forEach((lb, i) => {
        const x0 = f.L + f.step * i + (f.step - gw) / 2;
        let acc = 0;
        series.forEach((se, j) => {
            const v = se.values[i];
            if (!v) {
                return;
            }
            if (stacked) {
                const y1 = f.y(acc + v), y0 = f.y(acc);
                const isTop = j === series.length - 1 || !series.slice(j + 1).some((s) => s.values[i]);
                const hgt = Math.max(1, y0 - y1 - (acc ? 2 : 0));
                isTop ? roundTopRect(f.svg, x0, y1, gw, hgt, 4, se.color) : el("rect", { x: x0, y: y1, width: gw, height: hgt, fill: se.color }, f.svg);
                acc += v;
            } else {
                const x = x0 + j * (bw + 2), y = f.y(v);
                roundTopRect(f.svg, x, y, bw, f.T + f.ph - y, 4, se.color);
            }
        });
        if (targets && targets[i] !== null && targets[i] !== undefined) {
            const ty = f.y(targets[i]);
            el("line", { x1: x0 - 3, x2: x0 + gw + 3, y1: ty, y2: ty, stroke: targetStyle?.color || css("--gh-ink"), "stroke-width": 2,
                "stroke-dasharray": targetStyle?.dash || "" }, f.svg);
        }
        if (topLabels && topLabels[i]) {
            const t = el("text", { x: x0 + gw / 2, y: f.y(Math.max(totals[i], targets ? targets[i] || 0 : 0)) - 5, "text-anchor": "middle", style: "fill:" + css("--gh-ink") }, f.svg);
            t.textContent = topLabels[i];
        }
        const hit = el("rect", { class: "hit", x: f.L + f.step * i, y: f.T, width: f.step, height: f.ph }, f.svg);
        bindTip(hit, () => `<b>${esc(lb)}</b>` + series.map((se) => row(se.color, se.name, tipFmt(se.values[i] || 0))).join("") +
            (targets && targets[i] !== null && targets[i] !== undefined ? row(null, targetStyle?.name || "Due / target", tipFmt(targets[i])) : "") +
            (topLabels && topLabels[i] ? row(null, "", topLabels[i]) : "") + (onClick ? HINT : ""));
        bindClick(hit, onClick, (ev) => {
            // which series was hit: stacked = by height, grouped = by bar slot
            const p = svgPoint(f.svg, ev);
            let j = null;
            if (stacked) {
                let acc = 0;
                series.forEach((se, k) => {
                    const v = Math.max(0, se.values[i] || 0);
                    if (v && j === null && p.y >= f.y(acc + v) && p.y <= f.y(acc)) {
                        j = k;
                    }
                    acc += v;
                });
            } else {
                const k = Math.floor((p.x - x0) / (bw + 2));
                j = k >= 0 && k < series.length ? k : null;
            }
            onClick(i, j);
        });
    });
}

function lineChart(host, css, { labels, series, h = 190, yFmt = fmt, tipFmt = fmt, yMax, yMin = 0, refLine, onClick }) {
    const values = series.flatMap((s) => s.values.filter((v) => v !== null && v !== undefined));
    const max = yMax ?? niceMax(Math.max(...values, refLine || 0, 0) * 1.1);
    const f = frame(host, h, max, yFmt, labels, { yMin });
    const yy = f.y;
    if (refLine !== null && refLine !== undefined) {
        el("line", { x1: f.L, x2: f.W - f.R, y1: yy(refLine), y2: yy(refLine), stroke: css("--gh-ink-soft"), "stroke-dasharray": "2 4" }, f.svg);
    }
    const xs = (i) => f.L + f.step * i + f.step / 2;
    series.forEach((se) => {
        const pts = se.values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
        if (!pts.length) {
            return;
        }
        const d = pts.map(([i, v], k) => (k ? "L" : "M") + xs(i) + "," + yy(v)).join("");
        el("path", { d, fill: "none", stroke: se.color, "stroke-width": 2, "stroke-dasharray": se.dash ? "5 4" : "", "stroke-linejoin": "round", "stroke-linecap": "round" }, f.svg);
        const [li, lv] = pts[pts.length - 1];
        el("circle", { cx: xs(li), cy: yy(lv), r: 3.5, fill: se.color, stroke: "#fff", "stroke-width": 2 }, f.svg);
    });
    const xh = el("line", { class: "xh", y1: f.T, y2: f.T + f.ph }, f.svg);
    const dots = series.map((se) => el("circle", { r: 4.5, fill: se.color, stroke: "#fff", "stroke-width": 2, opacity: 0 }, f.svg));
    labels.forEach((lb, i) => {
        const hit = el("rect", { class: "hit", x: f.L + f.step * i, y: f.T, width: f.step, height: f.ph }, f.svg);
        hit.addEventListener("mouseenter", (e) => {
            xh.setAttribute("x1", xs(i));
            xh.setAttribute("x2", xs(i));
            xh.style.opacity = 1;
            dots.forEach((d, j) => {
                const v = series[j].values[i];
                if (v === null || v === undefined) {
                    d.setAttribute("opacity", 0);
                    return;
                }
                d.setAttribute("cx", xs(i));
                d.setAttribute("cy", yy(v));
                d.setAttribute("opacity", 1);
            });
            showTip(`<b>${esc(lb)}</b>` + series.map((se) => row(se.color, se.name, se.values[i] === null || se.values[i] === undefined ? "—" : tipFmt(se.values[i]))).join("") + (onClick ? HINT : ""), e);
        });
        hit.addEventListener("mousemove", moveTip);
        hit.addEventListener("mouseleave", () => {
            xh.style.opacity = 0;
            dots.forEach((d) => d.setAttribute("opacity", 0));
            hideTip();
        });
        bindClick(hit, onClick, () => onClick(i, null));
    });
}

function stack100(host, css, { cats, h = 34, onClick }) {
    const W = host.clientWidth || 600, total = cats.reduce((s, c) => s + c.value, 0);
    const svg = el("svg", { class: "ch", viewBox: `0 0 ${W} ${h + 18}`, height: h + 18 }, host);
    const live = cats.filter((c) => c.value > 0), gaps = Math.max(live.length - 1, 0) * 2, usable = W - gaps;
    let x = 0;
    live.forEach((c, i) => {
        const w = (usable * c.value) / total;
        const r = el("rect", { x, y: 0, width: Math.max(1, w), height: h, fill: c.color, rx: i === 0 || i === live.length - 1 ? 4 : 0 }, svg);
        if (w > 34) {
            const t = el("text", { x: x + w / 2, y: h / 2 + 4, "text-anchor": "middle", style: `fill:${c.ink || "#fff"};font-weight:600` }, svg);
            t.textContent = Math.round((100 * c.value) / total) + "%";
        }
        bindTip(r, `<b>${esc(c.name)}</b>` + row(c.color, "Contracts", c.value) + row(null, "Share", pct(c.value, total)) + (c.def ? row(null, "Rule", c.def) : "") + (onClick ? HINT : ""));
        bindClick(r, onClick, () => onClick(cats.indexOf(c), null));
        x += w + 2;
    });
    [0, 25, 50, 75, 100].forEach((p) => {
        const t = el("text", { x: Math.min(W - 12, Math.max(8, (W * p) / 100)), y: h + 14, "text-anchor": "middle" }, svg);
        t.textContent = p + "%";
    });
}

function stackCols100(host, css, { labels, cats, data, h = 200, onClick }) {
    const f = frame(host, h, 100, (v) => v + "%", labels);
    const gw = f.step * 0.7;
    labels.forEach((lb, i) => {
        const tot = data[i].reduce((a, b) => a + b, 0);
        if (!tot) {
            return;
        }
        let acc = 0;
        const x = f.L + f.step * i + (f.step - gw) / 2;
        cats.forEach((c, j) => {
            const v = (100 * data[i][j]) / tot;
            if (!v) {
                return;
            }
            const y1 = f.y(acc + v), y0 = f.y(acc), hh = Math.max(0.5, y0 - y1 - (acc ? 2 : 0));
            j === cats.length - 1 ? roundTopRect(f.svg, x, y1, gw, hh, 3, c.color) : el("rect", { x, y: y1, width: gw, height: hh, fill: c.color }, f.svg);
            acc += v;
        });
        const hit = el("rect", { class: "hit", x: f.L + f.step * i, y: f.T, width: f.step, height: f.ph }, f.svg);
        bindTip(hit, () => `<b>${esc(lb)}</b>` + cats.map((c, j) => row(c.color, c.name, `${data[i][j]} · ${pct(data[i][j], tot)}`)).join("") + (onClick ? HINT : ""));
        bindClick(hit, onClick, (ev) => {
            const p = svgPoint(f.svg, ev);
            let acc = 0, hitJ = null;
            cats.forEach((c, j) => {
                const v = (100 * data[i][j]) / tot;
                if (v && hitJ === null && p.y >= f.y(acc + v) && p.y <= f.y(acc)) {
                    hitJ = j;
                }
                acc += v;
            });
            onClick(i, hitJ);
        });
    });
}

const KINDS = { bar: barChart, line: lineChart, stack100, stackCols100 };

export class GhChart extends Component {
    static template = "greenhub_dashboards.GhChart";
    static props = { kind: String, config: Object };

    setup() {
        this.root = useRef("root");
        this.onResize = () => this.draw();
        onMounted(() => {
            this.draw();
            window.addEventListener("resize", this.onResize);
        });
        onPatched(() => this.draw());
        onWillUnmount(() => {
            window.removeEventListener("resize", this.onResize);
            hideTip();
        });
    }

    draw() {
        const host = this.root.el;
        if (!host) {
            return;
        }
        host.innerHTML = "";
        const style = getComputedStyle(host);
        const css = (v) => style.getPropertyValue(v).trim();
        const config = { ...this.props.config };
        for (const se of config.series || []) {
            if (se.color && se.color.startsWith("--")) {
                se.color = css(se.color);
            }
        }
        for (const c of config.cats || []) {
            if (c.color && c.color.startsWith("--")) {
                c.color = css(c.color);
            }
        }
        KINDS[this.props.kind](host, css, config);
    }
}
