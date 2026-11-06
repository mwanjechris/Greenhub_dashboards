"""Copy a small, linked, pseudonymised sample of Green Hub data from the
neutralised saas~18.3 copy into the local Odoo 19 test database.

Usage (as a PostgreSQL superuser, Odoo stopped or idle):
    python -I sample_from_live_copy.py SOURCE_DB TARGET_DB

Sample: about 50 contracts (40 running/paused spread across products plus
10 closed/terminated/expired), their riders, partners and bikes, 15 other
vehicles in a spread of states, and only the child rows those records need.
Personal data (names, phones, emails, IDs, addresses, free text) is replaced.
Nothing is ever written to SOURCE_DB.
"""
import re
import sys
from collections import defaultdict

import psycopg2
import psycopg2.extras

SRC_DB, DST_DB = sys.argv[1], sys.argv[2]
src = psycopg2.connect(dbname=SRC_DB)
src.set_session(readonly=True)
dst = psycopg2.connect(dbname=DST_DB)
s = src.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
d = dst.cursor()

PII = re.compile(r"(address|location|description|note|memo|phone|whatsapp|email|emergency|home_location|home_description|tax_identification|"
                 r"national_id|license_number|insurance_provider|previous_employer|mobile_money_contact|"
                 r"street|city|zip|vat|website|comment|signup|barcode|^ref$|nin|passport|next_of_kin|"
                 r"unpaid_load_history|reason_for_vehicle|current_income_sources|request_data|"
                 r"vin_sn|license_plate|chassis|engine_no)", re.I)
# People tables: every text column is blanked unless listed here (allowlist, not patterns).
TEXT_ALLOW = {
    "res_partner": {"type", "lang", "tz", "gender", "name", "complete_name", "autopost_bills",
                    "invoice_sending_method", "invoice_edi_format", "peppol_eas", "ubl_cii_format"},
    "rider": {"state", "gender", "type", "rider_status", "source_of_information", "bike_type_status",
              "license_status", "utilization_indicator", "valid_driving_permit", "bike_ownership",
              "x_studio_gender", "prior_commercial_experience", "prior_riding_experience", "first_name", "last_name"},
}
idmap = defaultdict(dict)          # table -> {source id: target id}
stats = defaultdict(int)


def q(sql, args=()):
    s.execute(sql, args)
    return s.fetchall()


def ids(sql, args=()):
    return [r["id"] for r in q(sql, args)]


def dst_one(sql, args=()):
    d.execute(sql, args)
    row = d.fetchone()
    return row[0] if row else None


def dst_columns(table):
    d.execute("""select column_name, is_nullable, data_type from information_schema.columns
                 where table_schema='public' and table_name=%s""", (table,))
    return {r[0]: (r[1] == "YES", r[2]) for r in d.fetchall()}


def dst_fks(table):
    d.execute("""select a.attname, cf.relname from pg_constraint c
                 join pg_class t on t.oid=c.conrelid join pg_class cf on cf.oid=c.confrelid
                 join pg_attribute a on a.attrelid=t.oid and a.attnum=c.conkey[1]
                 where c.contype='f' and t.relname=%s""", (table,))
    return dict(d.fetchall())


DEFAULTS = {
    "res_users": 2,
    "res_company": dst_one("select min(id) from res_company"),
    "res_currency": dst_one("select id from res_currency where name='UGX'"),
    "uom_uom": dst_one("select min(id) from uom_uom"),
    "product_category": dst_one("select min(id) from product_category"),
    "res_country": dst_one("select id from res_country where code='UG'"),
}


_local_defaults = {}


def local_default(table, col, dtype):
    """Value for a NOT NULL column the 18.3 source lacks: copy it from an existing local row."""
    key = (table, col)
    if key not in _local_defaults:
        d.execute(f'select "{col}" from {table} where "{col}" is not null limit 1')
        row = d.fetchone()
        if row:
            value = row[0]
        elif dtype == "boolean":
            value = False
        elif dtype in ("integer", "numeric", "double precision", "bigint"):
            value = 0
        else:
            value = ""
        if isinstance(value, (dict, list)):
            value = psycopg2.extras.Json(value)
        _local_defaults[key] = value
    return _local_defaults[key]


def copy_rows(table, rows, pseudo=None, defer=(), keep=(), match_name=False):
    """Insert rows into DST, remapping every FK; returns {src id: dst id}."""
    if not rows:
        return {}
    cols, fks = dst_columns(table), dst_fks(table)
    out = {}
    for row in rows:
        vals = {}
        for col, value in row.items():
            if col == "id" or col not in cols or col in defer:
                continue
            nullable, dtype = cols[col]
            if col in fks and value is not None and col not in keep:
                ref = fks[col]
                if ref == table and value not in idmap[table]:
                    value = None
                elif ref in idmap and ref != "res_users":
                    value = idmap[ref].get(value)
                elif ref in DEFAULTS:
                    value = DEFAULTS[ref]
                else:
                    value = None
                if value is None and not nullable:
                    break
            if isinstance(value, str) and dtype in ("character varying", "text") and (
                    (table in TEXT_ALLOW and col not in TEXT_ALLOW[table]) or PII.search(col)):
                value = None if nullable else "redacted"
            if table in TEXT_ALLOW and dtype in ("jsonb", "json") and col not in TEXT_ALLOW[table] \
                    and isinstance(value, dict) and any(isinstance(x, str) and len(x) > 12 for x in value.values()):
                value = None if nullable else value
            if dtype in ("jsonb", "json") and value is not None:
                value = psycopg2.extras.Json(value)
            vals[col] = value
        else:
            if pseudo:
                for col, value in pseudo(row).items():
                    if col in cols:
                        if cols[col][1] in ("jsonb", "json") and isinstance(value, str):
                            value = psycopg2.extras.Json({"en_US": value})
                        vals[col] = value
            if match_name:
                name = row.get("name")
                label = name.get("en_US") if isinstance(name, dict) else name
                d.execute(f"select id from {table} where (case when jsonb_typeof(to_jsonb(name)) = 'object' "
                          f"then to_jsonb(name)->>'en_US' else name::text end) = %s limit 1", (label,))
                found = d.fetchone()
                if found:
                    out[row["id"]] = found[0]
                    stats[table + " (matched existing)"] += 1
                    continue
            for col, (nullable, dtype) in cols.items():
                if col != "id" and not nullable and vals.get(col) is None:
                    vals[col] = local_default(table, col, dtype)
            names = list(vals)
            d.execute(f'insert into {table} ({",".join(chr(34)+n+chr(34) for n in names)}) '
                      f'values ({",".join(["%s"]*len(names))}) returning id', [vals[n] for n in names])
            out[row["id"]] = d.fetchone()[0]
            stats[table] += 1
            continue
        stats[table + " (skipped: required link outside sample)"] += 1
    idmap[table].update(out)
    return out


def fetch(table, where, args=()):
    return q(f"select * from {table} where {where} order by id", args)


# ---------------------------------------------------------------- choose sample
active = []
for product_name, n in (("Thunder - Zembo lease", 25), ("Lease Principal iQube", 10)):
    active += ids("""select c.id from rider_contract c join product_product p on p.id=c.product_product_id
                     join product_template t on t.id=p.product_tmpl_id
                     where c.state in ('running','pause') and t.name->>'en_US'=%s order by c.id limit %s""",
                  (product_name, n))
active += ids("""select c.id from rider_contract c join product_product p on p.id=c.product_product_id
                 join product_template t on t.id=p.product_tmpl_id
                 where c.state in ('running','pause') and t.name->>'en_US' ilike 'niu%%' order by c.id limit 5""")
closed = ids("select id from rider_contract where state in ('closed','terminated','expired') order by id limit 10")
contract_ids = active + closed
contracts = fetch("rider_contract", "id = any(%s)", (contract_ids,))
rider_ids = sorted({c["rider_id"] for c in contracts if c["rider_id"]})
bike_ids = {c["bike_id"] for c in contracts if c["bike_id"]}
other_bikes = ids("""select id from (select id, row_number() over (partition by state order by id) rn
                     from fleet_vehicle where active and not (id = any(%s))) x where rn <= 3 order by id limit 15""",
                  (list(bike_ids),))
tagged = ids("""select distinct vehicle_tag_id as id from fleet_vehicle_vehicle_tag_rel r join fleet_vehicle_tag t
                on t.id=r.tag_id where t.name->>'en_US' <> 'Customer bike' and not (vehicle_tag_id = any(%s))
                order by 1 limit 6""", (list(bike_ids),))
vehicle_ids = sorted(bike_ids | set(other_bikes) | set(tagged))
riders = fetch("rider", "id = any(%s)", (rider_ids,))
vehicles = fetch("fleet_vehicle", "id = any(%s)", (vehicle_ids,))

partner_ids = {r["partner_id"] for r in riders} | {c["partner_id"] for c in contracts} | \
              {v["driver_id"] for v in vehicles}
partner_ids.discard(None)

# ---------------------------------------------------------------- dimensions
copy_rows("fleet_vehicle_model_brand", fetch("fleet_vehicle_model_brand", "true"), match_name=True)
copy_rows("fleet_vehicle_model", fetch("fleet_vehicle_model", "true"))
copy_rows("fleet_vehicle_tag", fetch("fleet_vehicle_tag", "true"), match_name=True)
copy_rows("closure_reason", fetch("closure_reason", "true"), match_name=True)
copy_rows("utm_source", fetch("utm_source", "id in (select source_id from rider where id = any(%s))", (rider_ids,)), match_name=True)
product_ids = sorted({c["product_product_id"] for c in contracts if c["product_product_id"]})
tmpl_ids = ids("select product_tmpl_id as id from product_product where id = any(%s)", (product_ids,))
copy_rows("product_template", fetch("product_template", "id = any(%s)", (tmpl_ids,)))
copy_rows("product_product", fetch("product_product", "id = any(%s)", (product_ids,)))

# ---------------------------------------------------------------- people + vehicles
rider_no = {pid: n for n, pid in enumerate(sorted(partner_ids), 1)}
copy_rows("res_partner", fetch("res_partner", "id = any(%s)", (list(partner_ids),)),
          pseudo=lambda r: {"name": f"Rider {rider_no[r['id']]:03d}", "complete_name": f"Rider {rider_no[r['id']]:03d}"})
copy_rows("fleet_vehicle", vehicles,
          pseudo=lambda r: {"license_plate": f"UTEST {r['id']:04d}", "name": f"Sample bike {r['id']:04d}"})
for row in q("select * from fleet_vehicle_vehicle_tag_rel where vehicle_tag_id = any(%s)", (vehicle_ids,)):
    if row["tag_id"] in idmap["fleet_vehicle_tag"]:
        d.execute("insert into fleet_vehicle_vehicle_tag_rel values (%s, %s) on conflict do nothing",
                  (idmap["fleet_vehicle"][row["vehicle_tag_id"]], idmap["fleet_vehicle_tag"][row["tag_id"]]))
        stats["fleet_vehicle_vehicle_tag_rel"] += 1

copy_rows("rider", riders, defer=("contract_id",),
          pseudo=lambda r: {"first_name": "Rider", "last_name": f"{rider_no.get(r['partner_id'], r['id']):03d}"})
copy_rows("rider_contract", contracts, defer=("upgraded_from_contract_id", "upgraded_to_contract_id"))
for r in riders:
    if r["contract_id"] in idmap["rider_contract"] and r["id"] in idmap["rider"]:
        d.execute("update rider set contract_id=%s where id=%s",
                  (idmap["rider_contract"][r["contract_id"]], idmap["rider"][r["id"]]))
for c in contracts:
    for col in ("upgraded_from_contract_id", "upgraded_to_contract_id"):
        if c.get(col) in idmap["rider_contract"]:
            d.execute(f"update rider_contract set {col}=%s where id=%s",
                      (idmap["rider_contract"][c[col]], idmap["rider_contract"][c["id"]]))

# ---------------------------------------------------------------- children (capped)
copy_rows("payment_schedule", fetch(
    "payment_schedule", """contract_id = any(%s) and (state in ('unpaid','partial','overdue')
       or due_date between current_date - 56 and current_date + 28)""", (contract_ids,)))
recent_logs = q("""select * from (select *, row_number() over (partition by contract_id
       order by attempt_date desc nulls last, id desc) rn from payment_log where contract_id = any(%s)) x
       where rn <= 20 order by id""", (contract_ids,))
copy_rows("payment_log", [{k: v for k, v in r.items() if k != "rn"} for r in recent_logs])
copy_rows("default_tracking", fetch("default_tracking", "contract_id = any(%s)", (contract_ids,)))
copy_rows("fleet_vehicle_accident", fetch("fleet_vehicle_accident", "vehicle_id = any(%s)", (vehicle_ids,)))
copy_rows("loaner_bike_tracking", fetch("loaner_bike_tracking", "loaner_bike = any(%s) or in_service_bike_id = any(%s)",
                                        (vehicle_ids, vehicle_ids)))

# ---------------------------------------------------------------- status history (for the backfill)
d.execute("select f.id, m.model, f.name from ir_model_fields f join ir_model m on m.id=f.model_id "
          "where (m.model, f.name) in (('rider.contract','state'),('rider.contract','payment_state'),('fleet.vehicle','state'))")
dst_fields = {(model, name): fid for fid, model, name in d.fetchall()}
src_fields = {(r["model"], r["name"]): r["id"] for r in q(
    """select f.id, m.model, f.name from ir_model_fields f join ir_model m on m.id=f.model_id
       where (m.model, f.name) in (('rider.contract','state'),('rider.contract','payment_state'),('fleet.vehicle','state'))""")}
for model, table, res_ids in (("rider.contract", "rider_contract", contract_ids), ("fleet.vehicle", "fleet_vehicle", vehicle_ids)):
    for msg in q("""select distinct m.* from mail_message m join mail_tracking_value v on v.mail_message_id=m.id
                    where m.model=%s and m.res_id = any(%s) and v.field_id = any(%s) order by m.id""",
                 (model, res_ids, list(src_fields.values()))):
        msg = dict(msg, body=None, res_id=idmap[table][msg["res_id"]], author_id=None, parent_id=None,
                   subject=None, email_from=None, record_name=None, message_id=None, reply_to=None)
        copy_rows("mail_message", [msg], keep=("res_id",))
        for tv in q("select * from mail_tracking_value where mail_message_id=%s and field_id = any(%s)",
                    (msg["id"], list(src_fields.values()))):
            key = next(k for k, v in src_fields.items() if v == tv["field_id"])
            if key in dst_fields:
                copy_rows("mail_tracking_value", [dict(tv, field_id=dst_fields[key])], keep=("field_id",))

dst.commit()
for table, n in sorted(stats.items()):
    print(f"{n:6d}  {table}")
