# Drill-through map

Rule: every figure on the four dashboards opens the records it was computed
from, so the list adds up to the number clicked. Figures taken from the general
ledger also offer the matching Odoo accounting report for the same dates
(Enterprise `account_reports`; without it the link falls back to posted journal
items).

Mechanics: `gh.kpi.service.get_drill(kind, args)` (models/gh_drill.py) rebuilds
the record set and returns a window action. Budget payloads carry ready-made
`{kind, args}` specs; the other dashboards build them in JS. Charts take an
`onClick(index, series)` in their config; the tooltip says "Click to open the
records". Dotted underline = a sub-figure with its own drill. `↗` chips = Odoo
accounting reports.

| Drill kind | Opens | Used by |
|---|---|---|
| `report` | Odoo P&L, General Ledger, Balance Sheet, Aged Receivable with the figure's dates (`ignore_session`, custom range) | Budget hero, P&L panel, financial tiles, revenue chart, outlook; Portfolio/Collections default losses |
| `journal_items` | Posted journal items on the accounts mapped to the P&L roles, grouped by account | Every P&L actual (month and period), B03–B05, B11, B10, revenue bars, EBITDA YTD, default losses (YTD, monthly bars, average) |
| `targets` | Budget / target lines summed into a plan figure (version, metric, dimension, months) | Every P&L budget, ops plans (B06–B10), C06 and category targets, outlook forecast + approved budget |
| `snapshots` | Contract snapshot rows for one period end (arrears, risk, PAR, due, collected per contract) | Arrears and average-arrears trends, risk trend (per category), default trend, recovery table, collection-rate trend |
| `kpi_snapshots` | Stored KPI values for one period | Unassigned e-bodas over time (vehicle lists are not snapshotted) |
| `growth` | Riders in opening / first-time / returning / exits / closing / retained for a period | Growth table cells and bars, retention chart and tiles, gender-age trend |
| `first_time_range` | First-time riders across the budget period | B08 |
| `receipts` | Successful inbound payment logs, filterable by category, product group, instalment-only | C01 sub-figures (late fees, deposits), C03, C07, C08 numerator, by-model collected, monthly bars, financing cash |
| `dues` | Payment schedule lines due, filterable (lease-only, active, open, paid, product group) | C02, compliance %, C08 denominator, by-model due, forecast bars |
| `month_contracts` | Contracts in a month's collection rate | C08, C09 |
| `available_vehicles` | Bikes counted as available | C09 sub-figure |
| `fleet_cell` | Vehicles in a vehicle-distribution row, column or cell | Matrix rows, totals, B09 |
| `contracts` | Live portfolio rows matching flags | B07, late-fee sub-figure on P02 |
| `financing` | Lender repayment lines (or the facilities screen when none are loaded) | C15/C16 card |

Figures that stay non-clickable on purpose: percentages that are pure ratios of
two clickable figures shown next to them (shares, Var %, performance %), and
the weekly-average retention (an average of the retention column; each point
of that chart is clickable).
