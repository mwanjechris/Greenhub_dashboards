"""Copy a realistic, pseudonymised slice of Green Hub's accounting into greenhub19_local.

Run inside `odoo-bin shell -d greenhub19_local` (reads the neutralised live copy
`greenhub_live_183_raw` read-only through psycopg2; writes only to the local db):

    odoo-bin shell -c /etc/odoo/odoo.conf -d greenhub19_local < sample_accounting_from_live_copy.py

What it copies (real records, real amounts, real dates):
  * the client's chart of accounts (codes, names, types), journals, analytic plans/accounts
  * posted 2026 journal entries: up to PER_JOURNAL_MONTH whole entries per journal per month
    (balanced, every line kept) + every entry carrying an analytic distribution
  * Odoo customer payments for Oct-Nov 2026: those whose payment_reference matches a payment log
    already in the local sample, plus every live payment that has no payment log at all
  * the two live P&L report budgets (APRIL/MAY BUDGET) and the three live analytic budgets
What it simulates (names start with SIMULATED):
  * a 2026 P&L report budget and a forecast budget, derived from the copied actuals x 0.85-1.15
  * 2026 analytic budgets by department / cost plan
Pseudonymisation: partners map to the already-pseudonymised local riders (deterministic hash),
vendors to "Sample vendor A..E"; line labels become the account name; references are dropped;
cashbooks named after people become "Cashbook A/B".
"""
import hashlib
import random
from collections import defaultdict
from datetime import date

import psycopg2
import psycopg2.extras

PER_JOURNAL_MONTH = 100
SRC_DB = "greenhub_live_183_raw"
YEAR_FROM, AS_OF = date(2026, 1, 1), date(2026, 11, 6)
rnd = random.Random(20261106)

src = psycopg2.connect(dbname=SRC_DB)
src.set_session(readonly=True)
cur = src.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def rows(sql, args=()):
    cur.execute(sql, args)
    return cur.fetchall()


company = env.company
ccy = company.currency_id
Account = env["account.account"].with_company(company)
log = lambda *a: print("[acct-sample]", *a, flush=True)

# ---------------------------------------------------------------- chart of accounts
acc_map = {}
created = 0
for a in rows("select id, code_store->>'1' code, name->>'en_US' name, account_type, reconcile from account_account"):
    local = Account.search([("code", "=", a["code"])], limit=1)
    if not local:
        local = Account.create({"code": a["code"], "name": a["name"], "account_type": a["account_type"],
                                "reconcile": bool(a["reconcile"]) or a["account_type"] in ("asset_receivable", "liability_payable")})
        created += 1
    acc_map[a["id"]] = local.id
log("accounts mapped", len(acc_map), "created", created)

# ---------------------------------------------------------------- currencies, journals
cur_map = {}
for c in rows("select id, name from res_currency"):
    local = env["res.currency"].with_context(active_test=False).search([("name", "=", c["name"])], limit=1)
    if local:
        if not local.active:
            local.active = True
        cur_map[c["id"]] = local.id

PSEUDO_JOURNAL = {"CSH2": "Cashbook A", "CSH3": "Cashbook B"}
jr_map = {}
for j in rows("select id, code, type, name->>'en_US' name, currency_id from account_journal"):
    local = env["account.journal"].search([("code", "=", j["code"]), ("company_id", "=", company.id)], limit=1)
    if not local:
        vals = {"code": j["code"], "type": j["type"], "name": PSEUDO_JOURNAL.get(j["code"], j["name"])}
        if j["currency_id"] and cur_map.get(j["currency_id"]) and cur_map[j["currency_id"]] != ccy.id:
            vals["currency_id"] = cur_map[j["currency_id"]]
        local = env["account.journal"].create(vals)
    jr_map[j["id"]] = local.id
log("journals mapped", len(jr_map))

# ---------------------------------------------------------------- analytic plans / accounts
plan_map, an_map = {}, {}
for p in rows("select id, name->>'en_US' name from account_analytic_plan order by id"):
    local = env["account.analytic.plan"].search([("name", "=", p["name"])], limit=1) or \
        env["account.analytic.plan"].create({"name": p["name"]})
    plan_map[p["id"]] = local
for a in rows("select id, name->>'en_US' name, plan_id from account_analytic_account"):
    plan = plan_map[a["plan_id"]]
    local = env["account.analytic.account"].search([("name", "=", a["name"]), ("plan_id", "=", plan.id)], limit=1) or \
        env["account.analytic.account"].create({"name": a["name"], "plan_id": plan.id})
    an_map[a["id"]] = local.id


def remap_distribution(dist):
    if not dist:
        return False
    out = {}
    for key, pct in dist.items():
        out[",".join(str(an_map[int(k)]) for k in key.split(",") if int(k) in an_map)] = pct
    return {k: v for k, v in out.items() if k} or False


# ---------------------------------------------------------------- partners (pseudonymised)
riders = env["rider"].search([]).mapped("partner_id")
if not riders:
    riders = env["res.partner"].create({"name": "Sample customer"})
vendors = env["res.partner"].search([("name", "like", "Sample vendor ")])
for letter in "ABCDE"[len(vendors):]:
    vendors |= env["res.partner"].create({"name": f"Sample vendor {letter}", "supplier_rank": 1})


def pick(pool, key):
    return pool[int(hashlib.md5(str(key).encode()).hexdigest(), 16) % len(pool)].id


supplier_ids = {r["id"] for r in rows("select distinct partner_id id from account_move where move_type in ('in_invoice','in_refund','in_receipt') and partner_id is not null")}


def partner(src_id):
    if not src_id:
        return False
    return pick(vendors, src_id) if src_id in supplier_ids else pick(riders, src_id)


# ---------------------------------------------------------------- journal entries
already = set(env["account.move"].search([("ref", "=like", "LIVE-SAMPLE %")]).mapped("ref"))
move_ids = [r["id"] for r in rows("""
    with m as (
        select m.id, row_number() over (partition by m.journal_id, date_trunc('month', m.date) order by md5(m.id::text)) rn
          from account_move m
         where m.state = 'posted' and m.date between %s and %s
           and not exists (select 1 from account_payment p where p.move_id = m.id))
    select id from m where rn <= %s
    union
    select distinct l.move_id from account_move_line l join account_move m2 on m2.id = l.move_id
     where l.analytic_distribution is not null and m2.state = 'posted' and m2.date between %s and %s
       and not exists (select 1 from account_payment p where p.move_id = m2.id)""",
    (YEAR_FROM, AS_OF, PER_JOURNAL_MONTH, YEAR_FROM, AS_OF))]
moves = {m["id"]: m for m in rows("select id, date, journal_id, move_type from account_move where id = any(%s) order by date, id", (move_ids,))}
lines = defaultdict(list)
for l in rows("""select move_id, account_id, debit, credit, amount_currency, currency_id, partner_id, analytic_distribution,
                        date_maturity, display_type from account_move_line where move_id = any(%s) order by id""", (move_ids,)):
    if l["display_type"] in ("line_section", "line_subsection", "line_note"):
        continue
    lines[l["move_id"]].append(l)
acc_names = {a.id: a.name for a in Account.browse(list(set(acc_map.values())))}
done = 0
for mid in sorted(moves, key=lambda i: (moves[i]["date"], i)):
    ref = f"LIVE-SAMPLE {mid}"
    if ref in already:
        continue
    m = moves[mid]
    vals_lines = []
    for l in lines[mid]:
        line_ccy = cur_map.get(l["currency_id"]) or ccy.id
        balance = float(l["debit"] or 0) - float(l["credit"] or 0)
        vals = {"account_id": acc_map[l["account_id"]], "debit": float(l["debit"] or 0), "credit": float(l["credit"] or 0),
                "partner_id": partner(l["partner_id"]), "name": acc_names[acc_map[l["account_id"]]],
                "date_maturity": l["date_maturity"]}
        if line_ccy != ccy.id:
            vals.update(currency_id=line_ccy, amount_currency=float(l["amount_currency"] or 0))
        else:
            vals.update(amount_currency=balance)
        dist = remap_distribution(l["analytic_distribution"])
        if dist:
            vals["analytic_distribution"] = dist
        vals_lines.append((0, 0, vals))
    if not vals_lines:
        continue
    move = env["account.move"].with_context(skip_invoice_sync=True, check_move_validity=False).create({
        "move_type": "entry", "journal_id": jr_map[m["journal_id"]], "date": m["date"], "ref": ref,
        "line_ids": vals_lines})
    move.action_post()
    done += 1
    if done % 250 == 0:
        env.cr.commit()
        log("entries posted", done)
env.cr.commit()
log("journal entries posted", done, "of", len(moves))

# ---------------------------------------------------------------- Odoo customer payments (Oct-Nov)
local_refs = set(env["payment.log"].search([("payment_reference", "!=", False)]).mapped("payment_reference"))
log_partner = {l.payment_reference: l.partner_id.id for l in env["payment.log"].search([("payment_reference", "in", list(local_refs))])}
have = set(env["account.payment"].search([("payment_reference", "!=", False)]).mapped("payment_reference"))
pays = rows("""
    select p.id, p.amount, p.payment_reference, p.memo, p.partner_id, p.journal_id, m.date, p.currency_id,
           exists (select 1 from payment_log l where l.payment_reference = p.payment_reference) has_log
      from account_payment p join account_move m on m.id = p.move_id
     where p.payment_type = 'inbound' and p.partner_type = 'customer' and m.state = 'posted'
       and m.date between '2026-10-01' and %s""", (AS_OF,))
made = 0
for p in pays:
    if p["payment_reference"] in have or not (p["payment_reference"] in local_refs or not p["has_log"]):
        continue
    if not p["amount"] or float(p["amount"]) <= 0:
        continue  # GreenHub forbids zero-value payments in bank/cash journals
    memo = p["memo"] if p["memo"] and p["memo"].isupper() and len(p["memo"]) < 20 else False
    pay = env["account.payment"].create({
        "payment_type": "inbound", "partner_type": "customer", "amount": float(p["amount"]), "date": p["date"],
        "journal_id": jr_map[p["journal_id"]], "payment_reference": p["payment_reference"], "memo": memo,
        "partner_id": log_partner.get(p["payment_reference"]) or partner(p["partner_id"]),
        "currency_id": cur_map.get(p["currency_id"]) or ccy.id})
    pay.action_post()
    made += 1
env.cr.commit()
log("customer payments posted", made, "(matched to local logs + live payments without a log)")

# ---------------------------------------------------------------- P&L report budgets
Budget, Item = env["account.report.budget"], env["account.report.budget.item"]
for b in rows("select id, name from account_report_budget"):
    if Budget.search([("name", "=", b["name"])]):
        continue
    nb = Budget.create({"name": b["name"]})
    Item.create([{"budget_id": nb.id, "account_id": acc_map[i["account_id"]], "amount": float(i["amount"]), "date": i["date"]}
                 for i in rows("select account_id, amount, date from account_report_budget_item where budget_id = %s", (b["id"],))
                 if i["account_id"] in acc_map])
pl_types = ("income", "income_other", "expense", "expense_direct_cost", "expense_depreciation", "expense_other")
actual = defaultdict(float)
for acc, month, bal in env["account.move.line"]._read_group(
        [("parent_state", "=", "posted"), ("date", ">=", YEAR_FROM), ("date", "<=", AS_OF),
         ("account_id.account_type", "in", pl_types), ("company_id", "=", company.id)],
        ["account_id", "date:month"], ["balance:sum"]):
    actual[(acc.id, month.month)] = bal
accounts = {a for a, _m in actual}


def simulated(name, months, jitter=0.15):
    if Budget.search([("name", "=", name)]):
        return Budget.search([("name", "=", name)], limit=1)
    b = Budget.create({"name": name})
    items = []
    for acc in accounts:
        known = [actual[(acc, m)] for m in range(1, 11) if (acc, m) in actual]
        avg = sum(known) / len(known) if known else 0.0
        for m in months:
            # past months: that month's actual (none -> no budget line); Nov/Dec: the Jan-Oct average
            base = actual.get((acc, m)) if m <= 10 else avg
            if base:
                items.append({"budget_id": b.id, "account_id": acc, "date": date(2026, m, 1),
                              "amount": round(base * rnd.uniform(1 - jitter, 1 + jitter), -3)})
    Item.create(items)
    return b


approved = simulated("SIMULATED 2026 P&L budget (local test)", range(1, 13))
forecast = simulated("SIMULATED 2026 forecast Nov-Dec (local test)", range(11, 13), jitter=0.08)
log("report budgets", Budget.search_count([]))

# ---------------------------------------------------------------- analytic budgets
BA, BL = env["budget.analytic"], env["budget.line"]


def column(plan):
    return plan._column_name()


live_cols = {1: "account_id"} | {pid: f"x_plan{pid}_id" for pid in plan_map if pid != 1}
live_budgets = rows("select id, name, budget_type, state, date_from, date_to, parent_id from budget_analytic order by id")
seen_names = defaultdict(int)
for b in live_budgets:
    seen_names[b["name"]] += 1
    # idempotent by name + occurrence (live has two budgets named "JIF project ..."; local states differ after confirm)
    if BA.search_count([("name", "=", b["name"])]) >= seen_names[b["name"]]:
        continue
    nb = BA.create({"name": b["name"], "budget_type": b["budget_type"], "date_from": b["date_from"], "date_to": b["date_to"]})
    for l in rows("select * from budget_line where budget_analytic_id = %s", (b["id"],)):
        vals = {"budget_analytic_id": nb.id, "budget_amount": float(l["budget_amount"] or 0)}
        for pid, col in live_cols.items():
            if l.get(col) and l[col] in an_map:
                vals[column(plan_map[pid])] = an_map[l[col]]
        BL.create(vals)
    if b["state"] in ("confirmed", "revised", "done"):
        nb.action_budget_confirm()
        if b["state"] == "done":
            nb.action_budget_done()

sim_name = "SIMULATED 2026 cost budget by cost plan (local test)"
if not BA.search([("name", "=", sim_name)]):
    sb = BA.create({"name": sim_name, "budget_type": "expense", "date_from": YEAR_FROM, "date_to": date(2026, 12, 31)})
    achieved = defaultdict(float)
    for al in env["account.analytic.line"].search([("date", ">=", YEAR_FROM)]):
        for plan in plan_map.values():
            acc = al[column(plan)] if column(plan) in al._fields else False
            if acc:
                achieved[(plan.id, acc.id)] += -al.amount
    for plan in plan_map.values():
        for acc in env["account.analytic.account"].search([("plan_id", "=", plan.id)]):
            got = achieved.get((plan.id, acc.id), 0.0)
            amount = round((got * rnd.uniform(1.05, 1.6)) if got > 0 else rnd.uniform(3e6, 25e6), -4)
            BL.create({"budget_analytic_id": sb.id, column(plan): acc.id, "budget_amount": amount})
    sb.action_budget_confirm()
log("analytic budgets", BA.search_count([]), "lines", BL.search_count([]))

# ---------------------------------------------------------------- dashboard settings for the local test
cfg = env["gh.dashboard.config"]._get_config()
code = lambda c: Account.search([("code", "=", c)], limit=1)
cfg.write({
    "budget_id": approved.id, "forecast_budget_id": forecast.id,
    "default_loss_account_ids": [(6, 0, code("601058").ids)],  # live WROFF journal posts here
    "loan_account_ids": [(6, 0, Account.search([("code", "in", ["200002", "200003", "200004", "200005", "200006"])]).ids)],
    "ebitda_addback_account_ids": [(6, 0, Account.search([("code", "in", ["501024", "501025", "501026", "501027"])]).ids)],
})
if not cfg.pl_report_id:
    cfg.action_create_pl_variant()
env.cr.commit()
log("settings: budget", approved.name, "| forecast", forecast.name, "| P&L", cfg.pl_report_id.name)
