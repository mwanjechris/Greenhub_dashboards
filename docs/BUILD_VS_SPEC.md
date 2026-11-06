# Green Hub Dashboards: build vs mockup and build spec

Compared on 6 Nov 2026 against `GREENHUB_DASHBOARDS_REBUILD.md` (the brief), *Odoo Dashboard
Specifications 2.0* and `greenhub_dashboard_mockups.html`. Verified on a local Odoo 19 database holding
a pseudonymised ~50-contract sample of the live data plus a stratified sample of the live 2026
accounting (4,693 real posted entries, 420 real customer payments, live + simulated budgets; see §5).
All integrations, crons and mail servers are neutralised.

Last updated 6 Nov 2026 (night): drill-through on every figure; all financial figures read from Odoo
accounting (P&L report engine, report budgets, analytic budgets, posted journal items); P&L variant
with EBITDA created on install. 37 automated tests pass; every figure was clicked through in Chrome.

Status key: **Done** = built and tested · **Partial** = built with a stated gap · **Not built**.

## 1. Against the mockup

| Tab | Layout & copy | Differences |
|---|---|---|
| Riders & Customers | Same header, filter bar, scorecard clusters, tables, charts and order | As-of is a list of snapshot week ends, not a free date picker. X-axis shows dates, not week numbers. |
| Portfolio & Credit Risk | Same, incl. 100% stacked risk/PAR bars, shared default block, recovery table, three trend charts | Risk rule text is generated from settings, so wording differs slightly. |
| Collections & Payments | Same, incl. category-vs-target table, lender-repayment card (from the GL), GreenHub logs vs Odoo payments side by side, forecast, compact default strip | Currency toggle shows only when a lender currency is set. |
| Budget & Performance | Same, incl. P&L table, outlook card, ops KPIs, budgets table with Import, plus an Odoo analytic-budgets panel | P&L lines are Odoo's own (labels "Less Costs of Revenue" etc. as in Accounting › Reporting), not the mockup's custom lines. The selector picks an Odoo report budget; a second selector picks the operational target version. |

Design rules kept: closed `gh-` palette copied from Nexus, IBM Plex bundled locally (no `@import`, no CDN),
Georgia for figures, all styles scoped under `.gh`, colour follows the entity, risk ramp order fixed,
one y-axis per chart, 2px lines, rounded bar ends at the data end, 2px stack gaps, tooltips on every
bar/point, dotted 100% reference and no cap on collection rates, icon + label on every status,
hatched "Awaiting …" empty states, per-panel error boxes, tiles stack below 1200px.
Charts are the mockup's SVG helpers ported into an OWL component (allowed by brief 3A).

## 2. Against the build spec

### Ground rules (brief 0)
| Rule | Status |
|---|---|
| Verify against Odoo 19 source | Done (APIs checked in source; see greenhub `UPGRADE_NOTES.md`) |
| All KPI maths on the server | Done |
| One definition per KPI | Done (`gh.history.service` holds contract-level rules used live and historically) |
| No string matching for business logic | Done. Products, models, vehicle categories, payment categories, exit types and accounts come from configuration records. Two one-off *setup helpers* propose tag and exit-type rules from names; a Manager reviews them. The payment memo prefix is a configured rule (the brief prescribes it as fallback). |
| Every number drills down | Done (7 Nov round): every tile, sub-figure, table cell, total, chart bar/point and hero figure opens the records it was computed from; ledger figures also link the Odoo P&L / General Ledger / Balance Sheet for the same dates. See DRILL_THROUGH.md |
| Read-only on business data | Done. No greenhub records are written. The only accounting write is the P&L *report variant* (report configuration, created on install, see ACCOUNTING_ALIGNMENT.md). |
| Financial figures never computed by the dashboard | Done (6 Nov): P&L from Odoo's report engine, budgets from Odoo report budgets and analytic budgets, losses / repayments from posted journal items; tests assert equality with Odoo line by line |
| Unit tests + reconciliation tests | Done: 33 server tests + 4 headless-browser tests, all passing; fresh install on an empty database verified |

### 0A codebase and upgrade
| Item | Status |
|---|---|
| Port greenhub saas~18.3 → 19, branch `19.0` | Done, pushed (a1d8bac). Installs; its 15 tests pass. |
| `docs/CODEBASE_MAP.md` (routes, crons, models) | **Not built** |
| Verify on an Odoo upgrade-service copy of production | **Not done.** Replaced, by the user's choice, with a pseudonymised sample copy. |
| Characterisation tests of greenhub computes, API smoke tests | **Not built** |

### 4.1 field additions
| Field | Status |
|---|---|
| payment.log `gh_category` | Partial: computed by `gh.payment.category.rule` at query time, not stored on payment.log |
| contract `gh_exit_type` | Partial: computed by `gh.exit.type.rule` (closure reason on contract or termination; upgrade link) |
| contract `gh_default_date`, `gh_write_off_date/amount`, `gh_repossession_date` | Partial: derived (default.tracking, written-off schedules, termination date); not stored |
| contract `gh_ever_late_fee` | Partial: derived (penalty date/invoice on schedules, penalty totals) |
| rider learner licence | **Not built** (needs a greenhub field; the licence panel says learners aren't recorded) |
| 30-day licence expiry activity | Done: daily cron, one to-do per rider for the responsible user, no duplicates |
| vehicle `gh_category`, `gh_ever_contracted` | Partial: computed by ordered `gh.vehicle.category.rule`; not stored |

Not storing them keeps the module read-only on greenhub models; the cost is that list views of
contracts/vehicles can't be filtered by these values yet.

### 4.2–4.5 data layer
| Item | Status |
|---|---|
| DPD | Done |
| Config models, product groups, accounting settings | Done (+ payment-category, exit-type and vehicle-category rules). The custom account mapping was removed on 6 Nov: financial figures are read from Odoo (see ACCOUNTING_ALIGNMENT.md) |
| Risk bands (UGX or instalment multiples) | Done. **Finding:** the brief's rounded multiples (0.38, 0.95 …) put exactly 30,000 and 75,000 UGX in the wrong band; defaults are 4-decimal (0.3801 …) and reproduce the spreadsheet's UGX bands exactly. The >236,820 gap now lands in Critical. |
| PAR by DPD buckets, configurable | Done (UGX-band variant not built) |
| `gh.kpi.snapshot`, `gh.contract.snapshot`, weekly + month-end cron, frozen periods | Done |
| Manual recompute | Done ("Snapshot today" and backfill with "Overwrite") |
| Backfill wizard + comparison CSV | Done. 36 weeks + 8 month ends in ~1.3 s on the sample. Assumptions are listed in code and on the pages. |

### 5.1 Riders & Customers
| Code | Status | Note |
|---|---|---|
| R01–R05 | Done | Youth by date of birth at the as-of date; riders with no DOB shown separately |
| R06, R07, R09 | Done | |
| R08 | Done | archived products still map |
| R10–R12 retention | Done | upgrades count as retained |
| R13 growth | Done | identity checked every period; exits split planned / default / other |
| R14 referral | Done | **Finding:** Green Hub records the source on the rider's UTM source; the selection field is empty for every active rider |
| R15, R16 | Done | R16 uses tracked vehicle state and today's tags |
| R17 accidents | Partial | count and rate per 100 bikes; no breakdown by type because `fleet.vehicle.accident` has no type field |
| R18 licences | Partial | counts, expiring list and reminder activity; learner permits not recorded in Odoo |

### 5.2 Portfolio & Credit Risk
| Code | Status | Note |
|---|---|---|
| P01–P12 | Done | P04 shown as "arrears in default" in the default block |
| P13 default rate | Done | definition is a setting: "episode" (default) or "payment status only" |
| P14–P17, P19 losses | Done | posted journal items on the write-off ledger picked in settings (live: **601058 Lease Default**, the account the WROFF journal posts to, not 501002); loss/revenue % uses Odoo's P&L Revenue line |
| P18 default trend | Done | new defaults from default.tracking events; outstanding from snapshots |
| P20 repossession → refinancing | Done, needs config | requires exit types |
| P21 arrears recovery | Done | |
| P22 trends | Done | |

### 5.3 Collections & Payments
| Code | Status | Note |
|---|---|---|
| C01–C04 | Done | C03 also shows instalment compliance |
| C05–C07 targets | Done | pro-rata by elapsed days |
| C08, C09 rates | Done | C09 counts available bikes at the group's standard instalment (setting, else median) |
| C10, C11 | Done | |
| C12, C13 | Done | by product group (the mockup's "bike model") |
| C14 shared default block | Done | |
| C15, C16 financing | Done, needs config | **Changed 6 Nov:** custom lender tables removed. Principal repaid = debits on the loan liability accounts picked in settings; interest = debits on the lender interest accounts. Actual repayments, no forward schedule (Odoo Loans app is not used by Green Hub) |
| C17 forecast | Done | risk-adjusted uses trailing per-category rates from snapshots |
| Logs vs Odoo payments (new, 6 Nov) | Done | side by side, matched on `payment_reference` (live never fills `payment.log.payment_id`) |
| USD conversion | Done | Odoo rates; only when a lender currency is set |

### 5.4 Budget
| Item | Status | Note |
|---|---|---|
| B01 import (.xlsx, validation, template) | Done | unknown codes, bad periods, duplicates block the import; missing months warn |
| B02 versions, approve + lock, revisions | Done | approved versions refuse edits and deletion |
| B03–B05, B11 financial | Done | **Changed 6 Nov:** read from Odoo's P&L report engine and Odoo report budgets (live has APRIL/MAY BUDGET, dated 2024-25; finance's 2026 budgets are analytic budgets, shown in their own panel). Tiles are Revenue, Gross profit, EBITDA, Net profit; B11 "financing costs" is replaced by Net profit because Odoo's P&L has no financing line (interest sits in Other Expenses). EBITDA is a line of the "GreenHub P&L (EBITDA)" variant in Accounting › Reporting, created from settings |
| B06–B10 operational | Done | end-date basis for portfolio counts |
| B12 year-end outlook | Done | EBITDA YTD from Odoo + the Odoo report budget chosen as Forecast budget for the rest of the year |
| Weekly budget rule | Done | monthly ÷ days, shown on the page (operational targets; P&L budgets follow Odoo) |
| Analytic budgets (Odoo Budgets app) | Done (6 Nov) | every budget overlapping the period with planned, theoretical, achieved and % exactly as Odoo computes them; line → Odoo's achieved entries, budget → Odoo form, "Report" → Odoo budget analysis |

### 7 and 8
| Item | Status |
|---|---|
| Odoo 19 APIs (OWL, `_read_group`, `privilege_id`, cron without numbercall) | Done |
| Performance < 1.5 s per dashboard | Sample: 0.14–0.22 s. Not yet measured at full volume. |
| Checks 1–6 (sums, P01 ≥ R01, R13 identity, C04 categories) | Done, shown in each filter bar |
| Check 7 (live snapshot = reconstruction for the same week) | Done: the backfill compares every frozen live period and reports differences |
| Check 8 (backfill CSV vs Green Hub's sheets) | CSV built; the comparison itself is Green Hub's sign-off step |
| Check 9 baseline (197 / 27 / 170 …) | Verified on the full neutralised copy by SQL: 197, 27, 170 match; youth is 163 by DOB (+6 without DOB) vs 168 |

## 3. Data findings for Green Hub

1. Referral sources are on the UTM source, not "How did you hear".
2. Bikes stay in state "Active" after their contract is terminated (R07 check flags them).
3. `default.tracking` rows are never closed ("ongoing" for all 231); `pending_termination` is never set,
   so "currently in default" depends on the definition chosen (setting).
4. Terminated contracts have no closure reason on the contract; some have it on the termination record.
   "Upgraded" closures never link to the new contract.
5. Payment logs are never linked to an instalment, so receipts are classified by purpose prefix and past
   arrears can only be approximated.
6. An archived product "NIU" is still on running contracts.
7. TVS ALPHA E-HLX and WYLEX ROROSHIP DUAL are in no product group (Green Hub to decide).
8. `fleet_operations` installs an active Gmail mail server record ("Vehicle Service") on any new database.

9. **Write-offs post to 601058 "Lease Default"**, not to 501002 "Bad Debts Written Off" (the WROFF
   journal's only expense account in 2026). Settings now suggest the account the write-off journal uses.
10. **Payment logs reconcile exactly with Odoo payments** (Oct–Nov 2026): 1,918 logs = 1,918 customer
    payments, UGX 83,646,431 on both sides, matched on `payment_reference`; `payment.log.payment_id` is
    never filled. 35 payments are dated a day apart from their log (period edges can differ). The other 90
    Odoo payments are 27 supplier payments and 63 zero-value receipts without a reference.
11. Live's P&L report budgets (APRIL/MAY BUDGET) cover Jul 2024–May 2025 only; 2026 budgets are kept as
    analytic budgets (JIF project, Fleet operations). The 2026 P&L budget column needs a 2026 report budget.
12. 252m of 2026 "Other Income" is Grant Re-imbursement (402004): Net Profit is positive while Operating
    Income is negative.
13. No lender interest-expense account exists; loan interest is presumably posted to the loan accounts or
    bank charges. The lender card shows principal debits only until finance names the interest account.
14. GreenHub's install calls its own `/api/closure-reasons` over HTTP and logs connection errors when the
    server isn't listening (seen on the fresh-install test; harmless, pre-existing).

## 4. Sample-data effects (not defects)

The local sample keeps open instalments and only the last eight weeks of paid ones per contract. Older
months therefore have receipts but few dues: collection rates before September and past arrears are
distorted. Last month's figures (full data) are realistic.

The accounting sample holds up to 100 whole entries per journal per month, so P&L amounts are a fraction
of live (e.g. Revenue YTD 19.1m in the sample); ratios and the dashboard = Odoo equality are what it proves.

## 5. Local test data (greenhub19_local)

Built by `tools/local_test_data/sample_accounting_from_live_copy.py` from the neutralised live copy
(read-only access granted for the run and revoked after):

| Data | Origin |
|---|---|
| Chart of accounts (292), journals, analytic plans/accounts | real (cashbooks named after people renamed Cashbook A/B) |
| 4,693 posted 2026 journal entries | real amounts, dates, accounts, analytic tags; up to 100 entries per journal per month + every analytic entry; partners pseudonymised, labels = account name |
| 420 customer payments (Oct–Nov) | real, same references as the sampled payment logs |
| APRIL / MAY BUDGET report budgets, 3 analytic budgets (JIF project ×2, Fleet operations) | real |
| "SIMULATED 2026 P&L budget", "SIMULATED 2026 forecast Nov-Dec" (report budgets) | simulated: each month's actual per account × 0.85–1.15 (Nov–Dec: Jan–Oct average) |
| "SIMULATED 2026 cost budget by cost plan" (analytic) | simulated: achieved × 1.05–1.6, or 3–25m where nothing was spent |
| Dashboard settings | P&L = GreenHub P&L (EBITDA); loss ledger 601058; loans 200002–200006; add-backs 501024–501027 |

Backup before the import: `~/greenhub_live_copy/greenhub19_local_before_accounting_sample_20261106.dump`.

## 6. Quality analysis (6 Nov night)

| Check | Result |
|---|---|
| Automated tests | 37/37 pass (33 server incl. 8 accounting-alignment and 5 drill-through tests, 4 headless browser) |
| Dashboard = Odoo | tests post entries/budgets and compare every P&L line, budget column, analytic achieved, loss and repayment figure with Odoo's own computation |
| Fresh install on an empty database | passes; the P&L variant (12 lines incl. GH_DA, GH_EBITDA) and settings link are created by the install hook; upgrades get it from `migrations/19.0.1.1.0` |
| Chrome click-through | every figure on all four dashboards (Riders 94, Portfolio 75, Collections 73, Budget 108 targets) opens its records or Odoo report; no errors |
| Screenshots | `build_*.png` in the review folder, all panels load, no panel errors |
| Load time (sample) | 0.07–0.5 s per dashboard; Budget runs Odoo's P&L ~14× per load (period, month, 10 months, outlook) — measure on full live volume before go-live |
| Bugs found and fixed in this round | licence tile crashed on click; recovery cell opened the wrong month; budget % column overwrote the budget figure; matched-payments count was always 0 on live data (wrong key); variant could duplicate when renamed; loss-ledger guess was the wrong account |
| Open | P&L budget column empty on live until a 2026 report budget exists; lender interest account to be named; performance at full volume; CODEBASE_MAP and greenhub characterisation tests (brief 0A) not built; ported `fleet_operations` / `requisitions` branches not pushed (client repos, awaiting go-ahead) |
