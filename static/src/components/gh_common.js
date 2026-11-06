/** @odoo-module **/

/** Shared formatting helpers for the Green Hub dashboards. */

export const SLOT_VAR = {
    zembo: "var(--s-zembo)",
    iqube: "var(--s-iqube)",
    niu: "var(--s-niu)",
    s4: "var(--s-4)",
};

export function slotColor(slot) {
    return SLOT_VAR[slot] || "var(--gh-ink-soft)";
}

export function fmtInt(value) {
    if (value === null || value === undefined || value === false) {
        return "—";
    }
    return Math.round(value).toLocaleString("en-US");
}

/** Percentage to 1 dp, or an em dash when the denominator was zero. */
export function fmtPct(value) {
    if (value === null || value === undefined || value === false) {
        return "—";
    }
    return `${value.toFixed(1)}%`;
}

export function fmtDate(isoDate) {
    if (!isoDate) {
        return "—";
    }
    const d = new Date(`${isoDate}T00:00:00`);
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

/** SVG polyline points for a sparkline, scaled to a 100 x 22 viewBox. */
export function sparkPoints(values) {
    if (!values || values.length < 2) {
        return "";
    }
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    return values
        .map((v, i) => {
            const x = (i / (values.length - 1)) * 100;
            const y = 20 - ((v - min) / span) * 18;
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(" ");
}
