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
    if (max === min) {
        return `0,11 100,11`;  // flat series: a level line mid-height, not an underline
    }
    const span = max - min;
    return values
        .map((v, i) => {
            const x = (i / (values.length - 1)) * 100;
            const y = 20 - ((v - min) / span) * 18;
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(" ");
}

/** Compact money: 3,230,952 -> "3.23m", 61,940,000 -> "61.9m"; small values in full. */
export function fmtMoney(value) {
    if (value === null || value === undefined || value === false) {
        return "—";
    }
    const abs = Math.abs(value);
    if (abs >= 1e9) {
        return (value / 1e9).toFixed(2) + "bn";
    }
    if (abs >= 1e7) {
        return (value / 1e6).toFixed(1) + "m";
    }
    if (abs >= 1e6) {
        return (value / 1e6).toFixed(2) + "m";
    }
    return Math.round(value).toLocaleString("en-US");
}

/** {main, suffix} for big serif figures with a small unit. */
export function moneyParts(value) {
    const s = fmtMoney(value);
    const m = s.match(/^(-?[\d.,]+)(m|bn)?$/);
    return m ? { main: m[1], suffix: m[2] || "" } : { main: s, suffix: "" };
}

export function shortDate(isoDate) {
    if (!isoDate) {
        return "";
    }
    const d = new Date(`${isoDate}T00:00:00`);
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export const RISK_COLORS = {
    ahead: "--r-ahead", ontrack: "--r-ontrack", norisk: "--r-norisk", low: "--r-low",
    atrisk: "--r-atrisk", high: "--r-high", critical: "--r-critical", default: "--r-default",
};
export const RISK_INK = { norisk: "#16242B", low: "#16242B", atrisk: "#16242B" };
export const PAR_COLORS = { par0: "--r-ahead", par7: "--r-norisk", par14: "--r-atrisk", par21: "--r-high", par28: "--r-default" };
export const SLOT_CSS = { zembo: "--s-zembo", iqube: "--s-iqube", niu: "--s-niu", s4: "--s-4" };
