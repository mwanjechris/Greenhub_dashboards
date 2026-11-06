# Accounting alignment

Rule (Green Hub, 6 Nov 2026): the directors' dashboards must never disagree with
the finance team's reports. Odoo computes every financial figure; the dashboard
only reads it.

| Figure | Source in Odoo | Who maintains it |
|---|---|---|
| P&L lines, Revenue, Gross profit, Net profit | Odoo P&L report engine (`account_reports.profit_and_loss`, or the variant chosen in settings) | Finance (chart of accounts, account types) |
| EBITDA | Line `GH_EBITDA` of the variant "GreenHub P&L (EBITDA)" in Accounting › Reporting › Profit and Loss: Operating Income + depreciation/amortisation charged above it (line `GH_DA`, accounts picked in settings). Net Profit of the variant equals the standard P&L | Created by the settings button; finance can edit the lines in Odoo's report editor |
| Budget column, approved budget, forecast | Odoo report budgets (`account.report.budget`), the same budgets finance uses in the P&L Budget filter | Finance |
| Default losses | Posted journal items on the write-off ledger(s) picked in settings (e.g. 501002 Bad Debts Written Off) | Finance posts the write-offs |
| Lender repayments (C15/C16) | Debits on the loan liability accounts and lender interest accounts picked in settings | Finance |
| Loss / revenue % | Default losses ÷ Revenue line of Odoo's P&L | — |
| Foreign currency | Odoo exchange rates | Finance |
| Cash collections (C01–C13) | GreenHub payment logs (the app's transactions), shown side by side with Odoo customer payments for the same dates; matched via `payment.log.payment_id` | GreenHub app / finance |

Not accounting (kept in the dashboard module): arrears, PAR and risk bands
(from GreenHub instalment schedules), rider/fleet KPIs, and operational targets
(riders, fleet, collections by category, default-loss limit).

Clicking an actual opens Odoo's own audit of that report cell; clicking a
budget opens Odoo's P&L with the budget switched on. Tests in
`tests/test_accounting.py` post journal entries and report budgets and assert
the dashboard equals Odoo's report line by line.
