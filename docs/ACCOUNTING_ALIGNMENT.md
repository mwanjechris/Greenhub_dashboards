# Accounting alignment

Rule (Green Hub, 6 Nov 2026): the directors' dashboards must never disagree with
the finance team's reports. Odoo computes every financial figure; the dashboard
only reads it.

| Figure | Source in Odoo | Who maintains it |
|---|---|---|
| P&L lines, Revenue, Gross profit, Net profit | Odoo P&L report engine (`account_reports.profit_and_loss`, or the variant chosen in settings) | Finance (chart of accounts, account types) |
| EBITDA | Line `GH_EBITDA` of the variant "GreenHub P&L (EBITDA)" in Accounting › Reporting › Profit and Loss: Operating Income + depreciation/amortisation charged above it (line `GH_DA`, accounts picked in settings). Net Profit of the variant equals the standard P&L | Created by the settings button; finance can edit the lines in Odoo's report editor |
| Budget column, approved budget, forecast | Odoo report budgets (`account.report.budget`), the same budgets finance uses in the P&L Budget filter | Finance |
| Analytic budgets panel | Odoo Budgets app (`budget.analytic` / `budget.line`): planned, theoretical, achieved, % as Odoo computes them | Finance |
| Default losses | Posted journal items on the write-off ledger(s) picked in settings (live: 601058 Lease Default, used by the WROFF journal) | Finance posts the write-offs |
| Lender repayments (C15/C16) | Debits on the loan liability accounts and lender interest accounts picked in settings | Finance |
| Loss / revenue % | Default losses ÷ Revenue line of Odoo's P&L | — |
| Foreign currency | Odoo exchange rates | Finance |
| Cash collections (C01–C13) | GreenHub payment logs (the app's transactions), shown side by side with Odoo customer payments for the same dates; matched on `payment_reference` (or `payment.log.payment_id` when filled) | GreenHub app / finance |

Not accounting (kept in the dashboard module): arrears, PAR and risk bands
(from GreenHub instalment schedules), rider/fleet KPIs, and operational targets
(riders, fleet, collections by category, default-loss limit).

Clicking an actual opens Odoo's own audit of that report cell; clicking a
budget opens Odoo's P&L with the budget switched on. Tests in
`tests/test_accounting.py` post journal entries and report budgets and assert
the dashboard equals Odoo's report line by line.

## The "GreenHub P&L (EBITDA)" variant

Created automatically:
* on **installation** of `greenhub_dashboards` (`post_init_hook` in `__init__.py`), for every company;
* on **upgrade** from 19.0.1.0.x (`migrations/19.0.1.1.0/post-migrate.py`);
* or by the button in Dashboard settings ("Create / refresh the GreenHub P&L (EBITDA) variant").

It is a copy of Odoo's standard Profit and Loss, registered as a variant (`root_report_id` = P&L) and
identified by the xmlid `greenhub_dashboards.gh_pl_ebitda_variant`, so finance can rename it and an
upgrade will not create a second one. Find it in Accounting › Reporting › Profit and Loss › variant
selector.

| Code | Line | Formula (Odoo report engine) |
|---|---|---|
| GH_REV | Revenue | income accounts, −sum |
| GH_COS | Less Costs of Revenue | expense_direct_cost, sum |
| GH_GRP | Gross Profit | GH_REV − GH_COS |
| GH_EXP | Less Operating Expenses | expense, sum |
| GH_INC | Operating Income (or Loss) | GH_REV − GH_COS − GH_EXP |
| GH_DA | Plus depreciation & amortisation above Operating Income | accounts in settings › "Depreciation / amortisation above Operating Income", sum |
| GH_EBITDA | EBITDA | GH_INC + GH_DA |
| GH_OIN | Plus Other Income | income_other, −sum |
| GH_OEXP | Less Other Expenses | expense_depreciation + expense_other, sum |
| GH_NEP | Net Profit | identical to the standard P&L |
| GH_ALLOC / GH_NEPAL | Allocations / Net Profit after allocations | as standard |

Why only part of depreciation is added back: Odoo already puts "Depreciation" type accounts (5020xx on
live) below Operating Income. Depreciation booked in cost of revenue or operating expenses (live:
501024–501027 EV fleet, batteries, cabinets, chargers) is inside Operating Income and is added back. The
install suggests these by account name ("depreciat", "amorti"); finance confirms them in settings, and
the GH_DA formula follows the setting. The variant's Net Profit always equals Odoo's standard P&L.

Because the variant belongs to the module through its xmlid, uninstalling the module is expected to remove it (not tested).
