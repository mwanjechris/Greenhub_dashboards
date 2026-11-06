# Local test data tools (not loaded by Odoo)

Scripts that built the pseudonymised `greenhub19_local` test database from the neutralised live copy.
They read the source database read-only and write only to the local database. No credentials inside.

| Script | What it does |
|---|---|
| `sample_from_live_copy.py` | ~50 records per table of riders, contracts, vehicles, schedules, payment logs; people's text replaced (allowlist) |
| `sample_addendum.py` | restores payment-memo prefixes and copies terminations |
| `sample_accounting_from_live_copy.py` | chart of accounts, journals, analytic plans, 2026 journal entries (stratified), Oct–Nov customer payments, live + simulated report and analytic budgets, dashboard settings. Idempotent. |

Run with `odoo-bin shell -c <conf> -d greenhub19_local < script.py`; the odoo role needs temporary
SELECT on the live copy (grant before, revoke after). Never run against a production database.
