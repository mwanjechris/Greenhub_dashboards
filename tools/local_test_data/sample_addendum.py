"""Second pass for the sample: memo category prefixes and contract terminations.

- payment_log.mobile_money_contact: keep only the purpose prefix (text before ' - '),
  so the number plate never reaches the copy.
- contract_termination: copy the rows of sampled contracts with all free text blanked,
  link rider_contract.termination_id.
Matching: payment_reference for logs, contract name for contracts. SOURCE is read-only.
"""
import sys
import psycopg2
import psycopg2.extras

src = psycopg2.connect(dbname=sys.argv[1]); src.set_session(readonly=True)
dst = psycopg2.connect(dbname=sys.argv[2])
s, d = src.cursor(), dst.cursor()

d.execute("select payment_reference from payment_log where payment_reference is not null")
refs = [r[0] for r in d.fetchall()]
s.execute("select payment_reference, upper(trim(split_part(mobile_money_contact, ' - ', 1))) from payment_log "
          "where payment_reference = any(%s) and mobile_money_contact is not null", (refs,))
n = 0
for ref, prefix in s.fetchall():
    d.execute("update payment_log set mobile_money_contact=%s where payment_reference=%s", (prefix, ref)); n += d.rowcount
print("payment_log memo prefixes restored:", n)

d.execute("select id, name from rider_contract")
dst_contracts = {name: cid for cid, name in d.fetchall() if name}
s.execute("select c.name, t.id, t.date, t.state, t.closure_reason_id, cr.name->>'en_US', t.total_outstanding_written_off, "
          "c.termination_date from rider_contract c join contract_termination t on t.id = c.termination_id "
          "left join closure_reason cr on cr.id = t.closure_reason_id where c.name = any(%s)",
          (list(dst_contracts),))
d.execute("select id, name->>'en_US' from closure_reason")
reasons = {name: rid for rid, name in d.fetchall()}
d.execute("select column_name, is_nullable from information_schema.columns where table_name='contract_termination'")
cols = dict(d.fetchall())
m = 0
for cname, tid, tdate, tstate, _rid, rname, written_off, cdate in s.fetchall():
    vals = {"contract_id": dst_contracts[cname], "date": tdate or cdate, "state": tstate,
            "closure_reason_id": reasons.get(rname), "total_outstanding_written_off": written_off,
            "create_uid": 2, "write_uid": 2, "create_date": tdate, "write_date": tdate}
    vals = {k: v for k, v in vals.items() if k in cols}
    for col, nullable in cols.items():
        if nullable == "NO" and col not in vals and col != "id":
            d.execute(f'select "{col}" from contract_termination where "{col}" is not null limit 1')
            row = d.fetchone()
            vals[col] = row[0] if row else (False if col.startswith(("is_", "has_")) else 0)
    names = list(vals)
    d.execute(f'insert into contract_termination ({",".join(names)}) values ({",".join(["%s"]*len(names))}) returning id',
              [vals[k] for k in names])
    new_id = d.fetchone()[0]
    d.execute("update rider_contract set termination_id=%s where id=%s", (new_id, dst_contracts[cname])); m += 1
print("contract_termination rows:", m)
dst.commit()
