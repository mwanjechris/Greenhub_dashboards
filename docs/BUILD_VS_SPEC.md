# Green Hub Dashboards: build vs mockup and build spec

Compared on 6 Nov 2026 against `GREENHUB_DASHBOARDS_REBUILD.md` (the brief), *Odoo Dashboard
Specifications 2.0* and `greenhub_dashboard_mockups.html`. Verified on a local Odoo 19 database holding
a pseudonymised ~50-contract sample of the live data (all integrations neutralised).

Status key: **Done** = built and tested · **Partial** = built with a stated gap · **Not built**.

## 1. Against the mockup

| Tab | Layout & copy | Differences |
|---|---|---|
| Riders & Customers | Same header, filter bar, scorecard clusters, tables, charts and order | As-of is a list of snapshot week ends, not a free date picker. X-axis shows dates, not week numbers. |
| Portfolio & Credit Risk | Same, incl. 100% stacked risk/PAR bars, shared default block, recovery table, three trend charts | Risk rule text is generated from settings, so wording differs slightly. |
| Collections & Payments | Same, incl. category-vs-target table, lender-repayment card (from the GL), GreenHub logs vs Odoo payments side by side, forecast, compact default strip | Currency toggle shows only when a lender currency is set. |
| Budget & Performance | Same, incl. version selector, P&L table, outlook card, ops KPIs, versions table with Import | Hero and P&L show "—" until ledger accounts are mapped (by design: never a fake 0). |

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
| Read-only on business data | Done. No greenhub records are written. |
| Unit tests + reconciliation tests | Done: 20 server tests + 4 headless-browser tests, all passing |

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
| P14–P17, P19 losses | Done, needs config | read journal items on accounts mapped to "Default losses" and revenue roles |
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
| USD conversion | Done | Odoo rates; only when a lender currency is set |

### 5.4 Budget
| Item | Status | Note |
|---|---|---|
| B01 import (.xlsx, validation, template) | Done | unknown codes, bad periods, duplicates block the import; missing months warn |
| B02 versions, approve + lock, revisions | Done | approved versions refuse edits and deletion |
| B03–B05, B11 financial | Done | **Changed 6 Nov:** read from Odoo's P&L report engine and Odoo report budgets (the budgets finance already keeps: APRIL/MAY BUDGET on live). Tiles are Revenue, Gross profit, EBITDA, Net profit; B11 "financing costs" is replaced by Net profit because Odoo's P&L has no financing line (interest sits in Other Expenses). EBITDA is a line of the "GreenHub P&L (EBITDA)" variant in Accounting › Reporting, created from settings |
| B06–B10 operational | Done | end-date basis for portfolio counts |
| B12 year-end outlook | Done | EBITDA YTD from Odoo + the Odoo report budget chosen as Forecast budget for the rest of the year |
| Weekly budget rule | Done | monthly ÷ days, shown on the page |

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

## 4. Sample-data effects (not defects)

The local sample keeps open instalments and only the last eight weeks of paid ones per contract. Older
months therefore have receipts but few dues: collection rates before September and past arrears are
distorted. Last month's figures (full data) are realistic. No journal entries were copied, so all P&L
lines show "—".
